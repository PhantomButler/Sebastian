# sebastian/permissions/gate.py
from __future__ import annotations

import copy
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.config import settings
from sebastian.core.protocols import ApprovalManagerProtocol
from sebastian.core.tool import get_tool
from sebastian.core.tool_context import _current_tool_ctx
from sebastian.core.types import ToolResult
from sebastian.permissions.reviewer import PermissionReviewer
from sebastian.permissions.types import PermissionTier, ToolCallContext

logger = logging.getLogger(__name__)

# 静态高危 Bash 命令检测表。
# 每条规则：(正则, 人类可读描述)。
# 匹配到任意一条即跳过 LLM 审查，直接请求用户批准。
_DANGEROUS_BASH_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|[;&|(]\s*)rm\b"), "rm（删除文件/目录）"),
    (re.compile(r"(?:^|[;&|(]\s*)rmdir\b"), "rmdir（删除目录）"),
    (re.compile(r"(?:^|[;&|(]\s*)dd\b"), "dd（磁盘写入）"),
    (re.compile(r"(?:^|[;&|(]\s*)mkfs\b"), "mkfs（磁盘格式化）"),
    (re.compile(r"(?:^|[;&|(]\s*)shred\b"), "shred（安全删除）"),
    (re.compile(r"(?:^|[;&|(]\s*)truncate\b"), "truncate（截断/清空文件）"),
    (re.compile(r"curl\b.+[|]\s*(?:bash|sh|zsh)\b"), "curl | bash（远程代码执行）"),
    (re.compile(r"wget\b.+[|]\s*(?:bash|sh|zsh)\b"), "wget | bash（远程代码执行）"),
]


def _normalize_path_inputs(inputs: dict[str, Any]) -> None:
    """将 inputs 中的路径参数就地解析为绝对路径。

    统一处理 file_path 和 path 参数，确保所有工具收到的是绝对路径，
    防止工具内部用相对路径时因进程 CWD 不同产生不一致行为。
    """
    for key in ("file_path", "path"):
        val = inputs.get(key)
        if val is not None:
            inputs[key] = str(resolve_path(str(val)))


def _match_dangerous_bash(command: str) -> str | None:
    """若命令匹配任意高危模式，返回对应描述；否则返回 None。"""
    for pattern, description in _DANGEROUS_BASH_CHECKS:
        if pattern.search(command):
            return description
    return None


_REASON_SCHEMA: dict[str, str] = {
    "type": "string",
    "description": (
        "Explain why you need to call this tool and confirm it aligns with the current task goal."
    ),
}


class PolicyGate:
    """Permission-enforcing proxy around CapabilityRegistry.

    All agents access tools through this gate. CapabilityRegistry remains
    unaware of permission logic and can be tested independently.

    审批流顺序
    ----------
    1. Workspace 边界检查（所有 tier）：含 file_path/path 参数且路径在 workspace 外
       → 直接请求用户审批。
    2. LOW tier：直接执行。
    3. MODEL_DECIDES tier：
       a. Bash 静态高危模式匹配 → 直接请求用户审批（不走 LLM 审查）。
       b. LLM PermissionReviewer 审查：
          - escalate → 请求用户审批。
          - proceed  → 直接执行。
    4. HIGH_RISK tier：始终请求用户审批。
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        reviewer: PermissionReviewer,
        approval_manager: ApprovalManagerProtocol,
    ) -> None:
        self._registry = registry
        self._reviewer = reviewer
        self._approval_manager = approval_manager

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_tool_specs(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        """Delegate to registry for native + MCP tool specs (excluding skills)."""
        return self._registry.get_tool_specs(allowed)

    def get_skill_specs(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        """Delegate to registry for skill specs."""
        return self._registry.get_skill_specs(allowed)

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return tool specs in Anthropic API format.

        For MODEL_DECIDES tools (including unrecognised MCP tools), inject
        a required `reason` field so the LLM must state its intent.
        """
        specs: list[dict[str, Any]] = []
        for spec_dict in self._registry.get_all_tool_specs():
            tool_name = spec_dict["name"]
            native = get_tool(tool_name)
            tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

            if tier == PermissionTier.MODEL_DECIDES:
                spec_dict = copy.deepcopy(spec_dict)
                schema = spec_dict.setdefault("input_schema", {})
                props = schema.setdefault("properties", {})
                required: list[str] = schema.setdefault("required", [])
                props["reason"] = _REASON_SCHEMA
                if "reason" not in required:
                    required.append("reason")

            specs.append(spec_dict)
        return specs

    async def call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """Execute a tool after enforcing its permission tier."""
        native = get_tool(tool_name)
        tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

        token = _current_tool_ctx.set(context)
        try:
            # Stage 1: 路径规范化（所有 tier 共用）
            # 将 file_path/path 参数统一解析为绝对路径，工具无需自行处理相对路径。
            _normalize_path_inputs(inputs)

            # Stage 2: workspace 边界检查（所有 tier 共用）
            boundary_result = await self._check_workspace_boundary(tool_name, inputs, context)
            if boundary_result is not None:
                return boundary_result

            # Stage 3: tier 分派
            if tier == PermissionTier.LOW:
                return await self._registry.call(tool_name, **inputs)

            if tier == PermissionTier.MODEL_DECIDES:
                return await self._handle_model_decides(tool_name, inputs, context)

            # HIGH_RISK：始终请求用户审批
            return await self._request_approval_and_call(
                tool_name=tool_name,
                inputs=inputs,
                context=context,
                reason=f"高危工具 '{tool_name}' 需要用户明确授权。",
                denied_error="用户拒绝了此操作。",
            )
        finally:
            _current_tool_ctx.reset(token)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _check_workspace_boundary(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult | None:
        """若工具含 file_path/path 参数且路径在 workspace 外，请求用户审批。

        返回 ToolResult 表示流程已在此终止；返回 None 表示检查通过，继续后续流程。
        注意：会从 inputs 中移除 `reason` 字段，避免混入实际工具参数。
        """
        path_param = inputs.get("file_path") or inputs.get("path")
        if path_param is None:
            return None

        resolved = Path(str(path_param))
        if resolved.is_relative_to(settings.workspace_dir.resolve()):
            return None

        inputs.pop("reason", None)
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=inputs,
            reason=f"操作路径 '{resolved}' 在 workspace 外，需要用户确认。",
            session_id=context.session_id or "",
            agent_type=context.agent_type,
        )
        if granted:
            return await self._registry.call(tool_name, **inputs)
        return ToolResult(ok=False, error="用户拒绝了 workspace 外的文件操作。")

    async def _handle_model_decides(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """MODEL_DECIDES 审批流：静态检查优先，通过后再交 LLM 审查。"""
        reason = inputs.pop("reason", "")

        # Step 1: 静态高危模式匹配（仅 Bash）
        if tool_name == "Bash":
            cmd = inputs.get("command", "")
            matched = _match_dangerous_bash(cmd)
            if matched:
                return await self._request_approval_and_call(
                    tool_name=tool_name,
                    inputs=inputs,
                    context=context,
                    reason=f"检测到高危 Bash 命令（{matched}），需要用户确认。",
                    denied_error="用户拒绝了高危命令的执行。",
                )

        # Step 2: LLM PermissionReviewer 审查
        decision = await self._reviewer.review(
            tool_name=tool_name,
            tool_input=inputs,
            reason=reason,
            task_goal=context.task_goal,
        )
        if decision.decision == "proceed":
            return await self._registry.call(tool_name, **inputs)

        return await self._request_approval_and_call(
            tool_name=tool_name,
            inputs=inputs,
            context=context,
            reason=decision.explanation,
            denied_error="用户拒绝了此操作。",
        )

    async def _request_approval_and_call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
        reason: str,
        denied_error: str,
    ) -> ToolResult:
        """请求用户审批，批准则执行工具，拒绝则返回错误。"""
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=inputs,
            reason=reason,
            session_id=context.session_id or "",
            agent_type=context.agent_type,
        )
        if granted:
            return await self._registry.call(tool_name, **inputs)
        return ToolResult(ok=False, error=denied_error)

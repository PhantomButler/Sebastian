# sebastian/permissions/gate.py
from __future__ import annotations

import copy
import logging
import uuid
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.protocols import ApprovalManagerProtocol
from sebastian.core.tool import get_tool
from sebastian.core.types import ToolResult
from sebastian.permissions.reviewer import PermissionReviewer
from sebastian.permissions.types import PermissionTier, ToolCallContext

logger = logging.getLogger(__name__)

_REASON_SCHEMA: dict[str, str] = {
    "type": "string",
    "description": (
        "Explain why you need to call this tool and confirm it aligns "
        "with the current task goal."
    ),
}


class PolicyGate:
    """Permission-enforcing proxy around CapabilityRegistry.

    All agents access tools through this gate. CapabilityRegistry remains
    unaware of permission logic and can be tested independently.
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

        if tier == PermissionTier.LOW:
            return await self._registry.call(tool_name, **inputs)

        if tier == PermissionTier.MODEL_DECIDES:
            reason = inputs.pop("reason", "")
            decision = await self._reviewer.review(
                tool_name=tool_name,
                tool_input=inputs,
                reason=reason,
                task_goal=context.task_goal,
            )
            if decision.decision == "proceed":
                return await self._registry.call(tool_name, **inputs)
            granted = await self._approval_manager.request_approval(
                approval_id=uuid.uuid4().hex,
                task_id=context.task_id or "",
                tool_name=tool_name,
                tool_input=inputs,
                reason=decision.explanation,
                session_id=context.session_id or "",
            )
            if granted:
                return await self._registry.call(tool_name, **inputs)
            return ToolResult(ok=False, error="User denied approval for this tool call.")

        # HIGH_RISK — always request approval regardless of model intent
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=inputs,
            reason=f"High-risk tool '{tool_name}' requires explicit user approval.",
            session_id=context.session_id or "",
        )
        if granted:
            return await self._registry.call(tool_name, **inputs)
        return ToolResult(ok=False, error="User denied approval for this tool call.")

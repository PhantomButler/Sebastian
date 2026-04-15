# tests/unit/test_policy_gate.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import ToolResult
from sebastian.permissions.gate import PolicyGate
from sebastian.permissions.types import PermissionTier, ReviewDecision, ToolCallContext


def _make_context(task_goal: str = "test goal") -> ToolCallContext:
    return ToolCallContext(task_goal=task_goal, session_id="s1", task_id="t1")


@pytest.mark.asyncio
async def test_low_tier_bypasses_reviewer_and_approval(tmp_path) -> None:
    """LOW tier workspace 内路径 → 直接执行，不走 reviewer 和 approval_manager。"""
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "notes.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="result"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": str(inside_path)}, _make_context())

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()
    registry.call.assert_awaited_once_with("file_read", path=str(inside_path))


@pytest.mark.asyncio
async def test_model_decides_proceed_no_approval() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(return_value=ReviewDecision(decision="proceed", explanation=""))
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "shell",
            {"command": "cat /tmp/a.txt", "reason": "Reading temp file for task"},
            _make_context("Read temp file"),
        )

    assert result.ok
    reviewer.review.assert_awaited_once()
    approval_manager.request_approval.assert_not_called()
    # reason must not reach registry
    registry.call.assert_awaited_once_with("shell", command="cat /tmp/a.txt")


@pytest.mark.asyncio
async def test_model_decides_escalate_user_grants() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="deleted"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=ReviewDecision(decision="escalate", explanation="将删除文件，请确认。")
    )
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "shell",
            {"command": "rm /tmp/old.log", "reason": "Remove stale log"},
            _make_context("Clean up logs"),
        )

    assert result.ok
    approval_manager.request_approval.assert_awaited_once()
    call_kwargs = approval_manager.request_approval.call_args.kwargs
    assert call_kwargs["reason"] == "将删除文件，请确认。"


@pytest.mark.asyncio
async def test_model_decides_escalate_user_denies() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="done"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=ReviewDecision(decision="escalate", explanation="Risky.")
    )
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=False)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "shell",
            {"command": "rm /etc/hosts", "reason": "cleanup"},
            _make_context(),
        )

    assert not result.ok
    assert "拒绝" in (result.error or "")
    registry.call.assert_not_called()


@pytest.mark.asyncio
async def test_high_risk_always_requests_approval() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="done"))
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.HIGH_RISK
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("delete_file", {"path": "/data/db"}, _make_context())

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_high_risk_denied_returns_error() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=False)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.HIGH_RISK
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("delete_file", {"path": "/data"}, _make_context())

    assert not result.ok
    registry.call.assert_not_called()


def test_get_all_tool_specs_injects_reason_for_model_decides() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_callable_specs.return_value = [
        {
            "name": "shell",
            "description": "Run shell command",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "file_read",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]

    gate = PolicyGate(registry=registry, reviewer=MagicMock(), approval_manager=MagicMock())

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:

        def _side_effect(name: str):
            spec = MagicMock()
            spec.permission_tier = (
                PermissionTier.MODEL_DECIDES if name == "shell" else PermissionTier.LOW
            )
            return (spec, MagicMock())

        mock_get_tool.side_effect = _side_effect
        specs = gate.get_all_tool_specs()

    shell_spec = next(s for s in specs if s["name"] == "shell")
    file_spec = next(s for s in specs if s["name"] == "file_read")

    assert "reason" in shell_spec["input_schema"]["properties"]
    assert "reason" in shell_spec["input_schema"]["required"]
    assert "reason" not in file_spec["input_schema"]["properties"]


@pytest.mark.asyncio
async def test_low_tier_sets_and_resets_tool_context() -> None:
    """ContextVar is set during tool execution and reset to None after."""
    from sebastian.core.tool_context import _current_tool_ctx
    from sebastian.permissions.gate import PolicyGate

    captured: list = []

    async def _capturing_call(tool_name: str, **kwargs):
        captured.append(_current_tool_ctx.get())
        return ToolResult(ok=True, output="ok")

    registry = MagicMock()
    registry.call = _capturing_call

    gate = PolicyGate(registry=registry, reviewer=MagicMock(), approval_manager=MagicMock())
    ctx = _make_context("verify context injection")

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        await gate.call("file_read", {}, ctx)

    # ContextVar was set to ctx during the call
    assert captured[0] is ctx
    # ContextVar is reset to None after the call
    assert _current_tool_ctx.get() is None


def test_get_all_tool_specs_unknown_tool_defaults_to_model_decides() -> None:
    """MCP tools not in native registry default to MODEL_DECIDES."""
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_callable_specs.return_value = [
        {
            "name": "mcp_tool",
            "description": "An MCP tool",
            "input_schema": {
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
        }
    ]

    gate = PolicyGate(registry=registry, reviewer=MagicMock(), approval_manager=MagicMock())

    with patch("sebastian.permissions.gate.get_tool", return_value=None):
        specs = gate.get_all_tool_specs()

    mcp_spec = specs[0]
    assert "reason" in mcp_spec["input_schema"]["properties"]
    assert "reason" in mcp_spec["input_schema"]["required"]


@pytest.mark.asyncio
async def test_model_decides_file_path_outside_workspace_skips_reviewer(tmp_path) -> None:
    """file_path 在 workspace 外 → 跳过 reviewer，直接走用户审批。"""
    from pathlib import Path
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    outside_path = "/tmp/evil_output.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="written"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=Path(outside_path)),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Write",
            {"file_path": outside_path, "content": "data", "reason": "write outside"},
            _make_context("write a file"),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_awaited_once()
    # reason 不应透传给 registry
    call_kwargs = registry.call.call_args
    assert "reason" not in call_kwargs.kwargs


@pytest.mark.asyncio
async def test_model_decides_file_path_outside_workspace_user_denies(tmp_path) -> None:
    """workspace 外路径，用户拒绝审批 → 返回错误，不执行。"""
    from pathlib import Path
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock()
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=False)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=Path("/tmp/evil.txt")),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Write",
            {"file_path": "/tmp/evil.txt", "content": "x", "reason": "bad"},
            _make_context("write"),
        )

    assert not result.ok
    assert "拒绝" in (result.error or "")
    registry.call.assert_not_called()


@pytest.mark.asyncio
async def test_model_decides_file_path_inside_workspace_uses_reviewer(tmp_path) -> None:
    """file_path 在 workspace 内 → 走原有 reviewer 流程，不触发 workspace 拦截。"""
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "output.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(return_value=ReviewDecision(decision="proceed", explanation=""))
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Write",
            {"file_path": "output.txt", "content": "data", "reason": "write in workspace"},
            _make_context("write a file"),
        )

    assert result.ok
    reviewer.review.assert_awaited_once()
    approval_manager.request_approval.assert_not_called()


@pytest.mark.asyncio
async def test_low_tier_file_path_outside_workspace_requests_approval(tmp_path) -> None:
    """LOW tier（Read）含 file_path 且路径在 workspace 外 → 触发用户审批。"""
    from pathlib import Path
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    outside_path = "/etc/hosts"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="content"))
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=Path(outside_path)),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Read",
            {"file_path": outside_path},
            _make_context("read system file"),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_low_tier_path_param_outside_workspace_requests_approval(tmp_path) -> None:
    """LOW tier（Glob/Grep）含 path 参数且路径在 workspace 外 → 触发用户审批。"""
    from pathlib import Path
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    outside_path = "/tmp/search_root"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output={"files": []}))
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=Path(outside_path)),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Glob",
            {"pattern": "**/*", "path": outside_path},
            _make_context("list files"),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_low_tier_file_path_inside_workspace_no_approval(tmp_path) -> None:
    """LOW tier（Read）含 file_path 且路径在 workspace 内 → 直接执行，无审批。"""
    from unittest.mock import patch

    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "notes.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="content"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Read",
            {"file_path": "notes.txt"},
            _make_context("read file"),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()


def _make_gate_with_specs(
    native_specs: list[dict],
) -> PolicyGate:
    """构造一个 PolicyGate，注入 registry 返回指定 native_specs。"""
    registry = MagicMock()
    registry.get_callable_specs = MagicMock(
        side_effect=lambda allowed_tools, allowed_skills: [
            spec for spec in native_specs if allowed_tools is None or spec["name"] in allowed_tools
        ]
    )
    reviewer = MagicMock()
    approval_manager = MagicMock()
    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)
    return gate


def test_get_callable_specs_filters_by_allowed_tools() -> None:
    """给定 allowed_tools={'Read'}，只返回 Read 的 spec。"""
    specs = [
        {"name": "Read", "description": "read", "input_schema": {"properties": {}}},
        {"name": "Bash", "description": "bash", "input_schema": {"properties": {}}},
    ]
    gate = _make_gate_with_specs(specs)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = gate.get_callable_specs(allowed_tools={"Read"}, allowed_skills=None)

    names = [s["name"] for s in result]
    assert names == ["Read"]


def test_get_callable_specs_injects_reason_for_model_decides() -> None:
    """MODEL_DECIDES tier 的工具 spec 应被注入 required 的 reason 字段。"""
    specs = [
        {
            "name": "Bash",
            "description": "bash",
            "input_schema": {
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    ]
    gate = _make_gate_with_specs(specs)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = gate.get_callable_specs(allowed_tools=None, allowed_skills=None)

    assert len(result) == 1
    schema = result[0]["input_schema"]
    assert "reason" in schema["properties"]
    assert "reason" in schema["required"]


def test_get_all_tool_specs_still_works_as_shim() -> None:
    """get_all_tool_specs() 调用 get_callable_specs(None, None)，行为保持不变。"""
    specs = [
        {"name": "Read", "description": "read", "input_schema": {"properties": {}}},
    ]
    gate = _make_gate_with_specs(specs)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = gate.get_all_tool_specs()

    assert [s["name"] for s in result] == ["Read"]


def test_get_callable_specs_forwards_allowed_skills() -> None:
    """PolicyGate.get_callable_specs 应把 allowed_skills 如实转发给 registry。"""
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_callable_specs = MagicMock(return_value=[])
    reviewer = MagicMock()
    approval_manager = MagicMock()
    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    result = gate.get_callable_specs(
        allowed_tools={"Read"},
        allowed_skills={"code-review"},
    )

    assert result == []
    registry.get_callable_specs.assert_called_once_with({"Read"}, {"code-review"})


@pytest.mark.asyncio
async def test_call_rejects_tool_outside_allowed_tools() -> None:
    """context.allowed_tools 限制外的工具应被 Stage 0 拒绝，不到 registry。"""
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock()
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    context = ToolCallContext(
        task_goal="test",
        session_id="s1",
        task_id="t1",
        agent_type="forge",
        depth=2,
        allowed_tools=frozenset({"Read"}),
    )

    result = await gate.call("Bash", {"command": "ls"}, context)

    assert result.ok is False
    assert "'Bash'" in (result.error or "")
    assert "'forge'" in (result.error or "")
    registry.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_allows_tool_inside_allowed_tools(tmp_path) -> None:
    """白名单内的工具应通过 Stage 0，正常走后续流程。"""
    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "notes.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    context = ToolCallContext(
        task_goal="test",
        session_id="s1",
        task_id="t1",
        agent_type="forge",
        depth=2,
        allowed_tools=frozenset({"file_read"}),
    )

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": str(inside_path)}, context)

    assert result.ok
    registry.call.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_none_allowed_tools_means_unrestricted(tmp_path) -> None:
    """context.allowed_tools=None 表示不限制，任意合法工具可调用（回归）。"""
    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "notes.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    context = ToolCallContext(
        task_goal="test",
        session_id="s1",
        task_id="t1",
        agent_type="forge",
        depth=2,
        allowed_tools=None,
    )

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": str(inside_path)}, context)

    assert result.ok

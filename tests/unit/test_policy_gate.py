# tests/unit/test_policy_gate.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier, ReviewDecision, ToolCallContext


def _make_context(task_goal: str = "test goal") -> ToolCallContext:
    return ToolCallContext(task_goal=task_goal, session_id="s1", task_id="t1")


@pytest.mark.asyncio
async def test_low_tier_bypasses_reviewer_and_approval() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="result"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": "/tmp/f.txt"}, _make_context())

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()
    registry.call.assert_awaited_once_with("file_read", path="/tmp/f.txt")


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
    assert "denied" in (result.error or "").lower()
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
    registry.get_all_tool_specs.return_value = [
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


def test_get_all_tool_specs_unknown_tool_defaults_to_model_decides() -> None:
    """MCP tools not in native registry default to MODEL_DECIDES."""
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_all_tool_specs.return_value = [
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

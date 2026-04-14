from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier, ToolCallContext


@pytest.mark.asyncio
async def test_policy_gate_low_tier_end_to_end(tmp_path) -> None:
    """LOW tier tool executes without touching reviewer or approval."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.permissions.gate import PolicyGate

    registry = CapabilityRegistry()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output={"content": "hello"}))

    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    target_file = tmp_path / "test.txt"

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        spec = MagicMock()
        spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (spec, MagicMock())
        mock_settings.workspace_dir = tmp_path

        result = await gate.call(
            "file_read",
            {"path": str(target_file)},
            ToolCallContext(task_goal="Read file", session_id="s1", task_id=None),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()


@pytest.mark.asyncio
async def test_conversation_manager_approval_flow() -> None:
    """ConversationManager suspends and resumes on resolve."""
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.protocol.events.bus import EventBus

    bus = EventBus()
    manager = ConversationManager(event_bus=bus)

    approval_task = asyncio.create_task(
        manager.request_approval(
            approval_id="test_001",
            task_id="t1",
            tool_name="shell",
            tool_input={"command": "rm /tmp/x"},
            reason="Cleanup temp file",
        )
    )

    # 让协程挂起
    await asyncio.sleep(0)
    assert not approval_task.done()

    # 用户 grant
    await manager.resolve_approval("test_001", granted=True)
    result = await approval_task
    assert result is True


@pytest.mark.asyncio
async def test_conversation_manager_deny_flow() -> None:
    """ConversationManager returns False when denied."""
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.protocol.events.bus import EventBus

    bus = EventBus()
    manager = ConversationManager(event_bus=bus)

    approval_task = asyncio.create_task(
        manager.request_approval(
            approval_id="test_002",
            task_id="t1",
            tool_name="delete_file",
            tool_input={"path": "/data"},
            reason="High-risk tool requires approval.",
        )
    )

    await asyncio.sleep(0)
    await manager.resolve_approval("test_002", granted=False)
    result = await approval_task
    assert result is False


@pytest.mark.asyncio
async def test_policy_gate_model_decides_full_escalate_grant_flow() -> None:
    """Full MODEL_DECIDES flow: reviewer escalates → approval granted → tool runs."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.permissions.gate import PolicyGate
    from sebastian.permissions.reviewer import PermissionReviewer
    from sebastian.protocol.events.bus import EventBus

    registry = CapabilityRegistry()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output={"stdout": "done"}))

    from sebastian.core.stream_events import TextDelta

    async def _stream_escalate(*args, **kwargs):
        yield TextDelta(
            block_id="0", delta='{"decision": "escalate", "explanation": "删除操作需要确认"}'
        )

    mock_provider = MagicMock()
    mock_provider.stream = _stream_escalate
    mock_registry = MagicMock()
    mock_registry.get_default_with_model = AsyncMock(
        return_value=(mock_provider, "claude-haiku-4-5-20251001")
    )

    reviewer = PermissionReviewer(llm_registry=mock_registry)
    bus = EventBus()
    conversation = ConversationManager(event_bus=bus)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=conversation)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        spec = MagicMock()
        spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (spec, MagicMock())

        call_task = asyncio.create_task(
            gate.call(
                "shell",
                {"command": "rm /tmp/old.log", "reason": "Remove stale log file"},
                ToolCallContext(task_goal="Clean up logs", session_id="s1", task_id="t1"),
            )
        )

        # 等待 approval 请求产生
        await asyncio.sleep(0)
        # 找出 pending 的 approval_id
        assert len(conversation._pending) == 1
        approval_id = next(iter(conversation._pending))

        # 用户批准
        await conversation.resolve_approval(approval_id, granted=True)
        result = await call_task

    assert result.ok
    registry.call.assert_awaited_once_with("shell", command="rm /tmp/old.log")

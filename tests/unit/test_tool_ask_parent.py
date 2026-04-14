from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.tool_context import _current_tool_ctx
from sebastian.core.types import SessionStatus
from sebastian.permissions.types import ToolCallContext
from sebastian.protocol.events.types import EventType


def _make_mock_state(session_status=SessionStatus.ACTIVE):
    state = MagicMock()
    state.index_store = AsyncMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()

    mock_session = MagicMock()
    mock_session.status = session_status
    mock_session.goal = "重构 auth"
    mock_session.parent_session_id = "seb-123"
    mock_session.agent_type = "code"
    state.session_store.get_session = AsyncMock(return_value=mock_session)

    return state, mock_session


@pytest.mark.asyncio
async def test_ask_parent_sets_waiting_status():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    state, mock_session = _make_mock_state()
    ctx = ToolCallContext(
        task_goal="重构",
        session_id="child-456",
        task_id=None,
        agent_type="code",
        depth=2,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.ask_parent._get_state", return_value=state):
            result = await ask_parent(question="config.yaml 要覆盖吗？")
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is True
    assert mock_session.status == SessionStatus.WAITING
    state.session_store.update_session.assert_awaited_once()
    state.index_store.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_ask_parent_publishes_session_waiting_event():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    state, mock_session = _make_mock_state()
    ctx = ToolCallContext(
        task_goal="重构",
        session_id="child-456",
        task_id=None,
        agent_type="code",
        depth=2,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.ask_parent._get_state", return_value=state):
            await ask_parent(question="config.yaml 要覆盖吗？")
    finally:
        _current_tool_ctx.reset(token)

    state.event_bus.publish.assert_awaited_once()
    published = state.event_bus.publish.call_args[0][0]
    assert published.type == EventType.SESSION_WAITING
    assert published.data["question"] == "config.yaml 要覆盖吗？"
    assert published.data["parent_session_id"] == "seb-123"
    assert published.data["session_id"] == "child-456"


@pytest.mark.asyncio
async def test_ask_parent_blocked_for_sebastian():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    ctx = ToolCallContext(
        task_goal="总任务",
        session_id="seb-123",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        result = await ask_parent(question="这样做对吗？")
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is False
    assert "上级" in result.error


@pytest.mark.asyncio
async def test_ask_parent_output_instructs_to_wait():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    state, _ = _make_mock_state()
    ctx = ToolCallContext(
        task_goal="重构",
        session_id="child-456",
        task_id=None,
        agent_type="code",
        depth=2,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.ask_parent._get_state", return_value=state):
            result = await ask_parent(question="继续吗？")
    finally:
        _current_tool_ctx.reset(token)

    assert "等待" in result.output

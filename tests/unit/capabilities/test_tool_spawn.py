from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.tool_context import _current_tool_ctx
from sebastian.permissions.types import ToolCallContext


@pytest.mark.asyncio
async def test_spawn_sub_agent_success():
    from sebastian.capabilities.tools.spawn_sub_agent import spawn_sub_agent

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_agent.name = "code"
    mock_state.agent_instances = {"code": mock_agent}
    mock_state.agent_registry = {"code": MagicMock(max_children=5)}
    mock_state.session_store = AsyncMock()
    mock_state.session_store.list_active_children = AsyncMock(return_value=[])
    mock_state.event_bus = MagicMock()

    ctx = ToolCallContext(
        task_goal="complex task",
        session_id="parent_session",
        task_id=None,
        agent_type="code",
        depth=2,
    )

    token = _current_tool_ctx.set(ctx)
    try:
        with patch(
            "sebastian.capabilities.tools.spawn_sub_agent._get_state", return_value=mock_state
        ):
            result = await spawn_sub_agent(goal="write unit tests", context="")
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is True
    assert "组员" in result.output
    mock_state.session_store.create_session.assert_awaited_once()
    created_session = mock_state.session_store.create_session.call_args[0][0]
    assert created_session.depth == 3
    assert created_session.parent_session_id == "parent_session"


@pytest.mark.asyncio
async def test_spawn_sub_agent_over_limit():
    from sebastian.capabilities.tools.spawn_sub_agent import spawn_sub_agent

    mock_state = MagicMock()
    mock_state.agent_registry = {"code": MagicMock(max_children=2)}
    mock_state.session_store = AsyncMock()
    mock_state.session_store.list_active_children = AsyncMock(
        return_value=[{"id": "c1"}, {"id": "c2"}]
    )

    ctx = ToolCallContext(
        task_goal="task",
        session_id="parent",
        task_id=None,
        agent_type="code",
        depth=2,
    )

    token = _current_tool_ctx.set(ctx)
    try:
        with patch(
            "sebastian.capabilities.tools.spawn_sub_agent._get_state", return_value=mock_state
        ):
            result = await spawn_sub_agent(goal="another task")
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is False
    assert "上限" in result.error


@pytest.mark.asyncio
async def test_spawn_sub_agent_no_context():
    """Without ContextVar set, tool returns error."""
    from sebastian.capabilities.tools.spawn_sub_agent import spawn_sub_agent

    result = await spawn_sub_agent(goal="some task")

    assert result.ok is False
    assert "上下文" in result.error

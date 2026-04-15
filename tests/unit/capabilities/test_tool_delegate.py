import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.permissions.types import ToolCallContext

_FAKE_CTX = ToolCallContext(
    task_goal="orchestrator turn",
    session_id="S1",
    task_id=None,
    agent_type="sebastian",
    depth=1,
)


@pytest.mark.asyncio
async def test_delegate_to_agent_creates_session_and_dispatches():
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_agent.name = "forge"
    mock_state.agent_instances = {"forge": mock_agent}
    mock_state.agent_registry = {
        "forge": MagicMock(max_children=5),
    }
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.event_bus = MagicMock()

    with (
        patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state),
        patch(
            "sebastian.capabilities.tools.delegate_to_agent.get_tool_context",
            return_value=_FAKE_CTX,
        ),
    ):
        result = await delegate_to_agent(
            agent_type="forge",
            goal="write auth module",
            context="",
        )

    assert result.ok is True
    assert "Forge" in result.output
    mock_state.session_store.create_session.assert_awaited_once()
    mock_state.index_store.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_delegate_unknown_agent_type_returns_error() -> None:
    """agent_type 不在 agent_instances 时返回 ok=False。"""
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent

    mock_state = MagicMock()
    mock_state.agent_instances = {}  # 无任何 agent

    with (
        patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state),
        patch(
            "sebastian.capabilities.tools.delegate_to_agent.get_tool_context",
            return_value=_FAKE_CTX,
        ),
    ):
        result = await delegate_to_agent(
            agent_type="nonexistent",
            goal="write auth module",
            context="",
        )

    assert result.ok is False
    assert "nonexistent" in result.error


@pytest.mark.asyncio
async def test_delegate_creates_background_task() -> None:
    """成功委派时 asyncio.create_task 被调用一次。"""
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_state.agent_instances = {"forge": mock_agent}
    mock_state.agent_registry = {
        "forge": MagicMock(max_children=5),
    }
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.event_bus = MagicMock()

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.add_done_callback = MagicMock()

    with (
        patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state),
        patch(
            "sebastian.capabilities.tools.delegate_to_agent.get_tool_context",
            return_value=_FAKE_CTX,
        ),
        patch("asyncio.create_task", return_value=mock_task) as mock_create_task,
    ):
        result = await delegate_to_agent(
            agent_type="forge",
            goal="write auth module",
            context="",
        )

    assert result.ok is True
    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_delegate_sets_parent_session_id_and_depth() -> None:
    """子 Session 的 parent_session_id 必须等于 ctx.session_id，depth = ctx.depth + 1。"""
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_state.agent_instances = {"forge": mock_agent}
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.event_bus = MagicMock()

    with (
        patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state),
        patch(
            "sebastian.capabilities.tools.delegate_to_agent.get_tool_context",
            return_value=_FAKE_CTX,
        ),
    ):
        result = await delegate_to_agent(
            agent_type="forge",
            goal="write auth module",
            context="",
        )

    assert result.ok is True
    created_session = mock_state.session_store.create_session.await_args.args[0]
    assert created_session.parent_session_id == "S1"
    assert created_session.depth == 2
    assert created_session.agent_type == "forge"


@pytest.mark.asyncio
async def test_delegate_without_context_returns_error() -> None:
    """get_tool_context 返回 None 时必须提前返回 ok=False 并给出行动指引。"""
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent

    with patch(
        "sebastian.capabilities.tools.delegate_to_agent.get_tool_context",
        return_value=None,
    ):
        result = await delegate_to_agent(
            agent_type="forge",
            goal="write auth module",
            context="",
        )

    assert result.ok is False
    assert "ToolCallContext" in result.error
    assert "不要重试" in result.error

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import Session, SessionStatus
from sebastian.permissions.types import ToolCallContext
from sebastian.protocol.events.types import EventType


def _make_session(
    status: SessionStatus,
    *,
    agent_type: str = "code",
    depth: int = 2,
    parent_id: str = "seb-123",
) -> Session:
    session = Session(
        agent_type=agent_type,
        title="测试会话",
        goal="处理任务",
        depth=depth,
        parent_session_id=parent_id,
    )
    session.status = status
    return session


def _make_mock_state(session: Session) -> tuple[MagicMock, AsyncMock]:
    state = MagicMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()
    state.session_store.list_sessions = AsyncMock(
        return_value=[
            {
                "id": session.id,
                "agent_type": session.agent_type,
                "status": session.status.value,
                "depth": session.depth,
                "parent_session_id": session.parent_session_id,
            }
        ]
    )
    state.session_store.get_session = AsyncMock(return_value=session)

    mock_agent = AsyncMock()
    mock_agent.cancel_session = AsyncMock(return_value=True)
    state.agent_instances = {session.agent_type: mock_agent}
    return state, mock_agent


def _sebastian_ctx() -> ToolCallContext:
    return ToolCallContext(
        task_goal="管理子代理",
        session_id="seb-123",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )


def _leader_ctx(session_id: str = "code-leader-1") -> ToolCallContext:
    return ToolCallContext(
        task_goal="管理组员",
        session_id=session_id,
        task_id=None,
        agent_type="code",
        depth=2,
    )


@pytest.mark.asyncio
async def test_stop_active_session_transitions_to_idle_and_emits_side_effects() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.ACTIVE)
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(
            agent_type="code",
            session_id=session.id,
            reason="用户改主意",
        )

    assert result.ok is True
    mock_agent.cancel_session.assert_awaited_once_with(session.id, intent="stop")
    assert session.status == SessionStatus.IDLE
    state.session_store.update_session.assert_awaited_once_with(session)
    state.session_store.append_timeline_items.assert_awaited_once_with(
        session.id,
        "code",
        [{"kind": "system_event", "role": "system", "content": "[上级暂停] reason: 用户改主意"}],
    )
    state.event_bus.publish.assert_awaited_once()
    published_event = state.event_bus.publish.await_args.args[0]
    assert published_event.type == EventType.SESSION_PAUSED
    assert published_event.data["session_id"] == session.id
    assert published_event.data["agent_type"] == "code"
    assert published_event.data["stopped_by"] == "seb-123"
    assert published_event.data["reason"] == "用户改主意"
    assert "timestamp" in published_event.data


@pytest.mark.asyncio
async def test_stop_stalled_session_transitions_to_idle() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.STALLED)
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    assert session.status == SessionStatus.IDLE
    mock_agent.cancel_session.assert_awaited_once_with(session.id, intent="stop")
    state.session_store.append_timeline_items.assert_awaited_once_with(
        session.id,
        "code",
        [{"kind": "system_event", "role": "system", "content": "[上级暂停]"}],
    )


@pytest.mark.asyncio
async def test_stop_idle_session_is_idempotent() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.IDLE)
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    assert "IDLE" in result.output
    mock_agent.cancel_session.assert_not_awaited()
    state.session_store.update_session.assert_not_awaited()
    state.session_store.append_timeline_items.assert_not_awaited()
    state.event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED],
)
async def test_stop_terminal_session_rejected(status: SessionStatus) -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(status)
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert session.id in result.error
    assert "已结束" in result.error
    assert "inspect_session" in result.error
    mock_agent.cancel_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_unknown_session_returns_error() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    state = MagicMock()
    state.session_store = AsyncMock()
    state.session_store.list_sessions = AsyncMock(return_value=[])

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id="nope")

    assert result.ok is False
    assert "nope" in result.error
    assert "check_sub_agents" in result.error


@pytest.mark.asyncio
async def test_stop_agent_type_mismatch_returns_error() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.ACTIVE, agent_type="code")
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="forge", session_id=session.id)

    assert result.ok is False
    assert "code" in result.error
    assert "forge" in result.error
    assert "check_sub_agents" in result.error
    mock_agent.cancel_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_sebastian_can_stop_depth3_session() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.ACTIVE, depth=3, parent_id="code-leader-1")
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    mock_agent.cancel_session.assert_awaited_once_with(session.id, intent="stop")


@pytest.mark.asyncio
async def test_leader_can_stop_own_depth3_worker() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    leader_session_id = "code-leader-1"
    session = _make_session(SessionStatus.ACTIVE, depth=3, parent_id=leader_session_id)
    state, mock_agent = _make_mock_state(session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_leader_ctx(leader_session_id)),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    mock_agent.cancel_session.assert_awaited_once_with(session.id, intent="stop")


@pytest.mark.asyncio
async def test_leader_cannot_stop_non_owned_or_non_depth3_session() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    other_leader_worker = _make_session(
        SessionStatus.ACTIVE,
        depth=3,
        parent_id="other-leader",
    )
    other_state, other_mock_agent = _make_mock_state(other_leader_worker)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_leader_ctx("code-leader-1")),
        patch.object(stop_mod, "_get_state", return_value=other_state),
    ):
        other_result = await stop_agent(agent_type="code", session_id=other_leader_worker.id)

    assert other_result.ok is False
    assert "无权" in other_result.error
    other_mock_agent.cancel_session.assert_not_awaited()

    depth2_session = _make_session(SessionStatus.ACTIVE, depth=2, parent_id="seb-123")
    depth2_state, depth2_mock_agent = _make_mock_state(depth2_session)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_leader_ctx("code-leader-1")),
        patch.object(stop_mod, "_get_state", return_value=depth2_state),
    ):
        depth2_result = await stop_agent(agent_type="code", session_id=depth2_session.id)

    assert depth2_result.ok is False
    assert "无权" in depth2_result.error
    depth2_mock_agent.cancel_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_depth3_worker_cannot_stop_session() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.ACTIVE, depth=3, parent_id="code-leader-1")
    state, mock_agent = _make_mock_state(session)
    worker_ctx = ToolCallContext(
        task_goal="组员执行",
        session_id="worker-1",
        task_id=None,
        agent_type="code",
        depth=3,
    )

    with (
        patch.object(stop_mod, "get_tool_context", return_value=worker_ctx),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert "无权" in result.error
    mock_agent.cancel_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_returns_error_when_cancel_session_reports_no_active_stream() -> None:
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.ACTIVE)
    state, mock_agent = _make_mock_state(session)
    mock_agent.cancel_session = AsyncMock(return_value=False)

    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
    ):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert "inspect_session" in result.error
    state.session_store.update_session.assert_not_awaited()
    state.session_store.append_timeline_items.assert_not_awaited()
    state.event_bus.publish.assert_not_awaited()

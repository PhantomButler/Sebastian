from __future__ import annotations

import asyncio
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
    state.agent_instances = {session.agent_type: AsyncMock()}
    return state, state.agent_instances[session.agent_type]


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
async def test_resume_waiting_session_appends_instruction_and_restarts() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING)
    state, _ = _make_mock_state(session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "_schedule_session", new=AsyncMock()),
    ):
        result = await resume_agent(
            agent_type="code",
            session_id=session.id,
            instruction="继续推进修复",
        )

    assert result.ok is True
    assert session.status == SessionStatus.ACTIVE
    state.session_store.append_timeline_items.assert_awaited_once_with(
        session.id,
        "code",
        [
            {"kind": "system_event", "role": "system", "content": f"Agent {session.id} resumed"},
            {"kind": "user_message", "role": "user", "content": "继续推进修复"},
        ],
    )
    state.session_store.update_session.assert_awaited_once_with(session)
    state.event_bus.publish.assert_awaited_once()
    published_event = state.event_bus.publish.await_args.args[0]
    assert published_event.type == EventType.SESSION_RESUMED
    assert published_event.data["session_id"] == session.id
    assert published_event.data["agent_type"] == "code"
    assert published_event.data["resumed_by"] == "seb-123"
    assert published_event.data["instruction"] == "继续推进修复"
    assert "timestamp" in published_event.data


@pytest.mark.asyncio
async def test_resume_waiting_session_without_instruction_writes_system_event() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING)
    state, _ = _make_mock_state(session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "_schedule_session", new=AsyncMock()),
    ):
        result = await resume_agent(agent_type="code", session_id=session.id, instruction="")

    assert result.ok is True
    state.session_store.append_timeline_items.assert_awaited_once_with(
        session.id,
        "code",
        [{"kind": "system_event", "role": "system", "content": f"Agent {session.id} resumed"}],
    )


@pytest.mark.asyncio
async def test_resume_idle_session_without_instruction_writes_system_event() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.IDLE)
    state, _ = _make_mock_state(session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "_schedule_session", new=AsyncMock()),
    ):
        result = await resume_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    assert session.status == SessionStatus.ACTIVE
    state.session_store.append_timeline_items.assert_awaited_once_with(
        session.id,
        "code",
        [{"kind": "system_event", "role": "system", "content": f"Agent {session.id} resumed"}],
    )


@pytest.mark.asyncio
async def test_resume_idle_session_with_instruction_appends_message() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.IDLE)
    state, _ = _make_mock_state(session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "_schedule_session", new=AsyncMock()),
    ):
        result = await resume_agent(
            agent_type="code",
            session_id=session.id,
            instruction="继续执行任务",
        )

    assert result.ok is True
    state.session_store.append_timeline_items.assert_awaited_once_with(
        session.id,
        "code",
        [
            {"kind": "system_event", "role": "system", "content": f"Agent {session.id} resumed"},
            {"kind": "user_message", "role": "user", "content": "继续执行任务"},
        ],
    )


@pytest.mark.asyncio
async def test_resume_requires_tool_context() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    with patch.object(resume_mod, "get_tool_context", return_value=None):
        result = await resume_agent(agent_type="code", session_id="sess-1")

    assert result.ok is False
    assert "上下文缺失" in result.error or "ToolCallContext" in result.error


@pytest.mark.asyncio
async def test_resume_rejects_agent_type_mismatch() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING, agent_type="code")
    state, _ = _make_mock_state(session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
    ):
        result = await resume_agent(agent_type="forge", session_id=session.id)

    assert result.ok is False
    assert "code" in result.error
    assert "forge" in result.error


@pytest.mark.asyncio
async def test_leader_can_resume_own_depth3_worker_only() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    own_worker = _make_session(SessionStatus.WAITING, depth=3, parent_id="code-leader-1")
    own_state, _ = _make_mock_state(own_worker)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_leader_ctx("code-leader-1")),
        patch.object(resume_mod, "_get_state", return_value=own_state),
        patch.object(resume_mod, "_schedule_session", new=AsyncMock()),
    ):
        own_result = await resume_agent(agent_type="code", session_id=own_worker.id)

    assert own_result.ok is True

    other_worker = _make_session(SessionStatus.WAITING, depth=3, parent_id="other-leader")
    other_state, _ = _make_mock_state(other_worker)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_leader_ctx("code-leader-1")),
        patch.object(resume_mod, "_get_state", return_value=other_state),
    ):
        other_result = await resume_agent(agent_type="code", session_id=other_worker.id)

    assert other_result.ok is False
    assert "无权" in other_result.error

    depth2_session = _make_session(SessionStatus.IDLE, depth=2, parent_id="seb-123")
    depth2_state, _ = _make_mock_state(depth2_session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_leader_ctx("code-leader-1")),
        patch.object(resume_mod, "_get_state", return_value=depth2_state),
    ):
        depth2_result = await resume_agent(agent_type="code", session_id=depth2_session.id)

    assert depth2_result.ok is False
    assert "无权" in depth2_result.error


@pytest.mark.asyncio
async def test_depth3_worker_cannot_resume_session() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING, depth=3, parent_id="code-leader-1")
    state, _ = _make_mock_state(session)
    worker_ctx = ToolCallContext(
        task_goal="组员执行",
        session_id="worker-1",
        task_id=None,
        agent_type="code",
        depth=3,
    )

    with (
        patch.object(resume_mod, "get_tool_context", return_value=worker_ctx),
        patch.object(resume_mod, "_get_state", return_value=state),
    ):
        result = await resume_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert "无权" in result.error


@pytest.mark.asyncio
async def test_resume_rejects_unsupported_status() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.ACTIVE)
    state, _ = _make_mock_state(session)

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
    ):
        result = await resume_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert "inspect_session" in result.error


@pytest.mark.asyncio
async def test_concurrent_resume_only_schedules_once_for_same_session() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING)
    state, _ = _make_mock_state(session)
    # Keep list_sessions stale as waiting to ensure code relies on session-level state under lock.
    state.session_store.list_sessions = AsyncMock(
        return_value=[
            {
                "id": session.id,
                "agent_type": session.agent_type,
                "status": SessionStatus.WAITING.value,
                "depth": session.depth,
                "parent_session_id": session.parent_session_id,
            }
        ]
    )
    schedule_mock = AsyncMock()

    with (
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "_schedule_session", new=schedule_mock),
    ):
        first = asyncio.create_task(resume_agent(agent_type="code", session_id=session.id))
        second = asyncio.create_task(resume_agent(agent_type="code", session_id=session.id))
        first_result, second_result = await asyncio.gather(first, second)

    assert first_result.ok is True
    assert second_result.ok is False
    assert "inspect_session" in second_result.error
    assert schedule_mock.await_count == 1


@pytest.mark.asyncio
async def test_resume_waits_until_stop_finishes_writing_pause_message() -> None:
    import sebastian.capabilities.tools.resume_agent as resume_mod
    import sebastian.capabilities.tools.stop_agent as stop_mod
    from sebastian.capabilities.tools.resume_agent import resume_agent
    from sebastian.capabilities.tools.stop_agent import stop_agent

    session = _make_session(SessionStatus.ACTIVE)
    index_entry = {
        "id": session.id,
        "agent_type": session.agent_type,
        "status": session.status.value,
        "depth": session.depth,
        "parent_session_id": session.parent_session_id,
    }

    state = MagicMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()
    state.agent_instances = {session.agent_type: AsyncMock()}
    state.session_store.list_sessions = AsyncMock(return_value=[index_entry])
    state.session_store.get_session = AsyncMock(return_value=session)

    async def _update_session(s: Session) -> None:
        index_entry["status"] = s.status.value

    pause_append_started = asyncio.Event()
    release_pause_append = asyncio.Event()

    append_calls: list[tuple[str, list[dict]]] = []

    async def _append_timeline_items(
        _session_id: str,
        _agent_type: str,
        items: list[dict],
    ) -> list[dict]:
        first_item = items[0] if items else {}
        if first_item.get("kind") == "system_event":
            pause_append_started.set()
            await release_pause_append.wait()
        append_calls.append((_agent_type, items))
        return items

    state.session_store.update_session = AsyncMock(side_effect=_update_session)
    state.session_store.append_timeline_items = AsyncMock(side_effect=_append_timeline_items)
    state.agent_instances[session.agent_type].cancel_session = AsyncMock(return_value=True)

    schedule_mock = AsyncMock()
    with (
        patch.object(stop_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(stop_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "get_tool_context", return_value=_sebastian_ctx()),
        patch.object(resume_mod, "_get_state", return_value=state),
        patch.object(resume_mod, "_schedule_session", new=schedule_mock),
    ):
        stop_task = asyncio.create_task(
            stop_agent(agent_type=session.agent_type, session_id=session.id, reason="等确认")
        )
        await pause_append_started.wait()

        resume_task = asyncio.create_task(
            resume_agent(
                agent_type=session.agent_type,
                session_id=session.id,
                instruction="继续执行",
            )
        )
        await asyncio.sleep(0)
        assert resume_task.done() is False

        release_pause_append.set()
        stop_result, resume_result = await asyncio.gather(stop_task, resume_task)

    assert stop_result.ok is True
    assert resume_result.ok is True
    assert schedule_mock.await_count == 1
    assert len(append_calls) == 2
    first_items = append_calls[0][1]
    second_items = append_calls[1][1]
    # stop_agent writes the pause system_event first
    assert first_items[0]["kind"] == "system_event"
    # resume_agent always writes a system_event, then the user_message instruction
    assert second_items[0]["kind"] == "system_event"
    assert second_items[0]["content"] == f"Agent {session.id} resumed"
    assert second_items[1]["kind"] == "user_message"
    assert second_items[1]["content"] == "继续执行"

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sebastian.core.session_runner import run_agent_session
from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import EventType


def _make_session(**kwargs) -> Session:
    defaults = dict(
        agent_type="code",
        title="test",
        goal="目标任务",
        depth=2,
        parent_session_id="seb-session-1",
    )
    defaults.update(kwargs)
    return Session(**defaults)


@pytest.mark.asyncio
async def test_completed_event_carries_parent_session_id_and_goal():
    session = _make_session()
    agent = AsyncMock()
    agent.run_streaming = AsyncMock(return_value="done")
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(agent, session, "目标任务", session_store, index_store, event_bus)

    event_bus.publish.assert_called_once()
    published = event_bus.publish.call_args[0][0]
    assert published.type == EventType.SESSION_COMPLETED
    assert published.data["parent_session_id"] == "seb-session-1"
    assert published.data["goal"] == "目标任务"


@pytest.mark.asyncio
async def test_failed_event_carries_parent_session_id():
    session = _make_session()
    agent = AsyncMock()
    agent.run_streaming = AsyncMock(side_effect=RuntimeError("crash"))
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(agent, session, "目标任务", session_store, index_store, event_bus)

    published = event_bus.publish.call_args[0][0]
    assert published.type == EventType.SESSION_FAILED
    assert published.data["parent_session_id"] == "seb-session-1"


@pytest.mark.asyncio
async def test_waiting_status_not_overwritten_by_completed():
    """ask_parent 将 session 状态设为 WAITING 后，run_agent_session 不应覆盖为 COMPLETED。"""
    session = _make_session()
    agent = AsyncMock()

    async def _set_waiting(*_args, **_kwargs) -> str:
        session.status = SessionStatus.WAITING
        return "waiting"

    agent.run_streaming = AsyncMock(side_effect=_set_waiting)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(agent, session, "目标任务", session_store, index_store, event_bus)

    assert session.status == SessionStatus.WAITING
    # WAITING 状态不发布任何事件（ask_parent 工具自己发 SESSION_WAITING）
    event_bus.publish.assert_not_called()

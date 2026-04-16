from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.session_runner import run_agent_session
from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import EventType


@pytest.mark.asyncio
async def test_run_agent_session_success():
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value="done")
    session = Session(id="s1", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="write tests",
        session_store=session_store,
        index_store=index_store,
        event_bus=event_bus,
    )

    agent.run_streaming.assert_awaited_once_with("write tests", "s1")
    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.COMPLETED
    index_store.upsert.assert_awaited_once()
    event_bus.publish.assert_awaited_once()
    published_event = event_bus.publish.call_args[0][0]
    assert published_event.type == EventType.SESSION_COMPLETED


@pytest.mark.asyncio
async def test_run_agent_session_cancelled():
    """CancelledError 应将 session 状态设为 CANCELLED，并在持久化后重新抛出。"""
    import asyncio

    agent = MagicMock()
    agent.run_streaming = AsyncMock(side_effect=asyncio.CancelledError())
    session = Session(id="s4", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await run_agent_session(
            agent=agent,
            session=session,
            goal="cancellable task",
            session_store=session_store,
            index_store=index_store,
            event_bus=event_bus,
        )

    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.CANCELLED
    index_store.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_agent_session_stop_intent_yields_to_stop_agent_without_persisting():
    """CancelledError + stop intent：不再由 run_agent_session 写 IDLE/落库/发事件，
    全部交由 stop_agent 工具负责，避免状态双写。"""
    import asyncio

    agent = MagicMock()
    agent.run_streaming = AsyncMock(side_effect=asyncio.CancelledError())
    agent.consume_cancel_intent = MagicMock(return_value="stop")
    session = Session(id="s5", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="pausable task",
        session_store=session_store,
        index_store=index_store,
        event_bus=event_bus,
    )

    # stop 分支：session_runner 不触碰存储，也不发事件
    session_store.update_session.assert_not_awaited()
    index_store.upsert.assert_not_awaited()
    event_bus.publish.assert_not_called()
    # status 不被 session_runner 改写（保留 stop_agent 发起时的状态）
    assert session.status != SessionStatus.IDLE
    assert session.status != SessionStatus.CANCELLED


@pytest.mark.asyncio
async def test_run_agent_session_failure():
    agent = MagicMock()
    agent.run_streaming = AsyncMock(side_effect=RuntimeError("boom"))
    session = Session(id="s2", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="bad task",
        session_store=session_store,
        index_store=index_store,
        event_bus=event_bus,
    )

    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.FAILED
    index_store.upsert.assert_awaited_once()
    event_bus.publish.assert_awaited_once()
    published_event = event_bus.publish.call_args[0][0]
    assert published_event.type == EventType.SESSION_FAILED


@pytest.mark.asyncio
async def test_run_agent_session_no_event_bus():
    """event_bus=None 路径：不抛异常，session 状态正常更新。"""
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value="done")
    session = Session(id="s3", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="no bus task",
        session_store=session_store,
        index_store=index_store,
        event_bus=None,
    )

    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.COMPLETED
    index_store.upsert.assert_awaited_once()

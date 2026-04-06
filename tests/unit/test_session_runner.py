import pytest
from unittest.mock import AsyncMock, MagicMock
from sebastian.core.types import Session, SessionStatus
from sebastian.core.session_runner import run_agent_session


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

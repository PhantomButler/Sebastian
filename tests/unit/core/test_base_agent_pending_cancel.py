from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sebastian.core.base_agent import BaseAgent
from sebastian.core.types import Session
from sebastian.store.session_store import SessionStore


@pytest.fixture
async def agent(tmp_path: Path):
    class DummyAgent(BaseAgent):
        name = "sebastian"

    session_store = SessionStore(tmp_path / "sessions")
    await session_store.create_session(Session(id="s1", agent_type="sebastian", title="S1"))
    gate = MagicMock()
    return DummyAgent(gate=gate, session_store=session_store)


@pytest.mark.asyncio
async def test_cancel_session_registers_pending_when_no_active_stream(agent) -> None:
    # No run_streaming has been invoked; _active_streams is empty.
    cancelled = await agent.cancel_session("s1", intent="cancel")

    assert cancelled is True
    assert agent._pending_cancel_intents["s1"] == "cancel"


@pytest.mark.asyncio
async def test_cancel_session_registers_pending_with_stop_intent(agent) -> None:
    cancelled = await agent.cancel_session("s1", intent="stop")

    assert cancelled is True
    assert agent._pending_cancel_intents["s1"] == "stop"


@pytest.mark.asyncio
async def test_run_streaming_consumes_pending_cancel_on_registration(tmp_path: Path) -> None:
    """REST 200 后用户立即点停止 → pending cancel 写入 → run_streaming 登记后立即消费."""
    class DummyAgent(BaseAgent):
        name = "sebastian"

    session_store = SessionStore(tmp_path / "sessions")
    await session_store.create_session(Session(id="s1", agent_type="sebastian", title="S1"))
    gate = MagicMock()
    agent = DummyAgent(gate=gate, session_store=session_store)

    # Simulate race: user cancels before run_streaming registers _active_streams.
    cancelled = await agent.cancel_session("s1", intent="cancel")
    assert cancelled is True
    assert "s1" in agent._pending_cancel_intents

    # run_streaming should consume the pending cancel and raise CancelledError.
    with pytest.raises(asyncio.CancelledError):
        await agent.run_streaming("hello", "s1")

    # Pending intent must be consumed.
    assert "s1" not in agent._pending_cancel_intents


@pytest.mark.asyncio
async def test_pending_cancel_ttl_expiry(agent) -> None:
    await agent.cancel_session("s1", intent="cancel")
    assert "s1" in agent._pending_cancel_intents

    # Trigger TTL manually (the handle is a real asyncio TimerHandle; invoking
    # its callback directly avoids sleeping 60 real seconds in tests).
    agent._expire_pending_cancel("s1")

    assert "s1" not in agent._pending_cancel_intents
    assert "s1" not in agent._pending_cancel_timers

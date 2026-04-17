from __future__ import annotations

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

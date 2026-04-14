from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
)
from tests.unit.core.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_base_agent_uses_injected_provider() -> None:
    """BaseAgent passes the injected LLMProvider to AgentLoop."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Hello from sub."),
            TextBlockStop(block_id="b0_0", text="Hello from sub."),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    from sebastian.memory.episodic_memory import EpisodicMemory

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    result = await agent.run("hi", session_id="test_sess_01")
    assert result == "Hello from sub."
    assert provider.call_count == 1

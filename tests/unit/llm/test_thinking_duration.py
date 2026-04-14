from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.base_agent import BaseAgent
from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
)
from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.store.session_store import SessionStore
from tests.unit.core.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_thinking_block_stop_includes_duration_ms() -> None:
    """ThinkingBlockStop SSE payload 应包含正值 duration_ms。"""
    published: list[dict[str, Any]] = []

    provider = MockLLMProvider(
        [
            ThinkingBlockStart(block_id="b0_0"),
            ThinkingDelta(block_id="b0_0", delta="hmm"),
            ThinkingBlockStop(block_id="b0_0", thinking="hmm"),
            TextBlockStart(block_id="b0_1"),
            TextDelta(block_id="b0_1", delta="ok"),
            TextBlockStop(block_id="b0_1", text="ok"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    async def capture_publish(session_id, event_type, payload):
        published.append({"type": event_type, "data": payload})

    agent._publish = capture_publish  # type: ignore[method-assign]

    await agent.run("hi", session_id="test_sess_01")

    stop_events = [
        e for e in published if "thinking_block" in str(e["type"]) and "stop" in str(e["type"])
    ]
    assert len(stop_events) == 1
    duration_ms = stop_events[0]["data"].get("duration_ms")
    assert duration_ms is not None
    assert isinstance(duration_ms, int)
    assert duration_ms >= 0

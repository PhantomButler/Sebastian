from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
)
from tests.unit.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_execute_delegated_task_returns_task_result() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.memory.episodic_memory import EpisodicMemory
    from sebastian.protocol.a2a.types import DelegateTask
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider([
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Task complete."),
        TextBlockStop(block_id="b0_0", text="Task complete."),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.create_session = AsyncMock()

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        registry=CapabilityRegistry(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    task = DelegateTask(task_id="t1", goal="do something")
    result = await agent.execute_delegated_task(task)

    assert result.task_id == "t1"
    assert result.ok is True
    assert result.output.get("summary") == "Task complete."


@pytest.mark.asyncio
async def test_execute_delegated_task_captures_exception() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.memory.episodic_memory import EpisodicMemory
    from sebastian.protocol.a2a.types import DelegateTask
    from sebastian.store.session_store import SessionStore

    # No turns provided - will raise RuntimeError on first stream call
    provider = MockLLMProvider()

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "test"

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.create_session = AsyncMock()

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        registry=CapabilityRegistry(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    task = DelegateTask(task_id="t2", goal="failing task")
    result = await agent.execute_delegated_task(task)

    assert result.task_id == "t2"
    assert result.ok is False
    assert result.error is not None

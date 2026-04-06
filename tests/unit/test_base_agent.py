from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_base_agent_persists_user_turn_before_inference_failure(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="failure-path",
            agent_type="sebastian",
            agent_id="sebastian_01",
            title="Failure path",
        )
    )

    agent = TestAgent(MagicMock(), store)

    async def failing_stream(*args, **kwargs):
        if False:
            yield None
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        agent._loop.stream = failing_stream  # type: ignore[attr-defined]
        await agent.run("Hello", "failure-path")

    messages = await store.get_messages("failure-path", "sebastian", "sebastian_01")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"


@pytest.mark.asyncio
async def test_base_agent_writes_messages_to_overridden_agent_context(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="subagent-session",
            agent_type="stock",
            agent_id="stock_01",
            title="Stock session",
        )
    )

    agent = TestAgent(MagicMock(), store)

    async def successful_stream(*args, **kwargs):
        from sebastian.core.stream_events import TurnDone

        yield TurnDone(full_text="done")

    agent._loop.stream = successful_stream  # type: ignore[attr-defined]
    response = await agent.run(
        "Check this thesis",
        "subagent-session",
        agent_name="stock",
    )

    assert response == "done"
    stock_messages = await store.get_messages(
        "subagent-session",
        agent_type="stock",
        agent_id="stock_01",
    )
    assert [message["role"] for message in stock_messages] == ["user", "assistant"]
    assert stock_messages[0]["content"] == "Check this thesis"
    sebastian_messages = await store.get_messages(
        "subagent-session",
        agent_type="sebastian",
        agent_id="sebastian_01",
    )
    assert sebastian_messages == []


@pytest.mark.asyncio
async def test_run_streaming_publishes_turn_events(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TurnDone
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="stream-session",
            agent_type="sebastian",
            agent_id="sebastian_01",
            title="Stream session",
        )
    )

    bus = EventBus()
    collected_events = []

    async def capture(event) -> None:
        collected_events.append(event)

    bus.subscribe(capture)

    agent = TestAgent(MagicMock(), store, bus)

    async def fake_stream(*args, **kwargs):
        yield TurnDone(full_text="response text")

    agent._loop.stream = fake_stream  # type: ignore[attr-defined]

    result = await agent.run_streaming("hello", "stream-session")

    assert result == "response text"
    types = [event.type for event in collected_events]
    assert EventType.TURN_RECEIVED in types
    assert EventType.TURN_RESPONSE in types

    received = next(event for event in collected_events if event.type == EventType.TURN_RECEIVED)
    assert received.data["session_id"] == "stream-session"
    assert received.data["agent_id"] == "sebastian_01"

    response = next(event for event in collected_events if event.type == EventType.TURN_RESPONSE)
    assert response.data["session_id"] == "stream-session"
    assert response.data["content"] == "response text"
    assert response.data["interrupted"] is False

    messages = await store.get_messages("stream-session", "sebastian", "sebastian_01")
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "response text"


@pytest.mark.asyncio
async def test_run_streaming_interrupt_publishes_interrupted(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(
            id="interrupt-session",
            agent_type="sebastian",
            agent_id="sebastian_01",
            title="Interrupt session",
        )
    )

    bus = EventBus()
    collected_events = []

    async def capture(event) -> None:
        collected_events.append(event)

    bus.subscribe(capture)

    agent = TestAgent(MagicMock(), store, bus)

    async def slow_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b0_0")
        yield TextDelta(block_id="b0_0", delta="partial")
        await asyncio.sleep(10)

    agent._loop.stream = slow_stream  # type: ignore[attr-defined]

    stream_task = asyncio.create_task(agent.run_streaming("hello", "interrupt-session"))
    await asyncio.sleep(0.05)
    stream_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stream_task

    types = [event.type for event in collected_events]
    assert EventType.TURN_INTERRUPTED in types
    interrupted = next(
        event for event in collected_events if event.type == EventType.TURN_INTERRUPTED
    )
    assert interrupted.data["session_id"] == "interrupt-session"
    assert interrupted.data["partial_content"] == "partial"

    messages = await store.get_messages("interrupt-session", "sebastian", "sebastian_01")
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "partial"


def test_base_agent_has_no_execute_delegated_task():
    """execute_delegated_task should be removed."""
    from sebastian.core.base_agent import BaseAgent

    assert not hasattr(BaseAgent, "execute_delegated_task")

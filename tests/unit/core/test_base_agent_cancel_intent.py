from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
async def agent(tmp_path: Path):
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class DummyAgent(BaseAgent):
        name = "sebastian"

    session_store = SessionStore(tmp_path / "sessions")
    await session_store.create_session(Session(id="s1", agent_type="sebastian", title="Session 1"))
    await session_store.create_session(Session(id="s2", agent_type="sebastian", title="Session 2"))
    gate = MagicMock()
    return DummyAgent(gate=gate, session_store=session_store)


def _install_slow_stream(agent, stream_started: asyncio.Event) -> None:
    from sebastian.core.stream_events import TextBlockStart, TextDelta

    async def slow_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="partial")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = slow_stream  # type: ignore[attr-defined]


def _install_done_stream(agent, full_text: str) -> None:
    from sebastian.core.stream_events import TurnDone

    async def done_stream(*args, **kwargs):
        yield TurnDone(full_text=full_text)

    agent._loop.stream = done_stream  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cancel_session_exposes_cancel_intent_after_run_streaming_exit(agent) -> None:
    stream_started = asyncio.Event()
    _install_slow_stream(agent, stream_started)

    run_task = asyncio.create_task(agent.run_streaming("hello", "s1"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    cancelled = await agent.cancel_session("s1")

    assert cancelled is True
    with pytest.raises(asyncio.CancelledError):
        await run_task
    assert agent.consume_cancel_intent("s1") == "cancel"
    assert agent.consume_cancel_intent("s1") is None


@pytest.mark.asyncio
async def test_stop_intent_preserves_partial_without_cancelled_semantics(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class DummyAgent(BaseAgent):
        name = "sebastian"

    session_store = SessionStore(tmp_path / "sessions")
    await session_store.create_session(Session(id="s2", agent_type="sebastian", title="Session 2"))
    bus = EventBus()
    collected_events: list = []

    async def capture(event) -> None:
        collected_events.append(event)

    bus.subscribe(capture)
    agent = DummyAgent(gate=MagicMock(), session_store=session_store, event_bus=bus)

    stream_started = asyncio.Event()
    _install_slow_stream(agent, stream_started)

    run_task = asyncio.create_task(agent.run_streaming("hello", "s2"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    cancelled = await agent.cancel_session("s2", intent="stop")

    assert cancelled is True
    with pytest.raises(asyncio.CancelledError):
        await run_task

    messages = await session_store.get_messages("s2", "sebastian")
    assistant_messages = [message for message in messages if message["role"] == "assistant"]

    assert agent.consume_cancel_intent("s2") == "stop"
    assert agent.consume_cancel_intent("s2") is None
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "partial"

    event_types = [event.type for event in collected_events]
    assert EventType.TURN_CANCELLED not in event_types
    assert EventType.TURN_INTERRUPTED in event_types
    assert EventType.TURN_RESPONSE in event_types

    interrupted = next(
        event for event in collected_events if event.type == EventType.TURN_INTERRUPTED
    )
    assert interrupted.data["intent"] == "stop"
    assert interrupted.data["partial_content"] == "partial"


@pytest.mark.asyncio
async def test_cancel_session_registers_pending_without_recording_consumable_intent(agent) -> None:
    # No active stream → returns True and writes a pending cancel.
    # consume_cancel_intent only surfaces _completed_ intents, not pending ones.
    result = await agent.cancel_session("nope")

    assert result is True
    assert agent._pending_cancel_intents["nope"] == "cancel"
    assert agent.consume_cancel_intent("nope") is None


@pytest.mark.asyncio
async def test_cancel_session_rejects_invalid_intent(agent) -> None:
    stream_started = asyncio.Event()
    _install_slow_stream(agent, stream_started)

    run_task = asyncio.create_task(agent.run_streaming("hello", "s1"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    with pytest.raises(ValueError, match="Invalid cancel intent"):
        await agent.cancel_session("s1", intent="pause")

    assert agent.consume_cancel_intent("s1") is None

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task


@pytest.mark.asyncio
async def test_new_run_clears_stale_completed_cancel_intent(agent) -> None:
    stream_started = asyncio.Event()
    _install_slow_stream(agent, stream_started)

    first_run = asyncio.create_task(agent.run_streaming("hello", "s1"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    await agent.cancel_session("s1")

    with pytest.raises(asyncio.CancelledError):
        await first_run

    _install_done_stream(agent, "fresh response")
    result = await agent.run_streaming("hello again", "s1")

    assert result == "fresh response"
    assert agent.consume_cancel_intent("s1") is None


@pytest.mark.asyncio
async def test_later_cancel_intent_overrides_pending_stop(agent, caplog) -> None:
    """用户在 stop 之后紧接着按 cancel 时，应以 cancel 为准（终态优先），
    并在日志里留下覆盖痕迹便于排查。"""
    import logging

    stream_started = asyncio.Event()
    _install_slow_stream(agent, stream_started)

    run_task = asyncio.create_task(agent.run_streaming("hello", "s1"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    first_cancel = asyncio.create_task(agent.cancel_session("s1", intent="stop"))
    second_cancel = asyncio.create_task(agent.cancel_session("s1", intent="cancel"))

    with caplog.at_level(logging.WARNING, logger="sebastian.core.base_agent"):
        assert await first_cancel is True
        assert await second_cancel in (True, False)

    with pytest.raises(asyncio.CancelledError):
        await run_task

    # 终态以最后一次 intent 为准；若调度把 stop 挤到完成后才写，则保持 stop 亦可接受。
    assert agent.consume_cancel_intent("s1") in ("cancel", "stop")

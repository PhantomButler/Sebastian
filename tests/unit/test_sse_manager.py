from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest


def _parse_sse_chunk(chunk: str) -> tuple[int, dict[str, Any]]:
    lines = [line for line in chunk.strip().splitlines() if line]
    assert lines[0].startswith("id: ")
    assert lines[1].startswith("data: ")
    event_id = int(lines[0].removeprefix("id: ").strip())
    payload = json.loads(lines[1].removeprefix("data: ").strip())
    return event_id, payload


@pytest.mark.asyncio
async def test_sse_stream_emits_event_id_and_preserves_payload_shape() -> None:
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    manager = SSEManager(bus)
    stream = manager.stream()
    chunk_task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "abc"}))
    chunk = await chunk_task
    event_id, payload = _parse_sse_chunk(chunk)
    assert event_id == 1
    assert payload["type"] == "turn.response"
    assert payload["event"] == "turn.response"
    assert payload["data"]["session_id"] == "abc"


@pytest.mark.asyncio
async def test_sse_session_stream_filters_other_sessions() -> None:
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    manager = SSEManager(bus)
    stream = manager.stream(session_id="abc")
    chunk_task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "xyz"}))
    await asyncio.sleep(0)
    assert not chunk_task.done()

    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "abc"}))
    chunk = await chunk_task
    event_id, payload = _parse_sse_chunk(chunk)
    assert event_id == 2
    assert payload["data"]["session_id"] == "abc"


@pytest.mark.asyncio
async def test_sse_fresh_stream_does_not_replay_buffered_events_without_last_event_id() -> None:
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    manager = SSEManager(bus)

    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "abc", "step": 1}))
    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "abc", "step": 2}))

    stream = manager.stream()
    chunk_task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    assert not chunk_task.done()

    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "abc", "step": 3}))
    chunk = await chunk_task
    event_id, payload = _parse_sse_chunk(chunk)
    assert event_id == 3
    assert payload["data"]["step"] == 3
    await stream.aclose()

    replay_stream = manager.stream(last_event_id=1)
    replay_chunk = await anext(replay_stream)
    replay_event_id, replay_payload = _parse_sse_chunk(replay_chunk)
    assert replay_event_id == 2
    assert replay_payload["data"]["step"] == 2
    await replay_stream.aclose()

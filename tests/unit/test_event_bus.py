from __future__ import annotations

import pytest


def test_event_types_added_for_block_level_events() -> None:
    from sebastian.protocol.events.types import EventType

    assert EventType.APPROVAL_REQUESTED.value == "approval.requested"
    assert EventType.APPROVAL_GRANTED.value == "approval.granted"
    assert EventType.APPROVAL_DENIED.value == "approval.denied"
    assert EventType.TURN_DELTA.value == "turn.delta"
    assert EventType.TURN_THINKING_DELTA.value == "turn.thinking_delta"
    assert EventType.TURN_INTERRUPTED.value == "turn.interrupted"
    assert EventType.THINKING_BLOCK_START.value == "thinking_block.start"
    assert EventType.THINKING_BLOCK_STOP.value == "thinking_block.stop"
    assert EventType.TEXT_BLOCK_START.value == "text_block.start"
    assert EventType.TEXT_BLOCK_STOP.value == "text_block.stop"
    assert EventType.TOOL_BLOCK_START.value == "tool_block.start"
    assert EventType.TOOL_BLOCK_STOP.value == "tool_block.stop"


@pytest.mark.asyncio
async def test_subscribe_and_publish() -> None:
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={"task_id": "t1"}))
    assert len(received) == 1
    assert received[0].type == EventType.TASK_CREATED


@pytest.mark.asyncio
async def test_subscribe_filtered_by_type() -> None:
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler, EventType.TASK_COMPLETED)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={}))
    await bus.publish(Event(type=EventType.TASK_COMPLETED, data={}))
    assert len(received) == 1
    assert received[0].type == EventType.TASK_COMPLETED


@pytest.mark.asyncio
async def test_unsubscribe() -> None:
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)
    bus.unsubscribe(handler)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={}))
    assert len(received) == 0


@pytest.mark.asyncio
async def test_handler_exception_does_not_crash_bus() -> None:
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    good_received: list[Event] = []

    async def bad_handler(event: Event) -> None:
        raise RuntimeError("oops")

    async def good_handler(event: Event) -> None:
        good_received.append(event)

    bus.subscribe(bad_handler)
    bus.subscribe(good_handler)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={}))
    assert len(good_received) == 1

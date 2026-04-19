from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.memory.consolidation import MemoryConsolidationScheduler
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_completed_event(
    session_id: str = "sess-001",
    agent_type: str = "researcher",
) -> Event:
    return Event(
        type=EventType.SESSION_COMPLETED,
        data={"session_id": session_id, "agent_type": agent_type},
    )


def _make_mock_worker() -> AsyncMock:
    worker = MagicMock()
    worker.consolidate_session = AsyncMock(return_value=None)
    return worker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_completed_with_memory_enabled_calls_worker() -> None:
    """Publishing SESSION_COMPLETED with memory enabled → consolidate_session called once."""
    event_bus = EventBus()
    worker = _make_mock_worker()

    scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=worker,
        memory_settings_fn=lambda: True,
    )

    event = _make_session_completed_event(session_id="sess-001", agent_type="researcher")
    await event_bus.publish(event)

    # Give the task a moment to execute
    await asyncio.sleep(0)
    # Drain any pending tasks
    await asyncio.gather(*list(scheduler._pending_tasks), return_exceptions=True)

    worker.consolidate_session.assert_called_once_with("sess-001", "researcher")


@pytest.mark.asyncio
async def test_session_completed_with_memory_disabled_does_not_call_worker() -> None:
    """Publishing SESSION_COMPLETED with memory disabled → consolidate_session NOT called."""
    event_bus = EventBus()
    worker = _make_mock_worker()

    scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=worker,
        memory_settings_fn=lambda: False,
    )

    event = _make_session_completed_event()
    await event_bus.publish(event)

    # Even after yielding control, worker should not be called
    await asyncio.sleep(0)

    worker.consolidate_session.assert_not_called()
    assert len(scheduler._pending_tasks) == 0


@pytest.mark.asyncio
async def test_session_completed_missing_session_id_skips_worker() -> None:
    """Event missing session_id → no task created."""
    event_bus = EventBus()
    worker = _make_mock_worker()

    _scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=worker,
        memory_settings_fn=lambda: True,
    )

    event = Event(
        type=EventType.SESSION_COMPLETED,
        data={"agent_type": "researcher"},  # no session_id
    )
    await event_bus.publish(event)
    await asyncio.sleep(0)

    worker.consolidate_session.assert_not_called()


@pytest.mark.asyncio
async def test_session_completed_missing_agent_type_skips_worker() -> None:
    """Event missing agent_type → no task created."""
    event_bus = EventBus()
    worker = _make_mock_worker()

    _scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=worker,
        memory_settings_fn=lambda: True,
    )

    event = Event(
        type=EventType.SESSION_COMPLETED,
        data={"session_id": "sess-001"},  # no agent_type
    )
    await event_bus.publish(event)
    await asyncio.sleep(0)

    worker.consolidate_session.assert_not_called()


@pytest.mark.asyncio
async def test_aclose_cancels_pending_tasks() -> None:
    """aclose() cancels all pending consolidation tasks."""
    event_bus = EventBus()

    # Worker that blocks indefinitely
    async def slow_consolidate(session_id: str, agent_type: str) -> None:
        await asyncio.sleep(9999)

    worker = MagicMock()
    worker.consolidate_session = AsyncMock(side_effect=slow_consolidate)

    scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=worker,
        memory_settings_fn=lambda: True,
    )

    event = _make_session_completed_event()
    await event_bus.publish(event)
    await asyncio.sleep(0)  # let the task start

    assert len(scheduler._pending_tasks) == 1

    # aclose() should cancel the task without hanging
    await asyncio.wait_for(scheduler.aclose(), timeout=2.0)
    assert len(scheduler._pending_tasks) == 0


@pytest.mark.asyncio
async def test_multiple_events_schedule_multiple_tasks() -> None:
    """Multiple SESSION_COMPLETED events each schedule their own consolidation task."""
    event_bus = EventBus()
    worker = _make_mock_worker()

    scheduler = MemoryConsolidationScheduler(
        event_bus=event_bus,
        worker=worker,
        memory_settings_fn=lambda: True,
    )

    events = [
        _make_session_completed_event(session_id=f"sess-{i:03d}", agent_type="researcher")
        for i in range(3)
    ]
    for event in events:
        await event_bus.publish(event)

    await asyncio.sleep(0)
    await asyncio.gather(*list(scheduler._pending_tasks), return_exceptions=True)

    assert worker.consolidate_session.call_count == 3

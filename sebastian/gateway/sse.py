from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _BufferedEvent:
    event_id: int
    event: Event


@dataclass(slots=True)
class _StreamSubscription:
    queue: asyncio.Queue[_BufferedEvent | None]
    session_id: str | None


class SSEManager:
    """Manages active SSE client connections. Subscribes to the global EventBus
    and broadcasts all events to connected clients as SSE-formatted strings."""

    def __init__(self, event_bus: EventBus) -> None:
        self._queues: list[_StreamSubscription] = []
        self._buffer: deque[_BufferedEvent] = deque(maxlen=500)
        self._next_event_id = 1
        self._lock = asyncio.Lock()
        event_bus.subscribe(self._on_event)

    async def _on_event(self, event: Event) -> None:
        async with self._lock:
            buffered_event = _BufferedEvent(self._next_event_id, event)
            self._next_event_id += 1
            self._buffer.append(buffered_event)
            logger.debug(
                "sse_event id=%d type=%s session=%s",
                buffered_event.event_id,
                buffered_event.event.type.value,
                buffered_event.event.data.get("session_id", "-"),
            )
            subscriptions = list(self._queues)

        for subscription in subscriptions:
            if (
                subscription.session_id is not None
                and event.data.get("session_id") != subscription.session_id
            ):
                continue
            try:
                subscription.queue.put_nowait(buffered_event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event %s", event.type)

    @staticmethod
    def _format_chunk(buffered_event: _BufferedEvent) -> str:
        payload = json.dumps(
            {
                "type": buffered_event.event.type.value,
                "data": buffered_event.event.data | {"ts": buffered_event.event.ts.isoformat()},
            }
        )
        return f"id: {buffered_event.event_id}\ndata: {payload}\n\n"

    async def stream(
        self,
        session_id: str | None = None,
        last_event_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Async generator — yield SSE-formatted strings for one client."""
        subscription = _StreamSubscription(
            queue=asyncio.Queue(maxsize=200),
            session_id=session_id,
        )
        async with self._lock:
            self._queues.append(subscription)
            replay_events: list[_BufferedEvent] = []
            if last_event_id is not None:
                replay_events = [
                    buffered_event
                    for buffered_event in self._buffer
                    if buffered_event.event_id > last_event_id
                    and (
                        session_id is None
                        or buffered_event.event.data.get("session_id") == session_id
                    )
                ]
        try:
            for buffered_event in replay_events:
                yield self._format_chunk(buffered_event)
            while True:
                queued_event = await subscription.queue.get()
                if queued_event is None:
                    break
                yield self._format_chunk(queued_event)
        finally:
            async with self._lock:
                if subscription in self._queues:
                    self._queues.remove(subscription)

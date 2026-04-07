from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None] | None]

_WILDCARD = "__all__"


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, handler: EventHandler, event_type: EventType | None = None) -> None:
        key = event_type.value if event_type is not None else _WILDCARD
        self._handlers[key].append(handler)

    def unsubscribe(self, handler: EventHandler, event_type: EventType | None = None) -> None:
        key = event_type.value if event_type is not None else _WILDCARD
        self._handlers[key] = [h for h in self._handlers[key] if h is not handler]

    def reset(self) -> None:
        """Clear all handlers. Used in tests to prevent handler leakage between tests."""
        self._handlers.clear()

    async def publish(self, event: Event) -> None:
        handlers = list(self._handlers.get(event.type.value, [])) + list(
            self._handlers.get(_WILDCARD, [])
        )
        if not handlers:
            return
        awaitables = []
        for h in handlers:
            result = h(event)
            if inspect.isawaitable(result):
                awaitables.append(result)
        if awaitables:
            results = await asyncio.gather(*awaitables, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning("Event handler %s raised: %s", handlers[i], result)


# Global singleton
bus = EventBus()

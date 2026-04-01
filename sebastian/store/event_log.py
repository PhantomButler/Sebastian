from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sebastian.protocol.events.types import Event
from sebastian.store.models import EventRecord


class EventLog:
    """Append-only event persistence.

    All events flow through EventBus first, then are persisted here
    for history queries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: Event) -> None:
        """Append an event to the log."""
        record = EventRecord(
            id=event.id,
            type=event.type.value,
            data=event.data,
            ts=event.ts,
        )
        self._session.add(record)
        await self._session.commit()

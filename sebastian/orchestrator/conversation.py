from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


class ConversationManager:
    """Conversation plane: manages pending approval futures.

    Approval requests are persisted to DB and suspend the awaiting coroutine
    indefinitely until the user grants or denies via the REST API.
    """

    def __init__(self, event_bus: EventBus, db_factory: Any = None) -> None:
        self._bus = event_bus
        self._db_factory = db_factory
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        session_id: str = "",
        agent_type: str = "",
    ) -> bool:
        """Persist approval record, then suspend until user grants or denies."""
        from sebastian.store.models import ApprovalRecord

        if self._db_factory is not None:
            async with self._db_factory() as db_session:
                record = ApprovalRecord(
                    id=approval_id,
                    task_id=task_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    reason=reason,
                    status="pending",
                    created_at=datetime.now(UTC),
                )
                db_session.add(record)
                await db_session.commit()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[approval_id] = future

        await self._bus.publish(
            Event(
                type=EventType.APPROVAL_REQUESTED,
                data={
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "session_id": session_id,
                    "agent_type": agent_type,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "reason": reason,
                },
            )
        )

        try:
            return await asyncio.wait_for(future, timeout=300.0)
        except TimeoutError:
            self._pending.pop(approval_id, None)
            logger.warning("Approval request %s timed out after 300s, denying.", approval_id)
            return False

    async def resolve_approval(self, approval_id: str, granted: bool) -> None:
        """Called by the approval API endpoint to resolve a pending request."""
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            logger.warning(
                "resolve_approval called for unknown or already-done approval: %s", approval_id
            )
            return
        future.set_result(granted)
        event_type = EventType.APPROVAL_GRANTED if granted else EventType.APPROVAL_DENIED
        await self._bus.publish(
            Event(
                type=event_type,
                data={"approval_id": approval_id, "granted": granted},
            )
        )

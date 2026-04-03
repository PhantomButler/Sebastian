from __future__ import annotations

import asyncio
import logging
from typing import Any

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


class ConversationManager:
    """Conversation plane: manages pending approval futures.
    Approval requests suspend the awaiting coroutine until the user
    grants or denies via the REST API. The event bus notifies frontend clients."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        timeout: float = 300.0,
    ) -> bool:
        """Suspend execution until the user approves or denies, or timeout (→ deny)."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[approval_id] = future

        await self._bus.publish(Event(
            type=EventType.USER_APPROVAL_REQUESTED,
            data={
                "approval_id": approval_id,
                "task_id": task_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
            },
        ))

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError:
            logger.warning("Approval %s timed out", approval_id)
            self._pending.pop(approval_id, None)
            return False

    async def resolve_approval(self, approval_id: str, granted: bool) -> None:
        """Called by the approval API endpoint to resolve a pending request."""
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            return
        future.set_result(granted)
        event_type = (
            EventType.USER_APPROVAL_GRANTED if granted else EventType.USER_APPROVAL_DENIED
        )
        await self._bus.publish(Event(
            type=event_type,
            data={"approval_id": approval_id, "granted": granted},
        ))

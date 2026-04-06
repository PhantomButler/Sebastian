from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


async def run_agent_session(
    agent: BaseAgent,
    session: Session,
    goal: str,
    session_store: SessionStore,
    index_store: IndexStore,
    event_bus: EventBus | None = None,
) -> None:
    """Run an agent on a session asynchronously. Sets status on completion/failure."""
    try:
        await agent.run_streaming(goal, session.id)
        session.status = SessionStatus.COMPLETED
    except Exception:
        logger.exception("Agent session %s failed", session.id)
        session.status = SessionStatus.FAILED
    finally:
        session.updated_at = datetime.now(UTC)
        session.last_activity_at = datetime.now(UTC)
        await session_store.update_session(session)
        await index_store.upsert(session)
        if event_bus is not None:
            event_type = (
                EventType.SESSION_COMPLETED
                if session.status == SessionStatus.COMPLETED
                else EventType.SESSION_FAILED
            )
            await event_bus.publish(
                Event(
                    type=event_type,
                    data={
                        "session_id": session.id,
                        "agent_type": session.agent_type,
                        "status": session.status.value,
                    },
                )
            )

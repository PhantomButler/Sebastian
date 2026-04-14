from __future__ import annotations

import asyncio
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
    thinking_effort: str | None = None,
) -> None:
    """Run an agent on a session asynchronously. Sets status on completion/failure."""
    try:
        await agent.run_streaming(goal, session.id, thinking_effort=thinking_effort)
        # ask_parent 工具会把 session.status 设为 WAITING；此时不覆盖为 COMPLETED
        if session.status != SessionStatus.WAITING:
            session.status = SessionStatus.COMPLETED
    except asyncio.CancelledError:
        session.status = SessionStatus.CANCELLED
        raise  # finally block runs first, then CancelledError propagates
    except Exception:
        logger.exception("Agent session %s failed", session.id)
        session.status = SessionStatus.FAILED
    finally:
        session.updated_at = datetime.now(UTC)
        session.last_activity_at = datetime.now(UTC)
        await session_store.update_session(session)
        await index_store.upsert(session)
        if event_bus is not None and session.status != SessionStatus.WAITING:
            # WAITING 状态由 ask_parent 工具自己发布 SESSION_WAITING 事件，此处跳过
            event_type = (
                EventType.SESSION_COMPLETED
                if session.status == SessionStatus.COMPLETED
                else EventType.SESSION_CANCELLED
                if session.status == SessionStatus.CANCELLED
                else EventType.SESSION_FAILED
            )
            await event_bus.publish(
                Event(
                    type=event_type,
                    data={
                        "session_id": session.id,
                        "parent_session_id": session.parent_session_id,
                        "agent_type": session.agent_type,
                        "goal": session.goal,
                        "status": session.status.value,
                    },
                )
            )

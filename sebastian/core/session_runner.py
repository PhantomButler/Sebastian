from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore

from sebastian.capabilities.tools._session_lock import release_session_lock
from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import Event, EventType

_TERMINAL_STATUSES = {
    SessionStatus.COMPLETED,
    SessionStatus.FAILED,
    SessionStatus.CANCELLED,
}

logger = logging.getLogger(__name__)


async def run_agent_session(
    agent: BaseAgent,
    session: Session,
    goal: str,
    session_store: SessionStore,
    event_bus: EventBus | None = None,
) -> None:
    """Run an agent on a session asynchronously. Sets status on completion/failure.

    当 cancel_intent == "stop" 时，run_agent_session 不接管状态机与落库，
    完全交由 stop_agent 工具负责 status=IDLE、update_session、事件发布，
    避免两处都写导致的状态双写。
    """
    stopped_by_tool = False
    try:
        await agent.run_streaming(goal, session.id)
        # ask_parent 工具会把 session.status 设为 WAITING；此时不覆盖为 COMPLETED
        if session.status != SessionStatus.WAITING:
            session.status = SessionStatus.COMPLETED
    except asyncio.CancelledError:
        cancel_intent = agent.consume_cancel_intent(session.id)
        if cancel_intent == "stop":
            stopped_by_tool = True
        else:
            session.status = SessionStatus.CANCELLED
            raise  # finally block runs first, then CancelledError propagates
    except Exception:
        logger.exception("Agent session %s failed", session.id)
        session.status = SessionStatus.FAILED
    finally:
        if not stopped_by_tool:
            session.updated_at = datetime.now(UTC)
            session.last_activity_at = datetime.now(UTC)
            await session_store.update_session(session)
            if session.status in _TERMINAL_STATUSES:
                release_session_lock(session.id)
            if event_bus is not None and session.status != SessionStatus.WAITING:
                # WAITING 状态由 ask_parent 工具自己发布 SESSION_WAITING 事件
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
                            "depth": session.depth,
                        },
                    )
                )

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

from sebastian.core.types import SessionStatus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 60


async def _check_stalled_sessions(
    index_store: IndexStore,
    session_store: SessionStore,
    event_bus: EventBus | None,
    agent_registry: dict[str, Any],
) -> list[str]:
    """Scan active sessions and mark stalled ones. Returns list of stalled session IDs."""
    now = datetime.now(UTC)
    all_sessions = await index_store.list_all()
    stalled_ids: list[str] = []

    for entry in all_sessions:
        if entry.get("status") != "active":
            continue

        agent_type = entry.get("agent_type", "")
        config = agent_registry.get(agent_type)
        threshold_minutes = config.stalled_threshold_minutes if config else 5

        last_activity_str = entry.get("last_activity_at", "")
        if not last_activity_str:
            continue

        try:
            last_activity = datetime.fromisoformat(last_activity_str)
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue

        if now - last_activity > timedelta(minutes=threshold_minutes):
            session_id = entry["id"]
            session = await session_store.get_session(session_id, agent_type)
            if session is None:
                continue

            session.status = SessionStatus.STALLED
            session.updated_at = now
            await session_store.update_session(session)
            await index_store.upsert(session)

            if event_bus is not None:
                await event_bus.publish(
                    Event(
                        type=EventType.SESSION_STALLED,
                        data={
                            "session_id": session_id,
                            "agent_type": agent_type,
                            "last_activity_at": last_activity_str,
                        },
                    )
                )

            stalled_ids.append(session_id)
            logger.warning("Session %s marked as stalled (inactive %s min)", session_id, threshold_minutes)

    return stalled_ids


async def _watchdog_loop(
    index_store: IndexStore,
    session_store: SessionStore,
    event_bus: EventBus | None,
    agent_registry: dict[str, Any],
) -> None:
    """Background loop that periodically checks for stalled sessions."""
    while True:
        try:
            await _check_stalled_sessions(index_store, session_store, event_bus, agent_registry)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Stalled watchdog error")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


def start_watchdog(
    index_store: IndexStore,
    session_store: SessionStore,
    event_bus: EventBus | None,
    agent_registry: dict[str, Any],
) -> asyncio.Task[None]:
    """Start the stalled-detection watchdog as a background task."""
    return asyncio.create_task(
        _watchdog_loop(index_store, session_store, event_bus, agent_registry),
        name="stalled_watchdog",
    )

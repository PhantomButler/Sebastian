from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.context.compaction import CompactionScheduler
    from sebastian.context.usage import TokenUsage
    from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)


async def allocate_exchange_for_turn(
    session_store: SessionStore,
    session_id: str,
    agent_type: str,
) -> tuple[str, int] | tuple[None, None]:
    """Allocate an exchange slot for the upcoming user→assistant turn.

    Returns ``(exchange_id, exchange_index)`` on success, or ``(None, None)``
    when the store does not support exchange allocation.

    Called from ``run_streaming`` only when a real ``db_factory`` is present.
    """
    exchange_id, exchange_index = await session_store.allocate_exchange(
        session_id, agent_type
    )
    return exchange_id, exchange_index


async def schedule_compaction_if_needed(
    *,
    scheduler: CompactionScheduler | None,
    session_id: str,
    agent_type: str,
    usage: TokenUsage | None,
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> None:
    """Fire-and-forget compaction check after a successful turn.

    Delegates to ``scheduler.maybe_schedule_after_turn``.  Any exception is
    caught, logged as a warning, and swallowed — compaction must never affect
    the user turn.

    If ``scheduler`` is ``None`` this is a no-op.
    """
    if scheduler is None:
        return
    try:
        await scheduler.maybe_schedule_after_turn(
            session_id=session_id,
            agent_type=agent_type,
            usage=usage,
            messages=messages,
            system_prompt=system_prompt,
        )
    except Exception as exc:
        logger.warning(
            "compaction scheduling error session=%s agent=%s: %s",
            session_id,
            agent_type,
            exc,
            exc_info=True,
        )

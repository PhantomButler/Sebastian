from __future__ import annotations

import asyncio
import logging

import sebastian.gateway.state as state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.memory.trace import preview_text, trace
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pending task registry — used by drain_pending_saves() in tests
# ---------------------------------------------------------------------------

_pending_tasks: set[asyncio.Task[None]] = set()


async def drain_pending_saves() -> None:
    """Wait for all in-flight background save tasks to complete.

    Intended for use in tests only. In production, background tasks complete
    independently and callers must not block on them.
    """
    pending = list(_pending_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ---------------------------------------------------------------------------
# Background save task
# ---------------------------------------------------------------------------


async def _do_save(content: str, session_id: str | None, agent_type: str) -> None:
    """Background task: extract candidate artifacts via LLM, then persist them."""
    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.extraction import ExtractorInput
    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
    from sebastian.memory.subject import resolve_subject
    from sebastian.memory.types import MemoryScope

    extractor = getattr(state, "memory_extractor", None)
    if extractor is None:
        trace("tool.memory_save.bg_skip", reason="no_extractor")
        return

    subject_id = await resolve_subject(
        MemoryScope.USER,
        session_id=session_id or "",
        agent_type=agent_type,
    )

    extractor_input = ExtractorInput(
        subject_context={"subject_id": subject_id, "agent_type": agent_type},
        conversation_window=[{"role": "user", "content": content}],
        known_slots=[s.model_dump() for s in DEFAULT_SLOT_REGISTRY.list_all()],
    )
    extractor_output = await extractor.extract(extractor_input)
    candidates = extractor_output.artifacts

    if not candidates:
        trace("tool.memory_save.bg_skip", reason="extractor_empty")
        return

    # Inject session evidence so provenance is traceable per session
    if session_id is not None:
        candidates = [
            c.model_copy(update={"evidence": [{"session_id": session_id}]})
            for c in candidates
        ]

    async with state.db_factory() as db_session:
        decisions = await process_candidates(
            candidates,
            session_id=session_id or "",
            agent_type=agent_type,
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="memory_save_tool",
            model_name=None,
            rule_version="phase_b_v1",
            input_source={"type": "memory_save_tool", "session_id": session_id},
        )
        await db_session.commit()

    trace("tool.memory_save.bg_done", decision_count=len(decisions))


def _log_bg_error(t: asyncio.Task[None]) -> None:
    if t.cancelled():
        return
    exc = t.exception()
    if exc is not None:
        logger.error("memory_save background task failed: %s", exc, exc_info=exc)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool(
    name="memory_save",
    description=(
        "保存用户明确要求记住的内容。"
        "仅当用户直接要求你记住某件事时调用，例如'帮我记住……'。"
    ),
    permission_tier=PermissionTier.LOW,
)
async def memory_save(content: str) -> ToolResult:
    trace(
        "tool.memory_save.start",
        content_preview=preview_text(content),
    )

    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能当前已关闭，无法保存。")

    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储暂时不可用，无法保存，请稍后再试。")

    session_id: str | None = getattr(state, "current_session_id", None) or None
    agent_type: str = getattr(state, "current_agent_type", "default") or "default"

    task: asyncio.Task[None] = asyncio.create_task(
        _do_save(content, session_id, agent_type),
        name=f"memory_save_{session_id}",
    )
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    task.add_done_callback(_log_bg_error)

    trace("tool.memory_save.dispatched", session_id=session_id)
    return ToolResult(ok=True, output={"message": "已记住，正在后台保存。"})

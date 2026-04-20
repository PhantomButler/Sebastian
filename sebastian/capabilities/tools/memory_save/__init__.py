from __future__ import annotations

import asyncio
import logging

import sebastian.gateway.state as state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.memory.trace import preview_text, trace
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)


async def _do_save(content: str, session_id: str | None, agent_type: str) -> None:
    """Background task: run the full memory write pipeline for an explicit save."""
    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.errors import InvalidCandidateError
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.resolver import resolve_candidate
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
    from sebastian.memory.subject import resolve_subject
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )
    from sebastian.memory.write_router import persist_decision

    memory_scope = MemoryScope.USER
    subject_id = await resolve_subject(
        memory_scope,
        session_id=session_id or "",
        agent_type=agent_type,
    )

    evidence = [{"session_id": session_id}] if session_id is not None else []
    candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content=content,
        structured_payload={},
        subject_hint=subject_id,
        scope=memory_scope,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=evidence,
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )

    try:
        DEFAULT_SLOT_REGISTRY.validate_candidate(candidate)
    except InvalidCandidateError as e:
        trace("tool.memory_save.bg_reject", reason="validation_failed", error=str(e))
        logger.warning("memory_save background task: validation failed: %s", e)
        return

    async with state.db_factory() as session:
        profile_store = ProfileMemoryStore(session)
        episode_store = EpisodeMemoryStore(session)
        entity_registry = EntityRegistry(session)
        decision_logger = MemoryDecisionLogger(session)

        from sebastian.memory.types import MemoryDecisionType

        decision = await resolve_candidate(
            candidate,
            subject_id=subject_id,
            profile_store=profile_store,
            slot_registry=DEFAULT_SLOT_REGISTRY,
            episode_store=episode_store,
        )

        if decision.decision == MemoryDecisionType.DISCARD:
            await decision_logger.append(
                decision,
                worker="memory_save_tool",
                model=None,
                rule_version="phase_b_v1",
                input_source={"type": "memory_save_tool", "session_id": session_id},
            )
            await session.commit()
            trace("tool.memory_save.bg_done", decision="DISCARD")
            return

        if decision.new_memory is None:
            trace("tool.memory_save.bg_error", reason="missing_new_memory")
            logger.error("memory_save background task: resolver produced no new_memory")
            return

        await persist_decision(
            decision,
            session=session,
            profile_store=profile_store,
            episode_store=episode_store,
            entity_registry=entity_registry,
        )
        await decision_logger.append(
            decision,
            worker="memory_save_tool",
            model=None,
            rule_version="phase_b_v1",
            input_source={"type": "memory_save_tool", "session_id": session_id},
        )
        await session.commit()

    trace(
        "tool.memory_save.bg_done",
        decision=decision.decision,
        new_memory_id=decision.new_memory.id if decision.new_memory is not None else None,
    )


@tool(
    name="memory_save",
    description=(
        "保存用户明确要求记住的内容。"
        "仅当用户直接要求你记住某件事时调用，例如"帮我记住……"。"
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

    def _log_bg_error(t: asyncio.Task[None]) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("memory_save background task failed: %s", exc, exc_info=exc)

    task.add_done_callback(_log_bg_error)

    trace("tool.memory_save.dispatched", session_id=session_id)
    return ToolResult(ok=True, output={"message": "已记住，正在后台保存。"})

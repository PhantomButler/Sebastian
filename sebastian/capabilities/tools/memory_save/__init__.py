from __future__ import annotations

import sebastian.gateway.state as state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.memory.decision_log import MemoryDecisionLogger
from sebastian.memory.entity_registry import EntityRegistry
from sebastian.memory.episode_store import EpisodeMemoryStore
from sebastian.memory.errors import InvalidCandidateError
from sebastian.memory.profile_store import ProfileMemoryStore
from sebastian.memory.resolver import resolve_candidate
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.subject import resolve_subject
from sebastian.memory.trace import preview_text, trace
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
)
from sebastian.memory.write_router import persist_decision
from sebastian.permissions.types import PermissionTier


@tool(
    name="memory_save",
    description=(
        "Save an explicit user-approved memory. "
        "Use only when the user asks you to remember something."
    ),
    permission_tier=PermissionTier.LOW,
)
async def memory_save(
    content: str,
    slot_id: str | None = None,
    scope: str = "user",
    policy_tags: list[str] | None = None,
) -> ToolResult:
    trace(
        "tool.memory_save.start",
        scope=scope,
        slot_id=slot_id,
        content_preview=preview_text(content),
    )
    # Check memory enabled
    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能已关闭")

    # Check db_factory available
    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储不可用")

    memory_scope = MemoryScope(scope)
    tool_session_id: str | None = getattr(state, "current_session_id", None) or None
    subject_id = await resolve_subject(
        memory_scope,
        session_id=tool_session_id or "",
        agent_type=getattr(state, "current_agent_type", "default") or "default",
    )

    # Determine kind from slot; fall back to FACT for no-slot saves
    slot = DEFAULT_SLOT_REGISTRY.get(slot_id) if slot_id else None
    kind = slot.kind_constraints[0] if slot else MemoryKind.FACT

    evidence = [{"session_id": tool_session_id}] if tool_session_id is not None else []
    candidate = CandidateArtifact(
        kind=kind,
        content=content,
        structured_payload={},
        subject_hint=subject_id,
        scope=memory_scope,
        slot_id=slot_id,
        cardinality=slot.cardinality if slot else None,
        resolution_policy=slot.resolution_policy if slot else None,
        confidence=1.0,
        source=MemorySource.EXPLICIT,
        evidence=evidence,
        valid_from=None,
        valid_until=None,
        policy_tags=policy_tags or [],
        needs_review=False,
    )

    try:
        DEFAULT_SLOT_REGISTRY.validate_candidate(candidate)
    except InvalidCandidateError as e:
        trace(
            "tool.memory_save.reject",
            reason="validation_failed",
            scope=memory_scope,
            slot_id=slot_id,
            error=str(e),
        )
        return ToolResult(ok=False, error=f"记忆参数校验失败：{e}")

    async with state.db_factory() as session:
        profile_store = ProfileMemoryStore(session)
        episode_store = EpisodeMemoryStore(session)
        entity_registry = EntityRegistry(session)
        decision_logger = MemoryDecisionLogger(session)

        decision = await resolve_candidate(
            candidate,
            subject_id=subject_id,
            profile_store=profile_store,
            slot_registry=DEFAULT_SLOT_REGISTRY,
        )

        if decision.decision == MemoryDecisionType.DISCARD:
            await decision_logger.append(
                decision,
                worker="memory_save_tool",
                model=None,
                rule_version="phase_b_v1",
                input_source={"type": "memory_save_tool", "session_id": tool_session_id},
            )
            await session.commit()
            trace(
                "tool.memory_save.done",
                decision=decision.decision,
                slot_id=decision.slot_id,
                new_memory_id=None,
            )
            return ToolResult(ok=False, error="记忆被丢弃：置信度不足或槽位不匹配")

        if decision.new_memory is None:
            trace(
                "tool.memory_save.reject",
                reason="missing_new_memory",
                decision=decision.decision,
                slot_id=decision.slot_id,
            )
            return ToolResult(ok=False, error="内部错误：未生成记忆对象")

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
            input_source={"type": "memory_save_tool", "session_id": tool_session_id},
        )

        await session.commit()

    trace(
        "tool.memory_save.done",
        decision=decision.decision,
        slot_id=decision.slot_id,
        new_memory_id=decision.new_memory.id if decision.new_memory is not None else None,
    )
    return ToolResult(ok=True, output={"saved": content, "slot_id": slot_id})

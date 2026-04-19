from __future__ import annotations

import sebastian.gateway.state as state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.memory.decision_log import MemoryDecisionLogger
from sebastian.memory.episode_store import EpisodeMemoryStore
from sebastian.memory.profile_store import ProfileMemoryStore
from sebastian.memory.resolver import resolve_candidate
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
)
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
    # Check memory enabled
    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能已关闭")

    # Check db_factory available
    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储不可用")

    # Phase B: owner is the fixed subject
    subject_id = "owner"

    # Determine kind from slot; fall back to FACT for no-slot saves
    slot = DEFAULT_SLOT_REGISTRY.get(slot_id) if slot_id else None
    kind = slot.kind_constraints[0] if slot else MemoryKind.FACT

    candidate = CandidateArtifact(
        kind=kind,
        content=content,
        structured_payload={},
        subject_hint=subject_id,
        scope=MemoryScope(scope),
        slot_id=slot_id,
        cardinality=slot.cardinality if slot else None,
        resolution_policy=slot.resolution_policy if slot else None,
        confidence=1.0,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=policy_tags or [],
        needs_review=False,
    )

    async with state.db_factory() as session:
        profile_store = ProfileMemoryStore(session)
        episode_store = EpisodeMemoryStore(session)
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
            )
            await session.commit()
            return ToolResult(ok=False, error="记忆被丢弃：置信度不足或槽位不匹配")

        new_memory = decision.new_memory
        if new_memory is None:
            return ToolResult(ok=False, error="内部错误：未生成记忆对象")

        if decision.decision == MemoryDecisionType.ADD:
            if new_memory.kind.value in ("episode", "summary"):
                await episode_store.add_episode(new_memory)
            else:
                await profile_store.add(new_memory)
        elif decision.decision == MemoryDecisionType.SUPERSEDE:
            await profile_store.supersede(decision.old_memory_ids, new_memory)

        await decision_logger.append(
            decision,
            worker="memory_save_tool",
            model=None,
            rule_version="phase_b_v1",
        )

        await session.commit()

    return ToolResult(ok=True, output={"saved": content, "slot_id": slot_id})

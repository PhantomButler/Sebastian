from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sebastian.memory.trace import trace
from sebastian.memory.types import MemoryDecisionType, MemoryKind, ResolveDecision

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore


async def persist_decision(
    decision: ResolveDecision,
    *,
    session: AsyncSession,
    profile_store: ProfileMemoryStore,
    episode_store: EpisodeMemoryStore,
    entity_registry: EntityRegistry,
) -> None:
    """Route a ResolveDecision to the correct store based on memory kind.

    - DISCARD / EXPIRE → no write (caller still logs).
    - EPISODE / SUMMARY → EpisodeMemoryStore
    - ENTITY → EntityRegistry.upsert_entity
    - RELATION → relation_candidates table
    - FACT / PREFERENCE → ProfileMemoryStore (add or supersede)
    """
    if decision.decision == MemoryDecisionType.DISCARD:
        trace(
            "persist.skip",
            decision=decision.decision,
            subject_id=decision.subject_id,
            scope=decision.scope,
            slot_id=decision.slot_id,
            old_memory_ids=decision.old_memory_ids,
        )
        return
    if decision.decision == MemoryDecisionType.EXPIRE:
        if decision.candidate.kind in (MemoryKind.FACT, MemoryKind.PREFERENCE):
            for memory_id in decision.old_memory_ids:
                await profile_store.expire(memory_id)
            _trace_write("profile", decision)
            return
        trace(
            "persist.skip",
            decision=decision.decision,
            subject_id=decision.subject_id,
            scope=decision.scope,
            slot_id=decision.slot_id,
            old_memory_ids=decision.old_memory_ids,
        )
        return
    if decision.new_memory is None:
        raise ValueError("non-DISCARD/EXPIRE decision must have new_memory")

    artifact = decision.new_memory
    kind = artifact.kind

    if kind == MemoryKind.EPISODE:
        await episode_store.add_episode(artifact)
        _trace_write("episode", decision)
        return
    if kind == MemoryKind.SUMMARY:
        await episode_store.add_summary(artifact)
        _trace_write("episode", decision)
        return
    if kind == MemoryKind.ENTITY:
        payload = artifact.structured_payload or {}
        await entity_registry.upsert_entity(
            canonical_name=payload.get("canonical_name", artifact.content),
            entity_type=payload.get("entity_type", "unknown"),
            aliases=payload.get("aliases", []),
            metadata=payload.get("metadata", {}),
        )
        _trace_write("entity", decision)
        return
    if kind == MemoryKind.RELATION:
        from sebastian.store.models import RelationCandidateRecord

        payload = artifact.structured_payload or {}
        session.add(
            RelationCandidateRecord(
                id=artifact.id or str(uuid4()),
                subject_id=artifact.subject_id,
                predicate=payload.get("predicate", ""),
                source_entity_id=payload.get("source_entity_id"),
                target_entity_id=payload.get("target_entity_id"),
                content=artifact.content,
                structured_payload=payload,
                confidence=artifact.confidence,
                status=artifact.status.value,
                valid_from=artifact.valid_from,
                valid_until=artifact.valid_until,
                provenance=artifact.provenance,
                policy_tags=artifact.policy_tags,
                created_at=artifact.recorded_at,
                updated_at=artifact.recorded_at,
            )
        )
        await session.flush()
        _trace_write("relation", decision)
        return

    # FACT / PREFERENCE
    if decision.decision in (MemoryDecisionType.SUPERSEDE, MemoryDecisionType.MERGE):
        await profile_store.supersede(decision.old_memory_ids, artifact)
    else:
        await profile_store.add(artifact)
    _trace_write("profile", decision)


def _trace_write(store: str, decision: ResolveDecision) -> None:
    trace(
        "persist.write",
        store=store,
        decision=decision.decision,
        subject_id=decision.subject_id,
        scope=decision.scope,
        slot_id=decision.slot_id,
        kind=(
            decision.new_memory.kind
            if decision.new_memory is not None
            else decision.candidate.kind
        ),
        new_memory_id=(
            decision.new_memory.id
            if decision.new_memory is not None
            else None
        ),
        old_memory_ids=decision.old_memory_ids,
    )

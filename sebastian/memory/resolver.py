from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemorySource,
    MemoryStatus,
    ResolutionPolicy,
    ResolveDecision,
)

if TYPE_CHECKING:
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import SlotRegistry
    from sebastian.store.models import ProfileMemoryRecord


CONFIDENCE_DISCARD_THRESHOLD = 0.3

# Source priority ranking (higher = more authoritative).
# See docs/architecture/spec/memory/artifact-model.md §9.
_SOURCE_PRIORITY: dict[MemorySource, int] = {
    MemorySource.EXPLICIT: 5,
    MemorySource.IMPORTED: 4,
    MemorySource.OBSERVED: 3,
    MemorySource.INFERRED: 2,
    MemorySource.SYSTEM_DERIVED: 1,
}


def _new_is_weaker(
    new: CandidateArtifact,
    existing: ProfileMemoryRecord,
) -> bool:
    """Return True when ``new`` should not replace ``existing`` on a single-cardinality slot.

    A new candidate is considered strictly weaker (→ DISCARD) when BOTH:
    - its source rank is lower than the existing record's, AND
    - its confidence is not at least ``existing.confidence + 0.1``.
    """
    existing_source = MemorySource(existing.source)
    new_rank = _SOURCE_PRIORITY[new.source]
    old_rank = _SOURCE_PRIORITY[existing_source]
    if new_rank < old_rank and new.confidence < existing.confidence + 0.1:
        return True
    return False


async def resolve_candidate(
    candidate: CandidateArtifact,
    *,
    subject_id: str,
    profile_store: ProfileMemoryStore,
    slot_registry: SlotRegistry,
) -> ResolveDecision:
    """Determine how a :class:`CandidateArtifact` should be stored.

    The resolver is purely deterministic — it never writes to the DB and
    never calls an LLM.  The caller is responsible for executing the
    returned :class:`ResolveDecision`.

    Resolution order
    ----------------
    1. Episode / Summary → always ADD.
    2. No slot + low confidence → DISCARD.
    3. Determine effective cardinality and resolution_policy (slot registry
       takes precedence over candidate-level hints).
    4. MULTI cardinality or APPEND_ONLY policy → ADD.
    5. SINGLE cardinality → check existing records; SUPERSEDE or ADD.
    6. Fallback → ADD.
    """
    # ------------------------------------------------------------------
    # 1. Episode / Summary → always ADD
    # ------------------------------------------------------------------
    if candidate.kind in (MemoryKind.EPISODE, MemoryKind.SUMMARY):
        return ResolveDecision(
            decision=MemoryDecisionType.ADD,
            reason="episodes and summaries are always appended",
            old_memory_ids=[],
            new_memory=_make_artifact(candidate, subject_id),
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=None,
        )

    # ------------------------------------------------------------------
    # 2. No slot + low confidence → DISCARD
    # ------------------------------------------------------------------
    if candidate.slot_id is None and candidate.confidence < CONFIDENCE_DISCARD_THRESHOLD:
        return ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason=(
                f"confidence {candidate.confidence:.2f} is below threshold "
                f"{CONFIDENCE_DISCARD_THRESHOLD} and no slot_id provided"
            ),
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=None,
        )

    # ------------------------------------------------------------------
    # 3. Determine effective cardinality and resolution_policy
    # ------------------------------------------------------------------
    effective_cardinality: Cardinality | None = candidate.cardinality
    effective_policy: ResolutionPolicy | None = candidate.resolution_policy

    if candidate.slot_id is not None:
        slot = slot_registry.get(candidate.slot_id)
        if slot is not None:
            effective_cardinality = slot.cardinality
            effective_policy = slot.resolution_policy

    # ------------------------------------------------------------------
    # 4. MULTI cardinality or APPEND_ONLY policy → ADD
    # ------------------------------------------------------------------
    if (
        effective_cardinality == Cardinality.MULTI
        or effective_policy == ResolutionPolicy.APPEND_ONLY
    ):
        return ResolveDecision(
            decision=MemoryDecisionType.ADD,
            reason="multi-cardinality or append-only policy: new entry added alongside existing",
            old_memory_ids=[],
            new_memory=_make_artifact(candidate, subject_id),
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        )

    # ------------------------------------------------------------------
    # 5. SINGLE cardinality → check existing records
    # ------------------------------------------------------------------
    if effective_cardinality == Cardinality.SINGLE and candidate.slot_id is not None:
        existing = await profile_store.get_active_by_slot(
            subject_id,
            candidate.scope.value,
            candidate.slot_id,
        )
        if not existing:
            return ResolveDecision(
                decision=MemoryDecisionType.ADD,
                reason="single-cardinality slot has no existing active record",
                old_memory_ids=[],
                new_memory=_make_artifact(candidate, subject_id),
                candidate=candidate,
                subject_id=subject_id,
                scope=candidate.scope,
                slot_id=candidate.slot_id,
            )

        if all(_new_is_weaker(candidate, r) for r in existing):
            return ResolveDecision(
                decision=MemoryDecisionType.DISCARD,
                reason=(
                    f"new candidate (source={candidate.source.value}, "
                    f"confidence={candidate.confidence:.2f}) has weaker "
                    f"source/confidence than all {len(existing)} existing "
                    f"record(s) on slot '{candidate.slot_id}'"
                ),
                old_memory_ids=[],
                new_memory=None,
                candidate=candidate,
                subject_id=subject_id,
                scope=candidate.scope,
                slot_id=candidate.slot_id,
            )

        return ResolveDecision(
            decision=MemoryDecisionType.SUPERSEDE,
            reason=(
                f"single-cardinality slot '{candidate.slot_id}' already has "
                f"{len(existing)} active record(s); superseding"
            ),
            old_memory_ids=[r.id for r in existing],
            new_memory=_make_artifact(candidate, subject_id),
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        )

    # ------------------------------------------------------------------
    # 6. Fallback → ADD
    # ------------------------------------------------------------------
    return ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="fallback: no specific resolution rule matched",
        old_memory_ids=[],
        new_memory=_make_artifact(candidate, subject_id),
        candidate=candidate,
        subject_id=subject_id,
        scope=candidate.scope,
        slot_id=candidate.slot_id,
    )


def _make_artifact(candidate: CandidateArtifact, subject_id: str) -> MemoryArtifact:
    """Convert a :class:`CandidateArtifact` into a ready-to-store :class:`MemoryArtifact`."""
    now = datetime.now(UTC)
    return MemoryArtifact(
        id=str(uuid4()),
        kind=candidate.kind,
        scope=candidate.scope,
        subject_id=subject_id,
        slot_id=candidate.slot_id,
        cardinality=candidate.cardinality,
        resolution_policy=candidate.resolution_policy,
        content=candidate.content,
        structured_payload=candidate.structured_payload,
        source=candidate.source,
        confidence=candidate.confidence,
        status=MemoryStatus.ACTIVE,
        valid_from=candidate.valid_from,
        valid_until=candidate.valid_until,
        recorded_at=now,
        last_accessed_at=None,
        access_count=0,
        provenance={"evidence": candidate.evidence},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=candidate.policy_tags,
    )

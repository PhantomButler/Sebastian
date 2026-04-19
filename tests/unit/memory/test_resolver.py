from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sebastian.memory.resolver import resolve_candidate
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ResolutionPolicy,
)
from sebastian.store.models import ProfileMemoryRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(**overrides: Any) -> CandidateArtifact:
    defaults: dict[str, Any] = {
        "kind": MemoryKind.PREFERENCE,
        "content": "some content",
        "structured_payload": {},
        "subject_hint": None,
        "scope": MemoryScope.USER,
        "slot_id": "user.preference.language",
        "cardinality": Cardinality.SINGLE,
        "resolution_policy": ResolutionPolicy.SUPERSEDE,
        "confidence": 0.9,
        "source": MemorySource.EXPLICIT,
        "evidence": [],
        "valid_from": None,
        "valid_until": None,
        "policy_tags": [],
        "needs_review": False,
    }
    defaults.update(overrides)
    return CandidateArtifact(**defaults)


def _make_record(record_id: str = "mem-old-1", **overrides: Any) -> ProfileMemoryRecord:
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "id": record_id,
        "subject_id": "user-1",
        "scope": MemoryScope.USER.value,
        "slot_id": "user.preference.language",
        "kind": MemoryKind.PREFERENCE.value,
        "content": "English",
        "structured_payload": {},
        "source": MemorySource.INFERRED.value,
        "confidence": 0.7,
        "status": "active",
        "valid_from": None,
        "valid_until": None,
        "provenance": {},
        "policy_tags": [],
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": None,
        "access_count": 0,
    }
    defaults.update(overrides)
    return ProfileMemoryRecord(**defaults)


# ---------------------------------------------------------------------------
# Fake store
# ---------------------------------------------------------------------------


class FakeProfileStore:
    def __init__(self, records: list[ProfileMemoryRecord]) -> None:
        self._records = records

    async def get_active_by_slot(
        self,
        subject_id: str,
        scope: str,
        slot_id: str,
    ) -> list[ProfileMemoryRecord]:
        return self._records


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_preference_supersedes_inferred() -> None:
    """Explicit PREFERENCE for a SINGLE slot → SUPERSEDE existing record."""
    existing = _make_record("mem-lang-old")
    store = FakeProfileStore([existing])
    registry = SlotRegistry()  # built-ins include user.preference.language (SINGLE/SUPERSEDE)

    candidate = _make_candidate(
        kind=MemoryKind.PREFERENCE,
        source=MemorySource.EXPLICIT,
        slot_id="user.preference.language",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.SUPERSEDE
    assert decision.old_memory_ids == ["mem-lang-old"]


@pytest.mark.asyncio
async def test_multi_value_fact_adds_not_supersedes() -> None:
    """MULTI cardinality FACT → ADD (not SUPERSEDE), even if existing records present."""
    existing = _make_record(
        "mem-fact-old",
        slot_id="user.known_languages",
        kind=MemoryKind.FACT.value,
    )
    store = FakeProfileStore([existing])
    # Use a registry with a custom MULTI slot
    from sebastian.memory.types import SlotDefinition

    registry = SlotRegistry(
        slots=[
            SlotDefinition(
                slot_id="user.known_languages",
                scope=MemoryScope.USER,
                subject_kind="user",
                cardinality=Cardinality.MULTI,
                resolution_policy=ResolutionPolicy.APPEND_ONLY,
                kind_constraints=[MemoryKind.FACT],
                description="Languages the user knows",
            )
        ]
    )

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.OBSERVED,
        slot_id="user.known_languages",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.ADD
    assert decision.old_memory_ids == []


@pytest.mark.asyncio
async def test_episode_is_always_add() -> None:
    """EPISODE kind → always ADD regardless of existing state."""
    store = FakeProfileStore([])  # irrelevant, should not be queried
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.EPISODE,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        source=MemorySource.OBSERVED,
        confidence=0.85,
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.ADD
    assert decision.old_memory_ids == []
    assert decision.new_memory is not None


@pytest.mark.asyncio
async def test_low_confidence_inferred_no_slot_is_discarded() -> None:
    """Low-confidence inferred candidate without slot_id → DISCARD."""
    store = FakeProfileStore([])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.INFERRED,
        confidence=0.2,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.DISCARD


@pytest.mark.asyncio
async def test_resolver_discards_low_priority_overwrite() -> None:
    """SUPERSEDE candidate is DISCARDed when weaker source AND lower confidence than existing."""
    existing = _make_record(
        "mem-tz-old",
        slot_id="user.profile.timezone",
        kind=MemoryKind.FACT.value,
        source=MemorySource.EXPLICIT.value,
        confidence=0.95,
        content="Asia/Shanghai",
    )
    store = FakeProfileStore([existing])
    registry = SlotRegistry()  # built-ins include user.profile.timezone (SINGLE/SUPERSEDE, FACT)

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.INFERRED,
        confidence=0.6,
        slot_id="user.profile.timezone",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        content="Asia/Tokyo",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.DISCARD
    assert decision.old_memory_ids == []
    assert decision.new_memory is None


@pytest.mark.asyncio
async def test_resolver_supersedes_when_new_has_higher_source() -> None:
    """Higher source overrides even at lower confidence."""
    existing = _make_record(
        "mem-tz-old",
        slot_id="user.profile.timezone",
        kind=MemoryKind.FACT.value,
        source=MemorySource.INFERRED.value,
        confidence=0.5,
        content="Asia/Tokyo",
    )
    store = FakeProfileStore([existing])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.EXPLICIT,
        confidence=0.9,
        slot_id="user.profile.timezone",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        content="Asia/Shanghai",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.SUPERSEDE
    assert decision.old_memory_ids == ["mem-tz-old"]


@pytest.mark.asyncio
async def test_resolver_supersedes_when_new_has_much_higher_confidence_same_source() -> None:
    """Same source but much higher confidence → SUPERSEDE (new not strictly weaker)."""
    existing = _make_record(
        "mem-tz-old",
        slot_id="user.profile.timezone",
        kind=MemoryKind.FACT.value,
        source=MemorySource.INFERRED.value,
        confidence=0.3,
        content="Asia/Tokyo",
    )
    store = FakeProfileStore([existing])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.INFERRED,
        confidence=0.9,
        slot_id="user.profile.timezone",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        content="Asia/Shanghai",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.SUPERSEDE
    assert decision.old_memory_ids == ["mem-tz-old"]

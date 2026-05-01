from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.stores.episode_store import EpisodeMemoryStore
from sebastian.memory.resolver import resolve_candidate
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    ResolutionPolicy,
)
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base
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
async def test_explicit_preference_supersedes_inferred(caplog) -> None:
    """Explicit PREFERENCE for a SINGLE slot → SUPERSEDE existing record."""
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
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
    assert "MEMORY_TRACE resolve.decision" in caplog.text
    assert "decision=SUPERSEDE" in caplog.text
    assert "old_count=1" in caplog.text


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
async def test_resolver_provenance_includes_session_id() -> None:
    """Resolver lifts ``session_id`` from evidence into provenance top-level."""
    store = FakeProfileStore([])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.SUMMARY,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        source=MemorySource.SYSTEM_DERIVED,
        confidence=0.8,
        evidence=[{"session_id": "s-xyz", "note": "from summary"}],
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.ADD
    assert decision.new_memory is not None
    assert decision.new_memory.provenance["session_id"] == "s-xyz"
    assert decision.new_memory.provenance["evidence"] == [
        {"session_id": "s-xyz", "note": "from summary"}
    ]


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


# ---------------------------------------------------------------------------
# Branch coverage: every decision path in resolver.resolve_candidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_cardinality_no_existing_returns_add() -> None:
    """SINGLE slot with no existing active record → ADD (step 5 empty branch)."""
    store = FakeProfileStore([])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.PREFERENCE,
        source=MemorySource.EXPLICIT,
        slot_id="user.preference.response_style",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        confidence=0.9,
        content="concise",
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
    assert decision.slot_id == "user.preference.response_style"


@pytest.mark.asyncio
async def test_append_only_policy_returns_add() -> None:
    """APPEND_ONLY policy (non-SINGLE cardinality) → ADD (step 4 branch)."""
    # Use candidate-level APPEND_ONLY without registering a slot so that the
    # slot registry does not override the policy.  slot_id=None means step 3
    # leaves effective_policy as the candidate's APPEND_ONLY.
    store = FakeProfileStore([])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.ENTITY,
        source=MemorySource.OBSERVED,
        slot_id=None,
        cardinality=None,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        confidence=0.8,
        content="some entity",
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
async def test_inferred_no_slot_medium_confidence_returns_add() -> None:
    """INFERRED source, no slot, confidence=0.5 (> 0.3 threshold) → fallback ADD."""
    store = FakeProfileStore([])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.ENTITY,
        source=MemorySource.INFERRED,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.5,
        content="possibly a person named Alice",
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
async def test_relation_kind_without_slot_returns_add() -> None:
    """kind=RELATION with slot_id=None → fallback ADD (step 6 branch)."""
    store = FakeProfileStore([])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.RELATION,
        source=MemorySource.OBSERVED,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        content="Alice knows Bob",
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
    assert decision.slot_id is None


@pytest.mark.asyncio
async def test_explicit_overrides_inferred_existing_returns_supersede() -> None:
    """EXPLICIT candidate with existing INFERRED record → SUPERSEDE."""
    existing = _make_record(
        "mem-style-old",
        slot_id="user.preference.response_style",
        kind=MemoryKind.PREFERENCE.value,
        source=MemorySource.INFERRED.value,
        confidence=0.6,
        content="detailed",
    )
    store = FakeProfileStore([existing])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.PREFERENCE,
        source=MemorySource.EXPLICIT,
        slot_id="user.preference.response_style",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        confidence=0.9,
        content="concise",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user-1",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.SUPERSEDE
    assert decision.old_memory_ids == [existing.id]
    assert decision.new_memory is not None


@pytest.mark.asyncio
async def test_inferred_lower_confidence_vs_explicit_existing_returns_discard() -> None:
    """INFERRED + lower confidence vs EXPLICIT existing → DISCARD (all existing stronger)."""
    existing = _make_record(
        "mem-style-old",
        slot_id="user.preference.response_style",
        kind=MemoryKind.PREFERENCE.value,
        source=MemorySource.EXPLICIT.value,
        confidence=0.9,
        content="concise",
    )
    store = FakeProfileStore([existing])
    registry = SlotRegistry()

    candidate = _make_candidate(
        kind=MemoryKind.PREFERENCE,
        source=MemorySource.INFERRED,
        slot_id="user.preference.response_style",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        confidence=0.5,
        content="detailed",
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
    assert "weaker" in decision.reason


# ---------------------------------------------------------------------------
# Episode exact-duplicate deduplication (Step 2)
# ---------------------------------------------------------------------------


@pytest.fixture
async def episode_db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_episode_artifact(artifact_id: str, kind: MemoryKind, content: str) -> MemoryArtifact:
    now = datetime.now(UTC)
    return MemoryArtifact(
        id=artifact_id,
        kind=kind,
        scope=MemoryScope.USER,
        subject_id="user:owner",
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        content=content,
        structured_payload={},
        source=MemorySource.OBSERVED,
        confidence=0.85,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=now,
        last_accessed_at=None,
        access_count=0,
        provenance={"session_id": "sess-dedup"},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )


@pytest.mark.asyncio
async def test_episode_exact_duplicate_returns_discard(episode_db_session) -> None:
    """resolve_candidate with episode_store must DISCARD exact-content duplicates."""
    content = "本次讨论了记忆模块的去重逻辑"

    # Pre-populate the store with an existing record
    ep_store = EpisodeMemoryStore(episode_db_session)
    existing = await ep_store.add_summary(
        _make_episode_artifact("sum-existing", MemoryKind.SUMMARY, content)
    )

    profile_store = FakeProfileStore([])
    registry = SlotRegistry()
    candidate = _make_candidate(
        kind=MemoryKind.SUMMARY,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        source=MemorySource.SYSTEM_DERIVED,
        confidence=0.8,
        content=content,
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user:owner",
        profile_store=profile_store,
        slot_registry=registry,
        episode_store=ep_store,
    )

    assert decision.decision == MemoryDecisionType.DISCARD
    assert existing.id in decision.old_memory_ids
    assert decision.new_memory is None
    assert "duplicate" in decision.reason or "重复" in decision.reason


@pytest.mark.asyncio
async def test_episode_non_duplicate_still_returns_add(episode_db_session) -> None:
    """resolve_candidate with episode_store must ADD when content differs."""
    ep_store = EpisodeMemoryStore(episode_db_session)
    await ep_store.add_episode(
        _make_episode_artifact("ep-other", MemoryKind.EPISODE, "完全不同的内容")
    )

    profile_store = FakeProfileStore([])
    registry = SlotRegistry()
    candidate = _make_candidate(
        kind=MemoryKind.EPISODE,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        source=MemorySource.OBSERVED,
        confidence=0.85,
        content="全新内容，不重复",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user:owner",
        profile_store=profile_store,
        slot_registry=registry,
        episode_store=ep_store,
    )

    assert decision.decision == MemoryDecisionType.ADD
    assert decision.new_memory is not None


@pytest.mark.asyncio
async def test_episode_without_episode_store_still_adds() -> None:
    """resolve_candidate without episode_store keeps the old ADD-always behaviour."""
    profile_store = FakeProfileStore([])
    registry = SlotRegistry()
    candidate = _make_candidate(
        kind=MemoryKind.EPISODE,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        source=MemorySource.OBSERVED,
        confidence=0.85,
        content="任意内容",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user:owner",
        profile_store=profile_store,
        slot_registry=registry,
        # no episode_store
    )

    assert decision.decision == MemoryDecisionType.ADD


# ---------------------------------------------------------------------------
# MERGE decision path (Task 6)
# ---------------------------------------------------------------------------


class FakeProfileStoreWithExact(FakeProfileStore):
    """Extends FakeProfileStore with find_active_exact support."""

    def __init__(
        self,
        records: list[ProfileMemoryRecord],
        exact_record: ProfileMemoryRecord | None = None,
    ) -> None:
        super().__init__(records)
        self._exact_record = exact_record

    async def find_active_exact(
        self,
        *,
        subject_id: str,
        scope: str,
        slot_id: str,
        kind: str,
        content: str,
    ) -> ProfileMemoryRecord | None:
        if self._exact_record is not None:
            r = self._exact_record
            if (
                r.subject_id == subject_id
                and r.scope == scope
                and r.slot_id == slot_id
                and r.kind == kind
                and r.content == content
            ):
                return r
        return None


@pytest.mark.asyncio
async def test_merge_policy_exact_duplicate_returns_merge() -> None:
    """MULTI MERGE-policy slot with exact content duplicate → MERGE decision."""
    from sebastian.memory.types import SlotDefinition

    content = "用户使用 Sebastian"
    existing = _make_record(
        "mem-merge-old",
        subject_id="user:owner",
        slot_id="test.multi.merge",
        kind=MemoryKind.FACT.value,
        content=content,
        source=MemorySource.EXPLICIT.value,
        confidence=0.9,
    )
    store = FakeProfileStoreWithExact([existing], exact_record=existing)
    registry = SlotRegistry(
        slots=[
            SlotDefinition(
                slot_id="test.multi.merge",
                scope=MemoryScope.USER,
                subject_kind="user",
                cardinality=Cardinality.MULTI,
                resolution_policy=ResolutionPolicy.MERGE,
                kind_constraints=[MemoryKind.FACT],
                description="Test multi merge slot",
            )
        ]
    )

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.EXPLICIT,
        slot_id="test.multi.merge",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.MERGE,
        confidence=0.9,
        content=content,
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user:owner",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.MERGE
    assert decision.old_memory_ids == [existing.id]
    assert decision.new_memory is not None
    assert decision.new_memory.cardinality == Cardinality.MULTI
    assert decision.new_memory.resolution_policy == ResolutionPolicy.MERGE


@pytest.mark.asyncio
async def test_merge_policy_non_duplicate_still_adds() -> None:
    """MULTI MERGE-policy slot with no matching existing content → ADD (not MERGE)."""
    from sebastian.memory.types import SlotDefinition

    store = FakeProfileStoreWithExact([], exact_record=None)
    registry = SlotRegistry(
        slots=[
            SlotDefinition(
                slot_id="test.multi.merge",
                scope=MemoryScope.USER,
                subject_kind="user",
                cardinality=Cardinality.MULTI,
                resolution_policy=ResolutionPolicy.MERGE,
                kind_constraints=[MemoryKind.FACT],
                description="Test multi merge slot",
            )
        ]
    )

    candidate = _make_candidate(
        kind=MemoryKind.FACT,
        source=MemorySource.EXPLICIT,
        slot_id="test.multi.merge",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.MERGE,
        confidence=0.9,
        content="全新内容，不重复",
    )

    decision = await resolve_candidate(
        candidate,
        subject_id="user:owner",
        profile_store=store,
        slot_registry=registry,
    )

    assert decision.decision == MemoryDecisionType.ADD
    assert decision.old_memory_ids == []
    assert decision.new_memory is not None

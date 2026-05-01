from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.stores.entity_registry import EntityRegistry
from sebastian.memory.stores.episode_store import EpisodeMemoryStore, ensure_episode_fts
from sebastian.memory.stores.profile_store import ProfileMemoryStore
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    ResolveDecision,
)
from sebastian.memory.writing.write_router import persist_decision
from sebastian.store import models  # noqa: F401 — ensure all tables are registered
from sebastian.store.database import Base
from sebastian.store.models import (
    EntityRecord,
    EpisodeMemoryRecord,
    ProfileMemoryRecord,
    RelationCandidateRecord,
)


@pytest.fixture
async def db_session():
    from sebastian.memory.startup import ensure_profile_fts

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_episode_fts(conn)
        await ensure_profile_fts(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _artifact(kind: MemoryKind, **overrides: Any) -> MemoryArtifact:
    now = datetime.now(UTC)
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        kind=kind,
        scope=MemoryScope.USER,
        subject_id="owner",
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        content="c",
        structured_payload={},
        source=MemorySource.EXPLICIT,
        confidence=0.9,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=now,
        last_accessed_at=None,
        access_count=0,
        provenance={},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )
    defaults.update(overrides)
    return MemoryArtifact(**defaults)


def _candidate(kind: MemoryKind) -> CandidateArtifact:
    return CandidateArtifact(
        kind=kind,
        content="c",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def _stores(session) -> tuple[ProfileMemoryStore, EpisodeMemoryStore, EntityRegistry]:
    return (
        ProfileMemoryStore(session),
        EpisodeMemoryStore(session),
        EntityRegistry(session),
    )


async def test_persist_decision_discard_writes_nothing(db_session, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    profile_store, episode_store, entity_registry = _stores(db_session)
    decision = ResolveDecision(
        decision=MemoryDecisionType.DISCARD,
        reason="r",
        old_memory_ids=[],
        new_memory=None,
        candidate=_candidate(MemoryKind.FACT),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    for model in (
        ProfileMemoryRecord,
        EpisodeMemoryRecord,
        EntityRecord,
        RelationCandidateRecord,
    ):
        rows = (await db_session.scalars(select(model))).all()
        assert rows == []
    assert "MEMORY_TRACE persist.skip" in caplog.text
    assert "decision=DISCARD" in caplog.text


async def test_persist_decision_fact_add_writes_profile(db_session, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(MemoryKind.FACT, content="I like tea")
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.FACT),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].content == "I like tea"
    assert rows[0].status == MemoryStatus.ACTIVE.value
    assert rows[0].kind == "fact"
    assert "MEMORY_TRACE persist.write" in caplog.text
    assert "store=profile" in caplog.text
    assert f"new_memory_id={artifact.id}" in caplog.text


async def test_persist_decision_fact_supersede_marks_old_and_inserts_new(
    db_session,
) -> None:
    profile_store, episode_store, entity_registry = _stores(db_session)

    # Insert an initial active record via profile_store.
    old_artifact = _artifact(MemoryKind.FACT, content="old fact", slot_id="pet_name")
    await profile_store.add(old_artifact)

    new_artifact = _artifact(MemoryKind.FACT, content="new fact", slot_id="pet_name")
    decision = ResolveDecision(
        decision=MemoryDecisionType.SUPERSEDE,
        reason="r",
        old_memory_ids=[old_artifact.id],
        new_memory=new_artifact,
        candidate=_candidate(MemoryKind.FACT),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="pet_name",
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows_by_id = {
        row.id: row for row in (await db_session.scalars(select(ProfileMemoryRecord))).all()
    }
    assert rows_by_id[old_artifact.id].status == MemoryStatus.SUPERSEDED.value
    assert rows_by_id[new_artifact.id].status == MemoryStatus.ACTIVE.value
    assert rows_by_id[new_artifact.id].content == "new fact"


async def test_persist_decision_episode_add_writes_episode(db_session) -> None:
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(MemoryKind.EPISODE, content="we went hiking")
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.EPISODE),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(EpisodeMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].kind == "episode"
    assert rows[0].content == "we went hiking"


async def test_persist_decision_summary_add_writes_summary(db_session) -> None:
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(MemoryKind.SUMMARY, content="session recap")
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.SUMMARY),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(EpisodeMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].kind == "summary"
    assert rows[0].content == "session recap"


async def test_persist_decision_entity_add_writes_entity(db_session) -> None:
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(
        MemoryKind.ENTITY,
        content="小橘",
        structured_payload={
            "canonical_name": "小橘",
            "entity_type": "pet",
            "aliases": ["橘猫"],
            "metadata": {"color": "orange"},
        },
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.ENTITY),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(EntityRecord))).all()
    assert len(rows) == 1
    assert rows[0].canonical_name == "小橘"
    assert rows[0].entity_type == "pet"
    assert "橘猫" in rows[0].aliases
    assert rows[0].entity_metadata == {"color": "orange"}


async def test_persist_decision_relation_add_writes_relation_candidate(
    db_session,
) -> None:
    profile_store, episode_store, entity_registry = _stores(db_session)
    valid_from = datetime(2026, 1, 1, tzinfo=UTC)
    valid_until = datetime(2026, 2, 1, tzinfo=UTC)
    artifact = _artifact(
        MemoryKind.RELATION,
        content="owner owns 小橘",
        valid_from=valid_from,
        valid_until=valid_until,
        structured_payload={
            "predicate": "owns",
            "source_entity_id": "owner",
            "target_entity_id": "entity-xiaoju",
        },
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.RELATION),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(RelationCandidateRecord))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.predicate == "owns"
    assert row.source_entity_id == "owner"
    assert row.target_entity_id == "entity-xiaoju"
    assert row.content == "owner owns 小橘"
    assert row.status == MemoryStatus.ACTIVE.value
    assert row.valid_from == valid_from.replace(tzinfo=None)
    assert row.valid_until == valid_until.replace(tzinfo=None)


async def test_persist_decision_time_bound_relation_preserves_validity_window(
    db_session,
) -> None:
    profile_store, episode_store, entity_registry = _stores(db_session)
    valid_from = datetime(2026, 3, 1, tzinfo=UTC)
    valid_until = datetime(2026, 4, 1, tzinfo=UTC)
    artifact = _artifact(
        MemoryKind.RELATION,
        content="project phase active during March",
        valid_from=valid_from,
        valid_until=valid_until,
        structured_payload={
            "predicate": "active_phase",
            "source_entity_id": "project-sebastian",
            "target_entity_id": "phase-memory",
        },
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.RELATION),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    row = (await db_session.scalars(select(RelationCandidateRecord))).one()
    assert row.valid_from == valid_from.replace(tzinfo=None)
    assert row.valid_until == valid_until.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# RelationCandidateRecord.policy_tags persistence (Step 3)
# ---------------------------------------------------------------------------


async def test_persist_decision_relation_persists_policy_tags(db_session) -> None:
    """persist_decision() must persist policy_tags on RelationCandidateRecord."""
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(
        MemoryKind.RELATION,
        content="owner relationship with project",
        policy_tags=["do_not_auto_inject", "agent:sebastian"],
        structured_payload={
            "predicate": "manages",
            "source_entity_id": "owner",
            "target_entity_id": "entity-project",
        },
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.RELATION),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    row = (await db_session.scalars(select(RelationCandidateRecord))).one()
    assert row.policy_tags == ["do_not_auto_inject", "agent:sebastian"]


async def test_persist_decision_relation_persists_empty_policy_tags(db_session) -> None:
    """policy_tags defaults to an empty list when not supplied."""
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(
        MemoryKind.RELATION,
        content="simple relation",
        policy_tags=[],
        structured_payload={"predicate": "knows"},
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.RELATION),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    row = (await db_session.scalars(select(RelationCandidateRecord))).one()
    assert row.policy_tags == []


# ---------------------------------------------------------------------------
# MERGE decision path (Task 6)
# ---------------------------------------------------------------------------


async def test_persist_decision_expire_marks_profile_row_expired(db_session, caplog) -> None:
    """persist_decision with EXPIRE must mark the targeted profile row as expired."""
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    profile_store, episode_store, entity_registry = _stores(db_session)

    old_artifact = _artifact(MemoryKind.FACT, content="no longer current")
    await profile_store.add(old_artifact)

    placeholder_candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="EXPIRE: no longer current",
        structured_payload={},
        subject_hint="user:owner",
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.0,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.EXPIRE,
        reason="no longer current",
        old_memory_ids=[old_artifact.id],
        new_memory=None,
        candidate=placeholder_candidate,
        subject_id="user:owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].status == MemoryStatus.EXPIRED.value
    assert "MEMORY_TRACE persist.write" in caplog.text
    assert "store=profile" in caplog.text


async def test_persist_decision_fact_merge_marks_old_and_inserts_new(
    db_session,
) -> None:
    """persist_decision with MERGE supersedes old record and inserts new active record."""
    from sebastian.memory.types import Cardinality, ResolutionPolicy

    profile_store, episode_store, entity_registry = _stores(db_session)

    old_artifact = _artifact(
        MemoryKind.FACT,
        content="用户使用 Sebastian",
        slot_id="test.multi.merge",
    )
    await profile_store.add(old_artifact)

    new_artifact = _artifact(
        MemoryKind.FACT,
        content="用户使用 Sebastian",
        slot_id="test.multi.merge",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.MERGE,
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.MERGE,
        reason="merge-policy slot matched an exact active record",
        old_memory_ids=[old_artifact.id],
        new_memory=new_artifact,
        candidate=_candidate(MemoryKind.FACT),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="test.multi.merge",
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows_by_id = {
        row.id: row for row in (await db_session.scalars(select(ProfileMemoryRecord))).all()
    }
    assert rows_by_id[old_artifact.id].status == MemoryStatus.SUPERSEDED.value
    assert rows_by_id[new_artifact.id].status == MemoryStatus.ACTIVE.value
    assert rows_by_id[new_artifact.id].content == "用户使用 Sebastian"


@pytest.mark.asyncio
async def test_persist_decision_expire_zero_hit_traces_miss(db_session, caplog) -> None:
    """EXPIRE targeting a non-existent memory_id must emit persist.expire_miss trace."""
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    profile_store, episode_store, entity_registry = _stores(db_session)

    decision = ResolveDecision(
        decision=MemoryDecisionType.EXPIRE,
        reason="stale preference",
        old_memory_ids=["does-not-exist"],
        new_memory=None,
        candidate=_candidate(MemoryKind.FACT),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    assert "persist.expire_miss" in caplog.text
    assert "does-not-exist" in caplog.text


@pytest.mark.asyncio
async def test_persist_decision_relation_persists_source(db_session) -> None:
    """Relation candidate record must preserve the artifact's source field."""
    profile_store, episode_store, entity_registry = _stores(db_session)
    artifact = _artifact(
        MemoryKind.RELATION,
        source=MemorySource.INFERRED,
        structured_payload={
            "predicate": "knows",
            "source_entity_id": "owner",
            "target_entity_id": "entity-bob",
        },
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="r",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_candidate(MemoryKind.RELATION),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )

    await persist_decision(
        decision,
        session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
    )

    rows = (await db_session.scalars(select(RelationCandidateRecord))).all()
    assert len(rows) == 1
    assert rows[0].source == MemorySource.INFERRED.value

from __future__ import annotations

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store import models  # noqa: F401 – registers ORM models
from sebastian.store.database import Base


async def _make_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    return async_sessionmaker(engine, expire_on_commit=False)


def _preference_candidate():
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )

    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="以后回答简洁中文",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def _bad_slot_candidate():
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )

    return CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="no.such.slot",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


async def _run(candidates, *, session_id="s1", input_source=None):
    """Helper: run process_candidates with real in-memory DB, return (decisions, factory)."""
    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

    factory = await _make_db_factory()
    async with factory() as db_session:
        decisions = await process_candidates(
            candidates,
            session_id=session_id,
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="test",
            model_name=None,
            rule_version="test_v1",
            input_source=input_source or {"type": "test"},
        )
        await db_session.commit()
    return decisions, factory


@pytest.mark.asyncio
async def test_process_candidates_empty_list_returns_empty() -> None:
    decisions, _ = await _run([])
    assert decisions == []


@pytest.mark.asyncio
async def test_process_candidates_add_persists_profile_record() -> None:
    from sqlalchemy import select

    from sebastian.memory.types import MemoryDecisionType
    from sebastian.store.models import ProfileMemoryRecord

    decisions, factory = await _run([_preference_candidate()])

    assert len(decisions) == 1
    assert decisions[0].decision == MemoryDecisionType.ADD

    async with factory() as db_session:
        rows = (await db_session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].content == "以后回答简洁中文"
    assert rows[0].slot_id == "user.preference.response_style"


@pytest.mark.asyncio
async def test_process_candidates_invalid_slot_discards_with_no_db_record() -> None:
    from sqlalchemy import select

    from sebastian.memory.types import MemoryDecisionType
    from sebastian.store.models import MemoryDecisionLogRecord, ProfileMemoryRecord

    decisions, factory = await _run([_bad_slot_candidate()])

    assert len(decisions) == 1
    assert decisions[0].decision == MemoryDecisionType.DISCARD

    async with factory() as db_session:
        profile_rows = (await db_session.scalars(select(ProfileMemoryRecord))).all()
        log_rows = (await db_session.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(profile_rows) == 0
    assert len(log_rows) == 1
    assert log_rows[0].decision == MemoryDecisionType.DISCARD.value


@pytest.mark.asyncio
async def test_process_candidates_input_source_written_to_decision_log() -> None:
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    src = {"type": "my_worker", "session_id": "sess-99"}
    _, factory = await _run([_preference_candidate()], input_source=src)

    async with factory() as db_session:
        rows = (await db_session.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) == 1
    assert rows[0].input_source["type"] == "my_worker"
    assert rows[0].input_source["session_id"] == "sess-99"


@pytest.mark.asyncio
async def test_process_candidates_does_not_commit(monkeypatch) -> None:
    """process_candidates must NOT call db_session.commit() — caller owns the transaction."""
    from unittest.mock import AsyncMock, patch

    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

    factory = await _make_db_factory()
    async with factory() as db_session:
        commit_calls = []
        original_commit = db_session.commit

        async def spy_commit():
            commit_calls.append(1)
            return await original_commit()

        db_session.commit = spy_commit  # type: ignore[method-assign]

        await process_candidates(
            [_preference_candidate()],
            session_id="s1",
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="test",
            model_name=None,
            rule_version="test_v1",
            input_source={"type": "test"},
        )

    assert commit_calls == [], "process_candidates must not commit — caller owns the transaction"

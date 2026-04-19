from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.decision_log import MemoryDecisionLogger
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
    ResolveDecision,
)
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_candidate() -> CandidateArtifact:
    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="用户偏好简洁中文回复",
        structured_payload={"style": "concise"},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        confidence=0.96,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def _make_memory_artifact(memory_id: str = "mem-new") -> MemoryArtifact:
    return MemoryArtifact(
        id=memory_id,
        kind=MemoryKind.PREFERENCE,
        scope=MemoryScope.USER,
        subject_id="owner",
        slot_id="user.preference.response_style",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        content="用户偏好简洁中文回复",
        structured_payload={"style": "concise"},
        source=MemorySource.EXPLICIT,
        confidence=0.96,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=datetime.now(UTC),
        last_accessed_at=None,
        access_count=0,
        provenance={},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )


async def test_decision_logger_append_add(db_session) -> None:
    logger = MemoryDecisionLogger(db_session)

    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="No existing memory for this slot",
        old_memory_ids=[],
        new_memory=_make_memory_artifact(memory_id="mem-add-1"),
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    record = await logger.append(
        decision,
        worker="unit-test",
        model=None,
        rule_version="v1",
    )

    assert record.decision == "ADD"
    assert record.subject_id == "owner"
    assert record.slot_id == "user.preference.response_style"
    assert record.worker == "unit-test"
    assert record.rule_version == "v1"
    assert record.model is None
    assert record.new_memory_id == "mem-add-1"
    assert record.old_memory_ids == []
    assert record.conflicts == []
    assert isinstance(record.candidate, dict)
    assert record.candidate["content"] == "用户偏好简洁中文回复"
    assert record.candidate["structured_payload"] == {"style": "concise"}
    assert record.id is not None
    assert isinstance(record.created_at, datetime)


async def test_decision_logger_append_supersede(db_session) -> None:
    logger = MemoryDecisionLogger(db_session)

    decision = ResolveDecision(
        decision=MemoryDecisionType.SUPERSEDE,
        reason="New value replaces old preference",
        old_memory_ids=["mem-001", "mem-002"],
        new_memory=_make_memory_artifact(memory_id="mem-new-1"),
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    record = await logger.append(
        decision,
        worker="unit-test",
        model="claude-sonnet-4-6",
        rule_version="v1",
    )

    assert record.decision == "SUPERSEDE"
    assert record.subject_id == "owner"
    assert record.slot_id == "user.preference.response_style"
    assert record.worker == "unit-test"
    assert record.model == "claude-sonnet-4-6"
    assert record.rule_version == "v1"
    assert record.old_memory_ids == ["mem-001", "mem-002"]
    assert record.new_memory_id == "mem-new-1"
    assert record.conflicts == []
    assert isinstance(record.candidate, dict)
    assert record.candidate["content"] == "用户偏好简洁中文回复"

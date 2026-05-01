from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.writing.decision_log import MemoryDecisionLogger
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


async def test_decision_logger_append_add(db_session, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
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
    assert "MEMORY_TRACE decision_log.append" in caplog.text
    assert "decision=ADD" in caplog.text
    assert "worker=unit-test" in caplog.text


async def test_append_captures_session_id_from_provenance(db_session) -> None:
    """session_id flows from decision.new_memory.provenance into the log record."""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    artifact = _make_memory_artifact(memory_id="mem-prov-1")
    artifact = artifact.model_copy(update={"provenance": {"session_id": "sess-xyz"}})
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="ok",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(
        decision,
        worker="unit-test",
        model="claude-opus-4-6",
        rule_version="v1",
    )
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.session_id == "sess-xyz"
    assert row.model == "claude-opus-4-6"


async def test_append_session_id_none_when_no_new_memory(db_session) -> None:
    """DISCARD decision (new_memory=None) leaves session_id column as None."""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    decision = ResolveDecision(
        decision=MemoryDecisionType.DISCARD,
        reason="validate fail",
        old_memory_ids=[],
        new_memory=None,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(
        decision,
        worker="unit-test",
        model=None,
        rule_version="v1",
    )
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.session_id is None
    assert row.model is None


async def test_append_session_id_none_when_provenance_missing_key(db_session) -> None:
    """Provenance dict without session_id key results in None session_id."""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    artifact = _make_memory_artifact(memory_id="mem-prov-2")
    # provenance has some other field but no session_id
    artifact = artifact.model_copy(update={"provenance": {"agent_type": "main"}})
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="ok",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(
        decision,
        worker="unit-test",
        model=None,
        rule_version="v1",
    )
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.session_id is None


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
    assert record.conflicts == ["mem-001", "mem-002"]
    assert isinstance(record.candidate, dict)
    assert record.candidate["content"] == "用户偏好简洁中文回复"


async def test_append_input_source_persisted(db_session) -> None:
    """input_source dict 被持久化到 MemoryDecisionLogRecord.input_source。"""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    artifact = _make_memory_artifact(memory_id="mem-src-1")
    artifact = artifact.model_copy(update={"provenance": {"session_id": "sess-abc"}})
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="ok",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(
        decision,
        worker="unit-test",
        model=None,
        rule_version="v1",
        input_source={"type": "memory_save_tool", "session_id": "sess-abc"},
    )
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.input_source is not None
    assert row.input_source["type"] == "memory_save_tool"
    assert row.input_source["session_id"] == "sess-abc"


async def test_append_input_source_none_by_default(db_session) -> None:
    """不传 input_source 时，record.input_source 应为 None。"""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="ok",
        old_memory_ids=[],
        new_memory=_make_memory_artifact(memory_id="mem-src-2"),
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(decision, worker="unit-test", model=None, rule_version="v1")
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.input_source is None


async def test_append_session_id_from_input_source_when_new_memory_none(db_session) -> None:
    """DISCARD 且 new_memory=None 时，session_id 应从 input_source['session_id'] 取得。"""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    decision = ResolveDecision(
        decision=MemoryDecisionType.DISCARD,
        reason="validate fail",
        old_memory_ids=[],
        new_memory=None,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(
        decision,
        worker="unit-test",
        model=None,
        rule_version="v1",
        input_source={"type": "session_consolidation", "session_id": "sess-fallback"},
    )
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.session_id == "sess-fallback"
    assert row.input_source is not None
    assert row.input_source["session_id"] == "sess-fallback"


async def test_append_session_id_provenance_takes_priority_over_input_source(db_session) -> None:
    """provenance["session_id"] 优先级高于 input_source["session_id"]。"""
    from sqlalchemy import select

    from sebastian.store.models import MemoryDecisionLogRecord

    logger = MemoryDecisionLogger(db_session)

    artifact = _make_memory_artifact(memory_id="mem-prio-1")
    artifact = artifact.model_copy(update={"provenance": {"session_id": "sess-from-provenance"}})
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="ok",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
    )

    await logger.append(
        decision,
        worker="unit-test",
        model=None,
        rule_version="v1",
        input_source={"type": "memory_save_tool", "session_id": "sess-from-input-source"},
    )
    await db_session.commit()

    row = (await db_session.scalars(select(MemoryDecisionLogRecord))).first()
    assert row is not None
    assert row.session_id == "sess-from-provenance"

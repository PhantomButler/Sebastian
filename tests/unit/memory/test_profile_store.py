from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.profile_store import ProfileMemoryStore
from sebastian.memory.types import (
    Cardinality,
    MemoryArtifact,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    ResolutionPolicy,
)
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base
from sebastian.store.models import ProfileMemoryRecord


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_artifact(**overrides: object) -> MemoryArtifact:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": "mem-response-style",
        "kind": MemoryKind.PREFERENCE,
        "scope": MemoryScope.USER,
        "subject_id": "owner",
        "slot_id": "user.preference.response_style",
        "cardinality": Cardinality.SINGLE,
        "resolution_policy": ResolutionPolicy.SUPERSEDE,
        "content": "用户偏好简洁中文回复",
        "structured_payload": {"style": "concise"},
        "source": MemorySource.EXPLICIT,
        "confidence": 0.96,
        "status": MemoryStatus.ACTIVE,
        "valid_from": None,
        "valid_until": None,
        "recorded_at": now,
        "last_accessed_at": None,
        "access_count": 0,
        "provenance": {"session_id": "sess-1"},
        "links": [],
        "embedding_ref": None,
        "dedupe_key": None,
        "policy_tags": [],
    }
    defaults.update(overrides)
    return MemoryArtifact(**defaults)  # type: ignore[arg-type]


def _make_record(**overrides: object) -> ProfileMemoryRecord:
    now = datetime.now(UTC)
    defaults = {
        "id": "mem-direct",
        "subject_id": "owner",
        "scope": MemoryScope.USER.value,
        "slot_id": "user.preference.response_style",
        "kind": MemoryKind.PREFERENCE.value,
        "content": "用户偏好简洁中文回复",
        "structured_payload": {"style": "concise"},
        "source": MemorySource.EXPLICIT.value,
        "confidence": 0.96,
        "status": MemoryStatus.ACTIVE.value,
        "valid_from": None,
        "valid_until": None,
        "provenance": {"session_id": "sess-1"},
        "policy_tags": [],
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": None,
        "access_count": 0,
    }
    defaults.update(overrides)
    return ProfileMemoryRecord(**defaults)


async def test_add_inserts_active_record(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    artifact = _make_artifact()

    record = await store.add(artifact)

    assert record.id == "mem-response-style"
    assert record.content == "用户偏好简洁中文回复"
    assert record.status == MemoryStatus.ACTIVE.value
    assert record.subject_id == "owner"
    assert record.scope == MemoryScope.USER.value
    assert record.slot_id == "user.preference.response_style"


async def test_get_active_by_slot_returns_only_active_unexpired_records(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(id="active", valid_until=None),
            _make_record(id="active-future", valid_until=now + timedelta(days=1)),
            _make_record(id="superseded", status=MemoryStatus.SUPERSEDED.value),
            _make_record(id="expired", valid_until=now - timedelta(days=1)),
            _make_record(id="other-slot", slot_id="user.preference.language"),
        ]
    )
    await db_session.flush()

    records = await store.get_active_by_slot(
        subject_id="owner",
        scope=MemoryScope.USER.value,
        slot_id="user.preference.response_style",
    )

    assert {record.id for record in records} == {"active", "active-future"}
    assert all(record.status == MemoryStatus.ACTIVE.value for record in records)


async def test_supersede_marks_old_records_and_inserts_new_active_record(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    db_session.add_all(
        [
            _make_record(id="old-1"),
            _make_record(id="old-2"),
        ]
    )
    await db_session.flush()

    new_record = await store.supersede(
        ["old-1", "old-2"],
        _make_artifact(id="new-1", content="用户偏好详细说明"),
    )

    old_records = (
        await db_session.scalars(
            select(ProfileMemoryRecord).where(ProfileMemoryRecord.id.in_(["old-1", "old-2"]))
        )
    ).all()
    assert {record.status for record in old_records} == {MemoryStatus.SUPERSEDED.value}
    assert new_record.id == "new-1"
    assert new_record.content == "用户偏好详细说明"
    assert new_record.status == MemoryStatus.ACTIVE.value


async def test_touch_increments_access_count_and_sets_last_accessed_at(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    db_session.add_all(
        [
            _make_record(id="touch-1", access_count=2),
            _make_record(id="touch-2", access_count=0),
        ]
    )
    await db_session.flush()

    await store.touch(["touch-1", "touch-2"])

    records = (
        await db_session.scalars(
            select(ProfileMemoryRecord).where(ProfileMemoryRecord.id.in_(["touch-1", "touch-2"]))
        )
    ).all()
    counts = {record.id: record.access_count for record in records}
    assert counts == {"touch-1": 3, "touch-2": 1}
    assert all(record.last_accessed_at is not None for record in records)


async def test_search_active_filters_by_subject_and_scope_with_limit(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(id="owner-new", subject_id="owner", created_at=now + timedelta(minutes=2)),
            _make_record(id="owner-old", subject_id="owner", created_at=now + timedelta(minutes=1)),
            _make_record(id="guest", subject_id="guest", created_at=now + timedelta(minutes=3)),
            _make_record(
                id="project-scope",
                subject_id="owner",
                scope=MemoryScope.PROJECT.value,
                created_at=now + timedelta(minutes=4),
            ),
            _make_record(id="deleted", subject_id="owner", status=MemoryStatus.DELETED.value),
        ]
    )
    await db_session.flush()

    records = await store.search_active(subject_id="owner", scope=MemoryScope.USER.value, limit=8)

    assert [record.id for record in records] == ["owner-new", "owner-old"]
    assert all(record.subject_id == "owner" for record in records)
    assert all(record.status == MemoryStatus.ACTIVE.value for record in records)

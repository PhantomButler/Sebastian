from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.stores.profile_store import ProfileMemoryStore
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
    from sqlalchemy import text

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
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


async def test_search_active_filters_expired_records(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(id="m-expired", valid_until=now - timedelta(days=1)),
            _make_record(id="m-active", valid_until=None),
        ]
    )
    await db_session.flush()

    rows = await store.search_active(subject_id="owner")
    ids = {r.id for r in rows}
    assert ids == {"m-active"}


async def test_search_recent_context_returns_recent_only(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(id="ctx-recent", created_at=now - timedelta(hours=2)),
            _make_record(id="ctx-old", created_at=now - timedelta(days=30)),
        ]
    )
    await db_session.flush()

    rows = await store.search_recent_context(subject_id="owner", window_days=7)
    ids = {r.id for r in rows}
    assert ids == {"ctx-recent"}


async def test_search_recent_context_respects_limit(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [_make_record(id=f"ctx-{i}", created_at=now - timedelta(hours=i + 1)) for i in range(5)]
    )
    await db_session.flush()

    rows = await store.search_recent_context(subject_id="owner", limit=2)
    assert len(rows) == 2
    # Most recent first (smaller offset → newer)
    assert rows[0].id == "ctx-0"
    assert rows[1].id == "ctx-1"


async def test_search_recent_context_skips_expired(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(
                id="ctx-expired",
                created_at=now - timedelta(hours=2),
                valid_until=now - timedelta(minutes=5),
            ),
            _make_record(
                id="ctx-valid",
                created_at=now - timedelta(hours=3),
                valid_until=None,
            ),
        ]
    )
    await db_session.flush()

    rows = await store.search_recent_context(subject_id="owner")
    ids = {r.id for r in rows}
    assert ids == {"ctx-valid"}


async def test_expire_marks_record_expired(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    original = datetime.now(UTC) - timedelta(days=1)
    db_session.add(_make_record(id="m-old", created_at=original, updated_at=original))
    await db_session.flush()

    await store.expire("m-old")

    record = await db_session.get(ProfileMemoryRecord, "m-old")
    assert record is not None
    assert record.status == MemoryStatus.EXPIRED.value
    # SQLite returns naive datetimes; compare after stripping tz from original.
    assert record.updated_at.replace(tzinfo=None) > original.replace(tzinfo=None)


async def test_search_recent_context_skips_inactive(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(
                id="ctx-superseded",
                created_at=now - timedelta(hours=1),
                status=MemoryStatus.SUPERSEDED.value,
            ),
            _make_record(id="ctx-active", created_at=now - timedelta(hours=2)),
        ]
    )
    await db_session.flush()

    rows = await store.search_recent_context(subject_id="owner")
    ids = {r.id for r in rows}
    assert ids == {"ctx-active"}


# ---------------------------------------------------------------------------
# cardinality / resolution_policy persistence (Step 1)
# ---------------------------------------------------------------------------


async def test_add_persists_cardinality_and_resolution_policy(db_session) -> None:
    """ProfileMemoryStore.add() must persist cardinality and resolution_policy."""
    store = ProfileMemoryStore(db_session)
    artifact = _make_artifact(
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
    )

    record = await store.add(artifact)

    assert record.cardinality == "single"
    assert record.resolution_policy == "supersede"


async def test_add_persists_null_cardinality_and_resolution_policy(db_session) -> None:
    """cardinality and resolution_policy default to None when not supplied."""
    store = ProfileMemoryStore(db_session)
    artifact = _make_artifact(cardinality=None, resolution_policy=None)

    record = await store.add(artifact)

    assert record.cardinality is None
    assert record.resolution_policy is None


async def test_add_persists_multi_cardinality_append_only_policy(db_session) -> None:
    """MULTI cardinality and APPEND_ONLY resolution_policy are stored correctly."""
    store = ProfileMemoryStore(db_session)
    artifact = _make_artifact(
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
    )

    record = await store.add(artifact)

    assert record.cardinality == "multi"
    assert record.resolution_policy == "append_only"


# ---------------------------------------------------------------------------
# valid_from future filtering tests (Step 1: these should fail before fix)
# ---------------------------------------------------------------------------


async def test_search_active_excludes_valid_from_future(db_session) -> None:
    """search_active must not return records whose valid_from is in the future."""
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(id="vf-now", valid_from=now - timedelta(hours=1)),
            _make_record(id="vf-none", valid_from=None),
            _make_record(id="vf-future", valid_from=now + timedelta(days=1)),
        ]
    )
    await db_session.flush()

    rows = await store.search_active(subject_id="owner")
    ids = {r.id for r in rows}
    assert "vf-future" not in ids
    assert {"vf-now", "vf-none"} <= ids


async def test_get_active_by_slot_excludes_valid_from_future(db_session) -> None:
    """get_active_by_slot must not return records whose valid_from is in the future."""
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(id="slot-past", valid_from=now - timedelta(hours=1)),
            _make_record(id="slot-none", valid_from=None),
            _make_record(id="slot-future", valid_from=now + timedelta(days=1)),
        ]
    )
    await db_session.flush()

    rows = await store.get_active_by_slot(
        subject_id="owner",
        scope=MemoryScope.USER.value,
        slot_id="user.preference.response_style",
    )
    ids = {r.id for r in rows}
    assert "slot-future" not in ids
    assert {"slot-past", "slot-none"} <= ids


async def test_search_recent_context_excludes_valid_from_future(db_session) -> None:
    """search_recent_context must not return records whose valid_from is in the future."""
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_record(
                id="ctx-vf-past",
                created_at=now - timedelta(hours=1),
                valid_from=now - timedelta(hours=2),
            ),
            _make_record(
                id="ctx-vf-none",
                created_at=now - timedelta(hours=2),
                valid_from=None,
            ),
            _make_record(
                id="ctx-vf-future",
                created_at=now - timedelta(hours=3),
                valid_from=now + timedelta(days=1),
            ),
        ]
    )
    await db_session.flush()

    rows = await store.search_recent_context(subject_id="owner")
    ids = {r.id for r in rows}
    assert "ctx-vf-future" not in ids
    assert {"ctx-vf-past", "ctx-vf-none"} <= ids


# ---------------------------------------------------------------------------
# find_active_exact (Task 6)
# ---------------------------------------------------------------------------


async def test_find_active_exact_returns_matching_record(db_session) -> None:
    """find_active_exact returns a record when subject/scope/slot/kind/content all match."""
    store = ProfileMemoryStore(db_session)
    db_session.add(
        _make_record(
            id="exact-1",
            subject_id="user:owner",
            scope=MemoryScope.USER.value,
            slot_id="test.multi.merge",
            kind=MemoryKind.FACT.value,
            content="用户使用 Sebastian",
            status=MemoryStatus.ACTIVE.value,
        )
    )
    await db_session.flush()

    result = await store.find_active_exact(
        subject_id="user:owner",
        scope=MemoryScope.USER.value,
        slot_id="test.multi.merge",
        kind=MemoryKind.FACT.value,
        content="用户使用 Sebastian",
    )

    assert result is not None
    assert result.id == "exact-1"


async def test_find_active_exact_returns_none_for_different_content(db_session) -> None:
    """find_active_exact returns None when content does not match."""
    store = ProfileMemoryStore(db_session)
    db_session.add(
        _make_record(
            id="exact-2",
            subject_id="user:owner",
            scope=MemoryScope.USER.value,
            slot_id="test.multi.merge",
            kind=MemoryKind.FACT.value,
            content="用户使用 Sebastian",
            status=MemoryStatus.ACTIVE.value,
        )
    )
    await db_session.flush()

    result = await store.find_active_exact(
        subject_id="user:owner",
        scope=MemoryScope.USER.value,
        slot_id="test.multi.merge",
        kind=MemoryKind.FACT.value,
        content="完全不同的内容",
    )

    assert result is None


@pytest.fixture
async def fts_db_session():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_recent_context_is_query_aware(fts_db_session) -> None:
    store = ProfileMemoryStore(fts_db_session)

    project_artifact = _make_artifact(
        id="mem-project",
        slot_id="user.current_project_focus",
        kind=MemoryKind.FACT,
        content="当前专注 Sebastian 项目的记忆模块",
        confidence=0.9,
    )
    other_artifact = _make_artifact(
        id="mem-timezone",
        slot_id="user.profile.timezone",
        kind=MemoryKind.FACT,
        content="用户所在时区为 Asia/Shanghai",
        confidence=0.95,
    )
    await store.add(project_artifact)
    await store.add(other_artifact)

    results = await store.search_recent_context(
        subject_id="owner",
        query="记忆模块",
        limit=5,
    )
    assert len(results) >= 1
    assert results[0].id == "mem-project"
    assert all(r.id != "mem-timezone" for r in results)


async def test_find_active_exact_ignores_superseded_record(db_session) -> None:
    """find_active_exact returns None when the matching record is superseded."""
    store = ProfileMemoryStore(db_session)
    db_session.add(
        _make_record(
            id="exact-superseded",
            subject_id="user:owner",
            scope=MemoryScope.USER.value,
            slot_id="test.multi.merge",
            kind=MemoryKind.FACT.value,
            content="用户使用 Sebastian",
            status=MemoryStatus.SUPERSEDED.value,
        )
    )
    await db_session.flush()

    result = await store.find_active_exact(
        subject_id="user:owner",
        scope=MemoryScope.USER.value,
        slot_id="test.multi.merge",
        kind=MemoryKind.FACT.value,
        content="用户使用 Sebastian",
    )

    assert result is None


async def test_search_active_returns_high_confidence_first(db_session) -> None:
    """search_active must sort by confidence.desc() before created_at.desc()."""
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)

    # Newer, but low confidence
    db_session.add(
        _make_record(
            id="mem-low-conf",
            slot_id="user.preference.language",
            confidence=0.4,
            created_at=now,
            updated_at=now,
        )
    )
    # Older, but high confidence
    db_session.add(
        _make_record(
            id="mem-high-conf",
            slot_id="user.preference.response_style",
            confidence=0.95,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )
    )
    await db_session.flush()

    results = await store.search_active(subject_id="owner", limit=10)
    ids = [r.id for r in results]
    assert ids.index("mem-high-conf") < ids.index("mem-low-conf"), (
        f"Expected high-conf first, got order: {ids}"
    )


async def test_expire_nonexistent_returns_zero(db_session) -> None:
    """expire() on a non-existent id must return 0."""
    store = ProfileMemoryStore(db_session)
    rowcount = await store.expire("does-not-exist")
    assert rowcount == 0


async def test_expire_existing_returns_one(db_session) -> None:
    """expire() on an existing active record must return 1 and set status=expired."""
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)
    db_session.add(_make_record(id="mem-expire-rc", created_at=now, updated_at=now))
    await db_session.flush()

    rowcount = await store.expire("mem-expire-rc")
    assert rowcount == 1

    record = await db_session.get(ProfileMemoryRecord, "mem-expire-rc")
    assert record is not None
    assert record.status == MemoryStatus.EXPIRED.value

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.entity_registry import EntityRegistry
from sebastian.memory.types import MemoryStatus
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base
from sebastian.store.models import RelationCandidateRecord


def _make_relation(
    *,
    subject_id: str = "owner",
    status: str = MemoryStatus.ACTIVE.value,
    content: str = "妻子喜欢做饭",
    created_at: datetime | None = None,
    predicate: str = "likes",
) -> RelationCandidateRecord:
    return RelationCandidateRecord(
        id=str(uuid4()),
        subject_id=subject_id,
        predicate=predicate,
        source_entity_id=None,
        target_entity_id=None,
        content=content,
        structured_payload={},
        confidence=0.9,
        status=status,
        provenance={},
        created_at=created_at or datetime.now(UTC),
    )


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_upsert_entity_creates_with_correct_fields(db_session) -> None:
    registry = EntityRegistry(db_session)

    record = await registry.upsert_entity("小橘", "pet", aliases=["橘猫"])
    await db_session.flush()

    assert record.canonical_name == "小橘"
    assert record.entity_type == "pet"
    assert "橘猫" in record.aliases
    assert record.id is not None
    assert isinstance(record.created_at, datetime)
    assert isinstance(record.updated_at, datetime)


async def test_upsert_entity_merges_aliases_without_duplicates(db_session) -> None:
    registry = EntityRegistry(db_session)

    await registry.upsert_entity("小橘", "pet", aliases=["橘猫"])
    await db_session.flush()

    # Re-upsert with overlapping and new alias
    record = await registry.upsert_entity("小橘", "pet", aliases=["橘猫", "小橘子"])
    await db_session.flush()

    assert record.canonical_name == "小橘"
    # aliases must contain both, with no duplicates
    assert sorted(record.aliases) == ["小橘子", "橘猫"]
    assert len(record.aliases) == len(set(record.aliases))


async def test_lookup_by_canonical_name(db_session) -> None:
    registry = EntityRegistry(db_session)

    await registry.upsert_entity("小橘", "pet", aliases=["橘猫"])
    await db_session.flush()

    results = await registry.lookup("小橘")

    assert len(results) == 1
    assert results[0].canonical_name == "小橘"


async def test_lookup_by_alias(db_session) -> None:
    registry = EntityRegistry(db_session)

    await registry.upsert_entity("小橘", "pet", aliases=["橘猫"])
    await db_session.flush()

    results = await registry.lookup("橘猫")

    assert len(results) == 1
    assert results[0].canonical_name == "小橘"


async def test_lookup_returns_empty_for_unknown_term(db_session) -> None:
    registry = EntityRegistry(db_session)

    results = await registry.lookup("不存在的实体")

    assert results == []


async def test_sync_jieba_terms_calls_add_entity_terms(db_session) -> None:
    registry = EntityRegistry(db_session)

    await registry.upsert_entity("小橘", "pet", aliases=["橘猫", "小橘子"])
    await db_session.flush()

    with patch("sebastian.memory.entity_registry.add_entity_terms") as mock_add:
        await registry.sync_jieba_terms()

    mock_add.assert_called_once()
    terms_passed = set(mock_add.call_args[0][0])
    assert "小橘" in terms_passed
    assert "橘猫" in terms_passed
    assert "小橘子" in terms_passed


# ---------------------------------------------------------------------------
# list_relations — Phase R-D Task D3
# ---------------------------------------------------------------------------


async def test_list_relations_returns_active_only(db_session) -> None:
    active = _make_relation(subject_id="owner", status=MemoryStatus.ACTIVE.value)
    superseded = _make_relation(
        subject_id="owner",
        status=MemoryStatus.SUPERSEDED.value,
        content="旧的关系",
    )
    db_session.add_all([active, superseded])
    await db_session.flush()

    registry = EntityRegistry(db_session)
    results = await registry.list_relations(subject_id="owner")

    assert len(results) == 1
    assert results[0].id == active.id
    assert results[0].status == MemoryStatus.ACTIVE.value


async def test_list_relations_respects_subject_filter(db_session) -> None:
    owner_rel = _make_relation(subject_id="owner", content="主人的关系")
    agent_rel = _make_relation(subject_id="agent:foo", content="Agent 的关系")
    db_session.add_all([owner_rel, agent_rel])
    await db_session.flush()

    registry = EntityRegistry(db_session)
    results = await registry.list_relations(subject_id="owner")

    assert len(results) == 1
    assert results[0].subject_id == "owner"


async def test_list_relations_respects_limit(db_session) -> None:
    base = datetime.now(UTC)
    relations = [
        _make_relation(
            subject_id="owner",
            content=f"关系-{i}",
            created_at=base + timedelta(seconds=i),
        )
        for i in range(5)
    ]
    db_session.add_all(relations)
    await db_session.flush()

    registry = EntityRegistry(db_session)
    results = await registry.list_relations(subject_id="owner", limit=2)

    assert len(results) == 2


async def test_list_relations_orders_by_created_at_desc(db_session) -> None:
    base = datetime.now(UTC)
    oldest = _make_relation(
        subject_id="owner", content="老", created_at=base - timedelta(hours=2)
    )
    middle = _make_relation(
        subject_id="owner", content="中", created_at=base - timedelta(hours=1)
    )
    newest = _make_relation(subject_id="owner", content="新", created_at=base)
    db_session.add_all([oldest, middle, newest])
    await db_session.flush()

    registry = EntityRegistry(db_session)
    results = await registry.list_relations(subject_id="owner", limit=5)

    assert [r.id for r in results] == [newest.id, middle.id, oldest.id]

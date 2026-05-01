from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.stores.entity_registry import EntityRegistry
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.startup import init_memory_storage, seed_builtin_slots
from sebastian.store.models import Base, EntityRecord, MemorySlotRecord


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def db_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_init_memory_storage_creates_fts_table(engine):
    await init_memory_storage(engine)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='episode_memories_fts'"
            )
        )
        assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_init_memory_storage_is_idempotent(engine):
    await init_memory_storage(engine)
    await init_memory_storage(engine)  # must not raise


@pytest.mark.asyncio
async def test_startup_seeds_builtin_slots(db_factory) -> None:
    async with db_factory() as session:
        await seed_builtin_slots(session)

    expected_ids = {s.slot_id for s in DEFAULT_SLOT_REGISTRY.list_all()}
    assert len(expected_ids) >= 6

    async with db_factory() as session:
        rows = (await session.execute(select(MemorySlotRecord))).scalars().all()

    assert {row.slot_id for row in rows} == expected_ids
    assert all(row.is_builtin is True for row in rows)


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_factory) -> None:
    async with db_factory() as session:
        await seed_builtin_slots(session)

    async with db_factory() as session:
        await seed_builtin_slots(session)

    async with db_factory() as session:
        rows = (await session.execute(select(MemorySlotRecord))).scalars().all()

    assert len(rows) == len(DEFAULT_SLOT_REGISTRY.list_all())


@pytest.mark.asyncio
async def test_sync_jieba_loads_aliases_from_db(db_factory) -> None:
    now = datetime.now(UTC)
    async with db_factory() as session:
        session.add(
            EntityRecord(
                id=str(uuid4()),
                canonical_name="小橘",
                entity_type="pet",
                aliases=["橘猫", "橘子精灵"],
                entity_metadata={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with db_factory() as session:
        registry = EntityRegistry(session)
        await registry.sync_jieba_terms()

    import jieba

    tokens = list(jieba.cut_for_search("橘子精灵"))
    assert "橘子精灵" in tokens

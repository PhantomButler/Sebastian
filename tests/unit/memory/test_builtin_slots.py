from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.slots import _BUILTIN_SLOTS
from sebastian.memory.startup import seed_builtin_slots
from sebastian.store.models import Base, MemorySlotRecord


def test_builtin_slot_count() -> None:
    assert len(_BUILTIN_SLOTS) == 10  # 原 6 + 新 3 + user.preference.addressing


def test_new_seed_slots_present() -> None:
    ids = {s.slot_id for s in _BUILTIN_SLOTS}
    assert "user.profile.name" in ids
    assert "user.profile.location" in ids
    assert "user.profile.occupation" in ids


@pytest.mark.asyncio
async def test_seed_writes_all_10_slots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_builtin_slots(session)
    async with factory() as session:
        result = await session.execute(select(MemorySlotRecord))
        ids = {row.slot_id for row in result.scalars().all()}
    assert {"user.profile.name", "user.profile.location", "user.profile.occupation"} <= ids
    assert len(ids) == 10

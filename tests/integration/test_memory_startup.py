from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sebastian.memory.startup import init_memory_storage
from sebastian.store.models import Base


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_init_memory_storage_creates_fts_table(engine):
    await init_memory_storage(engine)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name='episode_memories_fts'"
            )
        )
        assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_init_memory_storage_is_idempotent(engine):
    await init_memory_storage(engine)
    await init_memory_storage(engine)  # must not raise

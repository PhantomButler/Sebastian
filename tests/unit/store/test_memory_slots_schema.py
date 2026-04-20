from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from sebastian.store.database import _apply_idempotent_migrations
from sebastian.store.models import Base


@pytest.mark.asyncio
async def test_memory_slots_has_new_columns_after_migration() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
        result = await conn.exec_driver_sql("PRAGMA table_info(memory_slots)")
        columns = {row[1] for row in result.fetchall()}
    assert "proposed_by" in columns
    assert "proposed_in_session" in columns


@pytest.mark.asyncio
async def test_migration_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
        await _apply_idempotent_migrations(conn)  # 二次调用不应抛
        result = await conn.exec_driver_sql("PRAGMA table_info(memory_slots)")
        columns = [row[1] for row in result.fetchall()]
    assert columns.count("proposed_by") == 1

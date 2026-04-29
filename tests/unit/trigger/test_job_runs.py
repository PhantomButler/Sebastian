from __future__ import annotations

import asyncio

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def db_factory():
    import sebastian.store.models  # noqa: F401 — registers all ORM classes into Base.metadata
    from sebastian.store.database import Base, _apply_idempotent_migrations

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


async def test_scheduled_job_runs_table_exists(db_factory):
    async with db_factory() as session:
        rows = await session.execute(
            sqlalchemy.text("PRAGMA table_info(scheduled_job_runs)")
        )
        columns = {row[1] for row in rows.fetchall()}
    assert {"id", "job_id", "status", "started_at", "finished_at", "duration_ms", "error"}.issubset(
        columns
    )

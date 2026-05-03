from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.models import ScheduledJobRunRecord
from sebastian.trigger.job_runs import ScheduledJobRunStore


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
        rows = await session.execute(sqlalchemy.text("PRAGMA table_info(scheduled_job_runs)"))
        columns = {row[1] for row in rows.fetchall()}
    assert {"id", "job_id", "status", "started_at", "finished_at", "duration_ms", "error"}.issubset(
        columns
    )


@pytest.fixture
async def run_store(db_factory):
    return ScheduledJobRunStore(db_factory)


async def test_start_run_writes_running_record(run_store, db_factory):
    started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    run_id = await run_store.start_run("test.job", started_at)

    async with db_factory() as session:
        record = await session.get(ScheduledJobRunRecord, run_id)

    assert record is not None
    assert record.job_id == "test.job"
    assert record.status == "running"
    assert record.started_at == started_at
    assert record.finished_at is None
    assert record.duration_ms is None
    assert record.error is None


async def test_finish_run_updates_to_success(run_store, db_factory):
    started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    finished_at = datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC)
    run_id = await run_store.start_run("test.job", started_at)
    await run_store.finish_run(run_id, "success", finished_at, duration_ms=5000)

    async with db_factory() as session:
        record = await session.get(ScheduledJobRunRecord, run_id)

    assert record.status == "success"
    assert record.finished_at == finished_at
    assert record.duration_ms == 5000
    assert record.error is None


async def test_finish_run_stores_error_message(run_store, db_factory):
    started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    finished_at = datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC)
    run_id = await run_store.start_run("test.job", started_at)
    await run_store.finish_run(run_id, "failed", finished_at, duration_ms=1000, error="oops")

    async with db_factory() as session:
        record = await session.get(ScheduledJobRunRecord, run_id)

    assert record.status == "failed"
    assert record.error == "oops"


async def test_record_skipped_writes_complete_record(run_store, db_factory):
    at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    await run_store.record_skipped("test.job", at, reason="previous run still in progress")

    async with db_factory() as session:
        result = await session.execute(
            select(ScheduledJobRunRecord).where(ScheduledJobRunRecord.job_id == "test.job")
        )
        record = result.scalar_one()

    assert record.status == "skipped"
    assert record.started_at == at
    assert record.finished_at == at
    assert record.duration_ms == 0
    assert record.error == "previous run still in progress"


async def test_get_last_success_at_returns_most_recently_finished(run_store) -> None:
    # Run A: started early, finished late (long-running)
    run_a = await run_store.start_run("test.job", datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC))
    # Run B: started after A, finished before A (fast)
    run_b = await run_store.start_run("test.job", datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC))
    run_b_end = datetime(2024, 1, 1, 9, 5, 0, tzinfo=UTC)
    await run_store.finish_run(run_b, "success", run_b_end, duration_ms=300000)
    # A finishes last (later finished_at than B)
    run_a_end = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    await run_store.finish_run(run_a, "success", run_a_end, duration_ms=7200000)

    result = await run_store.get_last_success_at("test.job")
    # Should return run A's finished_at (most recently finished), not run B's
    assert result == run_a_end


async def test_get_last_success_at_falls_back_to_started_at_for_legacy_success(
    run_store, db_factory
) -> None:
    legacy_started_at = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
    async with db_factory() as session:
        async with session.begin():
            session.add(
                ScheduledJobRunRecord(
                    id="legacy-success",
                    job_id="test.job",
                    status="success",
                    started_at=legacy_started_at,
                    finished_at=None,
                )
            )

    result = await run_store.get_last_success_at("test.job")

    assert result == legacy_started_at


async def test_get_last_success_at_ignores_running_failed_timeout(run_store):
    t_success_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    t_success_end = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    t_stale_start = datetime(2024, 1, 1, 16, 0, 0, tzinfo=UTC)

    run1 = await run_store.start_run("test.job", t_success_start)
    await run_store.finish_run(run1, "success", t_success_end, duration_ms=300000)

    # Stale running row (simulates crash — never finished)
    await run_store.start_run("test.job", t_stale_start)

    result = await run_store.get_last_success_at("test.job")
    assert result == t_success_end


async def test_get_last_success_at_returns_none_when_no_history(run_store):
    result = await run_store.get_last_success_at("nonexistent.job")
    assert result is None


async def test_finish_run_with_unknown_run_id_does_not_raise(run_store):
    # Non-existent run_id: finish_run logs a warning and returns silently
    finished_at = datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC)
    await run_store.finish_run("nonexistent-id", "success", finished_at, duration_ms=0)
    # No exception raised — method is a no-op for unknown IDs


async def test_get_last_success_at_returns_aware_datetime(run_store):
    t_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    t_end = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    run_id = await run_store.start_run("test.job", t_start)
    await run_store.finish_run(run_id, "success", t_end, duration_ms=0)

    result = await run_store.get_last_success_at("test.job")
    assert result is not None
    assert result.tzinfo is not None  # must be timezone-aware

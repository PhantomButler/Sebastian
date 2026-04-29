from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.models import ScheduledJobRunRecord
from sebastian.trigger.job_runs import ScheduledJobRunStore
from sebastian.trigger.scheduler import JobRegistry, ScheduledJob, SchedulerRunner


async def _noop() -> None:
    pass


def test_job_registry_register_and_list() -> None:
    registry = JobRegistry()
    job = ScheduledJob(id="test.job", handler=_noop, interval=timedelta(hours=1))
    registry.register(job)
    assert len(registry.list_jobs()) == 1
    assert registry.list_jobs()[0].id == "test.job"


def test_job_registry_rejects_duplicate_id() -> None:
    registry = JobRegistry()
    job = ScheduledJob(id="test.job", handler=_noop, interval=timedelta(hours=1))
    registry.register(job)
    with pytest.raises(ValueError, match="Duplicate job id"):
        registry.register(ScheduledJob(id="test.job", handler=_noop, interval=timedelta(hours=2)))


def test_job_registry_list_returns_copy() -> None:
    registry = JobRegistry()
    registry.register(ScheduledJob(id="a", handler=_noop, interval=timedelta(hours=1)))
    snapshot = registry.list_jobs()
    registry.register(ScheduledJob(id="b", handler=_noop, interval=timedelta(hours=1)))
    assert len(snapshot) == 1  # original snapshot unchanged


def test_scheduled_job_defaults() -> None:
    job = ScheduledJob(id="x", handler=_noop, interval=timedelta(hours=6))
    assert job.run_on_startup is False
    assert job.startup_delay == timedelta(seconds=30)
    assert job.timeout_seconds == 300
    assert job.concurrency_policy == "skip_if_running"


@pytest.fixture
async def scheduler_db():
    import sebastian.store.models  # noqa: F401
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


# --- _compute_initial_next_run (pure logic, no DB) ---


def test_compute_uses_last_success_plus_interval() -> None:
    job = ScheduledJob(id="j", handler=_noop, interval=timedelta(hours=6))
    last_success = datetime(2024, 1, 1, 6, 0, 0, tzinfo=UTC)
    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)  # 4h after last success (not yet due)
    result = SchedulerRunner._compute_initial_next_run(job, last_success, now)
    assert result == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)  # last_success + 6h


def test_compute_clamps_overdue_to_now_plus_startup_delay() -> None:
    job = ScheduledJob(
        id="j", handler=_noop, interval=timedelta(hours=6), startup_delay=timedelta(minutes=5)
    )
    last_success = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)  # 10h later — job was due 4h ago
    result = SchedulerRunner._compute_initial_next_run(job, last_success, now)
    assert result == datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)  # now + startup_delay


def test_compute_no_history_run_on_startup() -> None:
    job = ScheduledJob(
        id="j",
        handler=_noop,
        interval=timedelta(hours=6),
        run_on_startup=True,
        startup_delay=timedelta(seconds=30),
    )
    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    result = SchedulerRunner._compute_initial_next_run(job, None, now)
    assert result == datetime(2024, 1, 1, 10, 0, 30, tzinfo=UTC)


def test_compute_no_history_no_startup() -> None:
    job = ScheduledJob(id="j", handler=_noop, interval=timedelta(hours=6), run_on_startup=False)
    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    result = SchedulerRunner._compute_initial_next_run(job, None, now)
    assert result == datetime(2024, 1, 1, 16, 0, 0, tzinfo=UTC)  # now + 6h


# --- _tick and _run_job (require DB) ---


async def test_tick_runs_handler_when_due(scheduler_db) -> None:
    called: list[int] = []

    async def handler() -> None:
        called.append(1)

    job = ScheduledJob(id="test.job", handler=handler, interval=timedelta(hours=1))
    registry = JobRegistry()
    registry.register(job)
    run_store = ScheduledJobRunStore(scheduler_db)
    runner = SchedulerRunner(registry=registry, run_store=run_store)

    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    runner._next_run["test.job"] = now  # force due immediately

    await runner._tick(now)
    task = runner._running.get("test.job")
    assert task is not None
    await task  # wait for _run_job to complete

    assert len(called) == 1
    assert await run_store.get_last_success_at("test.job") is not None


async def test_tick_does_not_run_when_not_due(scheduler_db) -> None:
    called: list[int] = []

    async def handler() -> None:
        called.append(1)

    job = ScheduledJob(id="test.job", handler=handler, interval=timedelta(hours=1))
    registry = JobRegistry()
    registry.register(job)
    runner = SchedulerRunner(registry=registry, run_store=ScheduledJobRunStore(scheduler_db))

    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    runner._next_run["test.job"] = now + timedelta(seconds=1)  # not yet due

    await runner._tick(now)
    assert "test.job" not in runner._running
    assert len(called) == 0


async def test_tick_records_skipped_when_job_still_running(scheduler_db) -> None:
    gate = asyncio.Event()

    async def slow_handler() -> None:
        await gate.wait()

    job = ScheduledJob(id="test.slow", handler=slow_handler, interval=timedelta(hours=1))
    registry = JobRegistry()
    registry.register(job)
    run_store = ScheduledJobRunStore(scheduler_db)
    runner = SchedulerRunner(registry=registry, run_store=run_store)

    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    runner._next_run["test.slow"] = now

    # First tick: starts the job (task created but not yet running due to asyncio scheduling)
    await runner._tick(now)
    assert not runner._running["test.slow"].done()

    # Second tick: job still running → should record skipped
    runner._next_run["test.slow"] = now
    await runner._tick(now)

    async with scheduler_db() as session:
        async with session.begin():
            result = await session.execute(
                select(ScheduledJobRunRecord).where(
                    ScheduledJobRunRecord.job_id == "test.slow",
                    ScheduledJobRunRecord.status == "skipped",
                )
            )
            assert result.first() is not None

    # Cleanup: release the slow handler and wait for it to finish
    gate.set()
    await runner._running["test.slow"]


async def test_run_job_writes_success_record(scheduler_db) -> None:
    job = ScheduledJob(id="test.job", handler=_noop, interval=timedelta(hours=1))
    registry = JobRegistry()
    registry.register(job)
    run_store = ScheduledJobRunStore(scheduler_db)
    runner = SchedulerRunner(registry=registry, run_store=run_store)

    await runner._run_job(job)

    last_success = await run_store.get_last_success_at("test.job")
    assert last_success is not None


async def test_run_job_writes_failed_record_on_exception(scheduler_db) -> None:
    async def failing() -> None:
        raise ValueError("boom")

    job = ScheduledJob(id="test.job", handler=failing, interval=timedelta(hours=1))
    registry = JobRegistry()
    registry.register(job)
    run_store = ScheduledJobRunStore(scheduler_db)
    runner = SchedulerRunner(registry=registry, run_store=run_store)

    await runner._run_job(job)

    async with scheduler_db() as session:
        async with session.begin():
            result = await session.execute(
                select(ScheduledJobRunRecord).where(
                    ScheduledJobRunRecord.job_id == "test.job",
                    ScheduledJobRunRecord.status == "failed",
                )
            )
            record = result.scalar_one()
    assert record.error == "boom"
    assert await run_store.get_last_success_at("test.job") is None


async def test_run_job_writes_timeout_record(scheduler_db) -> None:
    async def slow() -> None:
        await asyncio.sleep(10)

    job = ScheduledJob(
        id="test.job", handler=slow, interval=timedelta(hours=1), timeout_seconds=0.01
    )
    registry = JobRegistry()
    registry.register(job)
    runner = SchedulerRunner(registry=registry, run_store=ScheduledJobRunStore(scheduler_db))

    await runner._run_job(job)

    async with scheduler_db() as session:
        async with session.begin():
            result = await session.execute(
                select(ScheduledJobRunRecord).where(
                    ScheduledJobRunRecord.job_id == "test.job",
                    ScheduledJobRunRecord.status == "timeout",
                )
            )
            assert result.first() is not None


async def test_aclose_sets_shutdown_and_cancels_loop(scheduler_db) -> None:
    registry = JobRegistry()
    runner = SchedulerRunner(
        registry=registry,
        run_store=ScheduledJobRunStore(scheduler_db),
        poll_interval=timedelta(milliseconds=10),
    )
    await runner.start()
    assert runner._loop_task is not None
    assert not runner._loop_task.done()

    await runner.aclose()

    assert runner._shutdown is True
    assert runner._loop_task.done()


async def test_run_job_writes_cancelled_record_on_cancel(scheduler_db) -> None:
    handler_started = asyncio.Event()
    gate = asyncio.Event()

    async def blocking() -> None:
        handler_started.set()
        await gate.wait()

    job = ScheduledJob(id="test.cancel", handler=blocking, interval=timedelta(hours=1))
    registry = JobRegistry()
    registry.register(job)
    run_store = ScheduledJobRunStore(scheduler_db)
    runner = SchedulerRunner(registry=registry, run_store=run_store)

    task = asyncio.create_task(runner._run_job(job))
    # Wait until the handler is actually running (start_run already wrote to DB)
    await handler_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with scheduler_db() as session:
        async with session.begin():
            result = await session.execute(
                select(ScheduledJobRunRecord).where(
                    ScheduledJobRunRecord.job_id == "test.cancel",
                    ScheduledJobRunRecord.status == "cancelled",
                )
            )
            assert result.first() is not None

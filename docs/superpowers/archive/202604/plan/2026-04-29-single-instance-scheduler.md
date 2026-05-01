# Single-Instance Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single-instance async background job scheduler that runs `attachments.cleanup` every 6 hours and persists run history to SQLite for crash-safe restart recovery.

**Architecture:** In-memory job definitions (`ScheduledJob` + `JobRegistry`) live in `trigger/scheduler.py`; a poll-based `SchedulerRunner` checks due jobs every 30 s and dispatches asyncio tasks; run history is stored in the new `scheduled_job_runs` SQLite table via `ScheduledJobRunStore` (`trigger/job_runs.py`); `trigger/jobs.py` registers all builtin jobs; gateway lifespan starts and stops the runner, always before `get_engine().dispose()`.

**Tech Stack:** Python 3.12+, SQLAlchemy async ORM, asyncio, aiosqlite, python-ulid (already in `pyproject.toml`).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `sebastian/store/models.py` | Modify | Add `ScheduledJobRunRecord` ORM model |
| `sebastian/trigger/scheduler.py` | Create | `ScheduledJob`, `JobRegistry`, `SchedulerRunner` |
| `sebastian/trigger/job_runs.py` | Create | `ScheduledJobRunStore` – DB reads/writes for run history |
| `sebastian/trigger/jobs.py` | Create | `register_builtin_jobs(registry, *, attachment_store)` |
| `sebastian/gateway/state.py` | Modify | Add `scheduler: SchedulerRunner \| None = None` |
| `sebastian/gateway/app.py` | Modify | Lifespan: create/start/close scheduler |
| `sebastian/trigger/README.md` | Modify | Update from placeholder to actual module docs |
| `sebastian/store/README.md` | Modify | Add `scheduled_job_runs` table entry |
| `tests/unit/trigger/__init__.py` | Create | Empty, makes directory a test package |
| `tests/unit/trigger/test_job_runs.py` | Create | Unit tests for `ScheduledJobRunStore` |
| `tests/unit/trigger/test_scheduler.py` | Create | Unit tests for `JobRegistry` + `SchedulerRunner` |
| `tests/integration/test_scheduler_lifecycle.py` | Create | Integration: full scheduler → DB → restart recovery |

---

## Task 1: `ScheduledJobRunRecord` ORM model

**Files:**
- Modify: `sebastian/store/models.py`
- Test: `tests/unit/trigger/test_job_runs.py` (first test only — table exists check)
- Create: `tests/unit/trigger/__init__.py`

- [ ] **Step 1: Create the test package and write the failing table-existence test**

Create `tests/unit/trigger/__init__.py` as an empty file, then write `tests/unit/trigger/test_job_runs.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /path/to/sebastian
pytest tests/unit/trigger/test_job_runs.py::test_scheduled_job_runs_table_exists -v
```

Expected: FAIL — `no such table: scheduled_job_runs`

- [ ] **Step 3: Add `ScheduledJobRunRecord` to `sebastian/store/models.py`**

Append this class at the end of `models.py` (after `AttachmentRecord`). The imports `Integer, String, Text, Index, DateTime` are already present in the file; no new imports needed.

```python
class ScheduledJobRunRecord(Base):
    __tablename__ = "scheduled_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_scheduled_job_runs_job_status_started", "job_id", "status", "started_at"),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/unit/trigger/test_job_runs.py::test_scheduled_job_runs_table_exists -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/models.py tests/unit/trigger/__init__.py tests/unit/trigger/test_job_runs.py
git commit -m "feat(trigger): add ScheduledJobRunRecord ORM model

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: `ScheduledJobRunStore`

**Files:**
- Create: `sebastian/trigger/job_runs.py`
- Modify: `tests/unit/trigger/test_job_runs.py` (add 6 more tests)

- [ ] **Step 1: Write all failing tests for `ScheduledJobRunStore`**

Append to `tests/unit/trigger/test_job_runs.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import select

from sebastian.store.models import ScheduledJobRunRecord
from sebastian.trigger.job_runs import ScheduledJobRunStore


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


async def test_get_last_success_at_returns_most_recent_finished_at(run_store):
    t1_start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    t1_end = datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
    t2_start = datetime(2024, 1, 1, 16, 0, 0, tzinfo=UTC)
    t2_end = datetime(2024, 1, 1, 16, 5, 0, tzinfo=UTC)

    run1 = await run_store.start_run("test.job", t1_start)
    await run_store.finish_run(run1, "success", t1_end, duration_ms=300000)

    run2 = await run_store.start_run("test.job", t2_start)
    await run_store.finish_run(run2, "success", t2_end, duration_ms=300000)

    result = await run_store.get_last_success_at("test.job")
    assert result == t2_end


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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/unit/trigger/test_job_runs.py -v -k "not table_exists"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sebastian.trigger.job_runs'`

- [ ] **Step 3: Create `sebastian/trigger/job_runs.py`**

```python
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.store.models import ScheduledJobRunRecord

logger = logging.getLogger(__name__)


class ScheduledJobRunStore:
    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

    async def start_run(self, job_id: str, started_at: datetime) -> str:
        from ulid import ULID

        run_id = str(ULID())
        async with self._db_factory() as session:
            async with session.begin():
                session.add(
                    ScheduledJobRunRecord(
                        id=run_id,
                        job_id=job_id,
                        status="running",
                        started_at=started_at,
                    )
                )
        return run_id

    async def finish_run(
        self,
        run_id: str,
        status: str,
        finished_at: datetime,
        *,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        async with self._db_factory() as session:
            async with session.begin():
                record = await session.get(ScheduledJobRunRecord, run_id)
                if record is None:
                    logger.warning("finish_run: run_id=%s not found", run_id)
                    return
                record.status = status
                record.finished_at = finished_at
                record.duration_ms = duration_ms
                record.error = error

    async def record_skipped(self, job_id: str, at: datetime, reason: str) -> None:
        from ulid import ULID

        async with self._db_factory() as session:
            async with session.begin():
                session.add(
                    ScheduledJobRunRecord(
                        id=str(ULID()),
                        job_id=job_id,
                        status="skipped",
                        started_at=at,
                        finished_at=at,
                        duration_ms=0,
                        error=reason,
                    )
                )

    async def get_last_success_at(self, job_id: str) -> datetime | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(ScheduledJobRunRecord.finished_at)
                .where(
                    ScheduledJobRunRecord.job_id == job_id,
                    ScheduledJobRunRecord.status == "success",
                )
                .order_by(ScheduledJobRunRecord.started_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
```

- [ ] **Step 4: Run all `test_job_runs.py` tests**

```bash
pytest tests/unit/trigger/test_job_runs.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/trigger/job_runs.py tests/unit/trigger/test_job_runs.py
git commit -m "feat(trigger): add ScheduledJobRunStore with full run history CRUD

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: `ScheduledJob` + `JobRegistry`

**Files:**
- Create: `sebastian/trigger/scheduler.py` (dataclass + registry only; `SchedulerRunner` in Task 4)
- Create: `tests/unit/trigger/test_scheduler.py` (registry tests only)

- [ ] **Step 1: Write the failing tests for `ScheduledJob` and `JobRegistry`**

Create `tests/unit/trigger/test_scheduler.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from sebastian.trigger.scheduler import JobRegistry, ScheduledJob


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
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/unit/trigger/test_scheduler.py -v -k "registry or defaults"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sebastian.trigger.scheduler'`

- [ ] **Step 3: Create `sebastian/trigger/scheduler.py`** (dataclass + registry only)

```python
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScheduledJob:
    id: str
    handler: Callable[[], Awaitable[Any]]
    interval: timedelta
    run_on_startup: bool = False
    startup_delay: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    timeout_seconds: float = 300
    concurrency_policy: Literal["skip_if_running"] = "skip_if_running"


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, ScheduledJob] = {}

    def register(self, job: ScheduledJob) -> None:
        if job.id in self._jobs:
            raise ValueError(f"Duplicate job id: {job.id!r}")
        self._jobs[job.id] = job

    def list_jobs(self) -> list[ScheduledJob]:
        return list(self._jobs.values())
```

Note: `timeout_seconds` is `float` (not `int`) so tests can use sub-second values like `0.01` without type errors. Values like `300` remain valid.

- [ ] **Step 4: Run the registry/defaults tests**

```bash
pytest tests/unit/trigger/test_scheduler.py -v -k "registry or defaults"
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/trigger/scheduler.py tests/unit/trigger/test_scheduler.py
git commit -m "feat(trigger): add ScheduledJob dataclass and JobRegistry

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: `SchedulerRunner`

**Files:**
- Modify: `sebastian/trigger/scheduler.py` (add `SchedulerRunner`)
- Modify: `tests/unit/trigger/test_scheduler.py` (add `SchedulerRunner` tests)

The `SchedulerRunner` exposes two internal methods for direct testing: `_compute_initial_next_run` (static) and `_tick(now)`. Tests call these instead of going through the polling loop.

- [ ] **Step 1: Write the failing `SchedulerRunner` tests**

Append to `tests/unit/trigger/test_scheduler.py`:

```python
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.models import ScheduledJobRunRecord
from sebastian.trigger.job_runs import ScheduledJobRunStore
from sebastian.trigger.scheduler import SchedulerRunner


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

    # First tick: starts the job
    await runner._tick(now)
    assert not runner._running["test.slow"].done()

    # Second tick: job still running → should record skipped
    runner._next_run["test.slow"] = now
    await runner._tick(now)

    async with scheduler_db() as session:
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/unit/trigger/test_scheduler.py -v -k "compute or tick or run_job or aclose"
```

Expected: FAIL — `cannot import name 'SchedulerRunner' from 'sebastian.trigger.scheduler'`

- [ ] **Step 3: Add `SchedulerRunner` to `sebastian/trigger/scheduler.py`**

Append this class after `JobRegistry`:

```python
class SchedulerRunner:
    def __init__(
        self,
        registry: JobRegistry,
        run_store: ScheduledJobRunStore,
        poll_interval: timedelta = timedelta(seconds=30),
    ) -> None:
        from sebastian.trigger.job_runs import ScheduledJobRunStore as _Store  # noqa: F401

        self._registry = registry
        self._run_store = run_store
        self._poll_interval = poll_interval
        self._next_run: dict[str, datetime] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._shutdown = False

    @staticmethod
    def _compute_initial_next_run(
        job: ScheduledJob,
        last_success_at: datetime | None,
        now: datetime,
    ) -> datetime:
        if last_success_at is not None:
            candidate = last_success_at + job.interval
            if candidate <= now:
                return now + job.startup_delay
            return candidate
        if job.run_on_startup:
            return now + job.startup_delay
        return now + job.interval

    async def start(self) -> None:
        now = datetime.now(UTC)
        for job in self._registry.list_jobs():
            last_success = await self._run_store.get_last_success_at(job.id)
            self._next_run[job.id] = self._compute_initial_next_run(job, last_success, now)
        self._loop_task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._shutdown:
            await self._tick(datetime.now(UTC))
            await asyncio.sleep(self._poll_interval.total_seconds())

    async def _tick(self, now: datetime) -> None:
        for job in self._registry.list_jobs():
            next_run = self._next_run.get(job.id)
            if next_run is None or now < next_run:
                continue
            self._next_run[job.id] = now + job.interval
            running_task = self._running.get(job.id)
            if running_task is not None and not running_task.done():
                await self._run_store.record_skipped(
                    job.id, at=now, reason="previous run still in progress"
                )
            else:
                self._running[job.id] = asyncio.create_task(self._run_job(job))

    async def _run_job(self, job: ScheduledJob) -> None:
        started_at = datetime.now(UTC)
        run_id = await self._run_store.start_run(job.id, started_at)
        try:
            await asyncio.wait_for(job.handler(), timeout=job.timeout_seconds)
        except TimeoutError:
            finished_at = datetime.now(UTC)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            await self._run_store.finish_run(
                run_id, "timeout", finished_at, duration_ms=duration_ms
            )
            logger.error("Job %s timed out after %.1fs", job.id, job.timeout_seconds)
        except asyncio.CancelledError:
            finished_at = datetime.now(UTC)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            with contextlib.suppress(Exception):
                await self._run_store.finish_run(
                    run_id, "cancelled", finished_at, duration_ms=duration_ms
                )
            raise
        except Exception as exc:
            finished_at = datetime.now(UTC)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            await self._run_store.finish_run(
                run_id, "failed", finished_at, duration_ms=duration_ms, error=str(exc)
            )
            logger.exception("Job %s failed", job.id)
        else:
            finished_at = datetime.now(UTC)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            await self._run_store.finish_run(
                run_id, "success", finished_at, duration_ms=duration_ms
            )
            logger.info("Job %s completed in %dms", job.id, duration_ms)

    async def aclose(self, grace_period: float = 5.0) -> None:
        self._shutdown = True
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        running_tasks = [t for t in self._running.values() if not t.done()]
        if running_tasks:
            _done, pending = await asyncio.wait(running_tasks, timeout=grace_period)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
```

Also add the import at the top of `scheduler.py` (after the existing imports):

```python
from sebastian.trigger.job_runs import ScheduledJobRunStore
```

- [ ] **Step 4: Run all scheduler tests**

```bash
pytest tests/unit/trigger/test_scheduler.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Run the full unit trigger suite**

```bash
pytest tests/unit/trigger/ -v
```

Expected: all tests in both test files PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/trigger/scheduler.py tests/unit/trigger/test_scheduler.py
git commit -m "feat(trigger): add SchedulerRunner with poll loop, tick, run_job, aclose

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: `register_builtin_jobs`

**Files:**
- Create: `sebastian/trigger/jobs.py`
- Create: `tests/integration/test_scheduler_lifecycle.py`

- [ ] **Step 1: Write the failing registration test**

Create `tests/integration/test_scheduler_lifecycle.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.trigger.job_runs import ScheduledJobRunStore
from sebastian.trigger.jobs import register_builtin_jobs
from sebastian.trigger.scheduler import JobRegistry, SchedulerRunner


@pytest.fixture
async def lifecycle_db(tmp_path):
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base, _apply_idempotent_migrations

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory, tmp_path
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


async def test_register_builtin_jobs_registers_attachments_cleanup(lifecycle_db) -> None:
    from sebastian.store.attachments import AttachmentStore

    factory, tmp_path = lifecycle_db
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True)
    attachment_store = AttachmentStore(root_dir=root, db_factory=factory)

    registry = JobRegistry()
    register_builtin_jobs(registry, attachment_store=attachment_store)

    jobs = registry.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "attachments.cleanup"
    assert jobs[0].interval == timedelta(hours=6)
    assert jobs[0].run_on_startup is True


async def test_scheduler_runs_job_and_persists_success(lifecycle_db) -> None:
    """Full end-to-end: tick → job runs → success record written → restart reads history."""
    from sebastian.store.attachments import AttachmentStore

    factory, tmp_path = lifecycle_db
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True)
    attachment_store = AttachmentStore(root_dir=root, db_factory=factory)

    registry = JobRegistry()
    register_builtin_jobs(registry, attachment_store=attachment_store)
    run_store = ScheduledJobRunStore(factory)
    runner = SchedulerRunner(registry=registry, run_store=run_store)

    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    runner._next_run["attachments.cleanup"] = now  # force immediately due

    await runner._tick(now)
    task = runner._running.get("attachments.cleanup")
    assert task is not None
    await task  # wait for cleanup to complete

    last_success = await run_store.get_last_success_at("attachments.cleanup")
    assert last_success is not None


async def test_restart_recovery_uses_db_history(lifecycle_db) -> None:
    """After a simulated restart, next_run is last_success + interval, not epoch."""
    from sebastian.store.attachments import AttachmentStore

    factory, tmp_path = lifecycle_db
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True)
    attachment_store = AttachmentStore(root_dir=root, db_factory=factory)

    # First run: job completes successfully
    run_store = ScheduledJobRunStore(factory)
    registry1 = JobRegistry()
    register_builtin_jobs(registry1, attachment_store=attachment_store)
    runner1 = SchedulerRunner(registry=registry1, run_store=run_store)

    now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    runner1._next_run["attachments.cleanup"] = now
    await runner1._tick(now)
    task1 = runner1._running.get("attachments.cleanup")
    if task1:
        await task1

    last_success = await run_store.get_last_success_at("attachments.cleanup")
    assert last_success is not None

    # Simulate restart: new runner reads DB history via start()
    registry2 = JobRegistry()
    register_builtin_jobs(registry2, attachment_store=attachment_store)
    runner2 = SchedulerRunner(registry=registry2, run_store=run_store)

    restart_now = datetime(2024, 1, 1, 10, 30, 0, tzinfo=UTC)  # 30min after first run
    # Patch datetime.now inside start() is complex; instead call _compute_initial_next_run directly
    job = registry2.list_jobs()[0]
    computed = SchedulerRunner._compute_initial_next_run(job, last_success, restart_now)
    # next run = last_success + 6h; not "now + startup_delay"
    assert computed > restart_now  # should NOT run immediately

    await runner2.aclose()  # clean up (no loop task started since we didn't call start())
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/integration/test_scheduler_lifecycle.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sebastian.trigger.jobs'`

- [ ] **Step 3: Create `sebastian/trigger/jobs.py`**

```python
from __future__ import annotations

from datetime import timedelta

from sebastian.store.attachments import AttachmentStore
from sebastian.trigger.scheduler import JobRegistry, ScheduledJob


def register_builtin_jobs(
    registry: JobRegistry,
    *,
    attachment_store: AttachmentStore,
) -> None:
    registry.register(
        ScheduledJob(
            id="attachments.cleanup",
            handler=attachment_store.cleanup,
            interval=timedelta(hours=6),
            run_on_startup=True,
            startup_delay=timedelta(minutes=2),
            timeout_seconds=300,
        )
    )
```

- [ ] **Step 4: Run the integration tests**

```bash
pytest tests/integration/test_scheduler_lifecycle.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/trigger/jobs.py tests/integration/test_scheduler_lifecycle.py
git commit -m "feat(trigger): add register_builtin_jobs with attachments.cleanup

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Gateway integration

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: Add `scheduler` to `state.py`**

In `sebastian/gateway/state.py`, add to the `TYPE_CHECKING` block:

```python
    from sebastian.trigger.scheduler import SchedulerRunner
```

And add a new module-level variable at the end of the variable declarations (after `attachment_store`):

```python
scheduler: SchedulerRunner | None = None
```

- [ ] **Step 2: Run the existing gateway tests to confirm no regressions**

```bash
pytest tests/unit/gateway/ tests/integration/test_gateway_attachments.py -v 2>/dev/null || pytest tests/ -k "gateway" --ignore=tests/integration/test_scheduler_lifecycle.py -v
```

Expected: all existing gateway tests PASS

- [ ] **Step 3: Add scheduler startup to `app.py` lifespan**

In `sebastian/gateway/app.py`, find the block that creates `attachment_store` (around line 115):

```python
    from sebastian.store.attachments import AttachmentStore

    attachment_store = AttachmentStore(settings.attachments_dir, db_factory)
    state.attachment_store = attachment_store
```

Append the scheduler setup **immediately after** `state.attachment_store = attachment_store`:

```python
    from sebastian.trigger.job_runs import ScheduledJobRunStore
    from sebastian.trigger.jobs import register_builtin_jobs
    from sebastian.trigger.scheduler import JobRegistry, SchedulerRunner

    _job_registry = JobRegistry()
    register_builtin_jobs(_job_registry, attachment_store=attachment_store)
    _scheduler = SchedulerRunner(
        registry=_job_registry,
        run_store=ScheduledJobRunStore(db_factory),
    )
    await _scheduler.start()
    state.scheduler = _scheduler
```

- [ ] **Step 4: Add scheduler shutdown to `app.py` lifespan teardown**

In `sebastian/gateway/app.py`, find the shutdown block after `yield` (around line 313):

```python
    logger.info("Sebastian gateway started")
    yield
    watchdog_task.cancel()
    try:
        await completion_notifier.aclose()
        if state.consolidation_scheduler is not None:
            await state.consolidation_scheduler.aclose()
        ...
    finally:
        ...
        from sebastian.store.database import get_engine
        await get_engine().dispose()
```

Add the scheduler close **inside the `try` block, as the first operation** (before `completion_notifier.aclose()`):

```python
    try:
        if state.scheduler is not None:
            await state.scheduler.aclose()
            state.scheduler = None
        await completion_notifier.aclose()
        if state.consolidation_scheduler is not None:
            await state.consolidation_scheduler.aclose()
        ...
```

The ordering constraint `scheduler.aclose()` → `get_engine().dispose()` is satisfied because the scheduler runs before the `finally` block that disposes the engine.

- [ ] **Step 5: Run linter and type checker**

```bash
ruff check sebastian/trigger/ sebastian/gateway/state.py sebastian/gateway/app.py
ruff format sebastian/trigger/ sebastian/gateway/state.py sebastian/gateway/app.py
```

Expected: no errors; if format changes files, re-run `ruff check` to confirm clean.

- [ ] **Step 6: Run the full test suite**

```bash
pytest tests/unit/ tests/integration/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests PASS (no regressions in gateway, store, or trigger tests)

- [ ] **Step 7: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py
git commit -m "feat(gateway): wire SchedulerRunner into lifespan — starts on boot, closes before engine dispose

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: README updates

**Files:**
- Modify: `sebastian/trigger/README.md`
- Modify: `sebastian/store/README.md`

- [ ] **Step 1: Rewrite `sebastian/trigger/README.md`**

Replace the entire file with:

```markdown
# trigger — 主动触发引擎

> 上级索引：[sebastian/](../README.md)

## 模块职责

`trigger/` 是 Sebastian 的后台任务调度基础设施，负责无用户输入情况下的主动执行。第一版实现单实例进程内 async 调度器，管理周期性系统维护任务（如附件清理）。

## 目录结构

```
trigger/
├── __init__.py      # 空模块入口
├── scheduler.py     # ScheduledJob, JobRegistry, SchedulerRunner
├── job_runs.py      # ScheduledJobRunStore：scheduled_job_runs 表读写
├── jobs.py          # register_builtin_jobs(...)：内置任务注册
└── README.md
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 调度循环、并发策略、timeout 处理 | [scheduler.py](scheduler.py) 的 `SchedulerRunner` |
| 运行历史读写（start / finish / skipped） | [job_runs.py](job_runs.py) 的 `ScheduledJobRunStore` |
| 内置任务注册（新增/修改 job） | [jobs.py](jobs.py) 的 `register_builtin_jobs` |
| `scheduled_job_runs` ORM 模型 | [../store/models.py](../store/models.py) 的 `ScheduledJobRunRecord` |
| Gateway 启动/关闭集成 | [../gateway/app.py](../gateway/app.py) lifespan |

## 设计要点

- **Job definition 在代码中**，不持久化到数据库。重启后由 `ScheduledJobRunStore.get_last_success_at` 推导 `next_run_at`，避免重启瞬间集中执行。
- **`skip_if_running` 并发策略**：同一 job 上一次未结束时下一次触发只写 `skipped` 记录，不并发执行。
- **poll_interval 默认 30s**，可在构造 `SchedulerRunner` 时传入更短的值（如测试环境）。
- **Scheduler shutdown 必须在 `get_engine().dispose()` 之前**（gateway lifespan 已保证）。
- 进程崩溃可能留下 `status="running"` 的孤儿行，不影响重启恢复（恢复只查 `status="success"`）。

## 未来扩展接入点

- 新增系统维护任务：在 `jobs.py` 的 `register_builtin_jobs` 中 `registry.register(...)` 一行。
- 用户业务触发（提醒、定时消息）：新增 `user_triggers` 业务表 + `TriggerDispatcher`；scheduler 注册一个扫描 job，不在 `trigger/` 内处理业务语义。

---

> 修改本目录或模块后，请同步更新此 README。
```

- [ ] **Step 2: Add `scheduled_job_runs` entry to `sebastian/store/README.md`**

In `sebastian/store/README.md`, update the "目录结构" code block to add:

```
├── attachments.py           # AttachmentStore：附件 blob 存储与状态管理
```

Already exists. Immediately after the `attachments.py` line, add nothing (attachment store line already there). Instead, update the **"修改导航" table** to add a new row:

```
| scheduler 运行历史读写 | [../trigger/job_runs.py](../trigger/job_runs.py) 的 `ScheduledJobRunStore`；ORM model：[models.py](models.py) 的 `ScheduledJobRunRecord` |
```

Add this row to the table in the "修改导航" section.

- [ ] **Step 3: Run lint on the changed files**

```bash
ruff check sebastian/trigger/README.md sebastian/store/README.md 2>/dev/null || echo "README files skipped by ruff — OK"
```

- [ ] **Step 4: Commit**

```bash
git add sebastian/trigger/README.md sebastian/store/README.md
git commit -m "docs(trigger): update trigger and store READMEs for scheduler module

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Covered by |
|---|---|
| `ScheduledJob` dataclass with all fields | Task 3 |
| `JobRegistry` rejects duplicate id | Task 3 |
| `SchedulerRunner` startup next_run computation (4 cases) | Task 4 |
| `SchedulerRunner` poll loop + tick | Task 4 |
| `skip_if_running` writes skipped record | Task 4 |
| `_run_job` success / failed / timeout / cancelled | Task 4 |
| `aclose` grace period + cancel | Task 4 |
| `ScheduledJobRunRecord` ORM + index | Task 1 |
| `ScheduledJobRunStore` all 4 methods | Task 2 |
| `record_skipped` field values (`started_at=at`, `finished_at=at`, `duration_ms=0`) | Task 2 |
| `get_last_success_at` ignores stale `running` rows | Task 2 |
| `register_builtin_jobs` with `attachments.cleanup` | Task 5 |
| Gateway lifespan: create / start / close scheduler | Task 6 |
| Shutdown ordering: scheduler before engine dispose | Task 6 |
| `state.scheduler` runtime reference | Task 6 |
| trigger/README.md updated | Task 7 |
| store/README.md updated | Task 7 |

### Placeholder scan

No TBD, TODO, or incomplete sections. All code blocks are complete.

### Type consistency

- `ScheduledJobRunStore` used in Tasks 2, 4, 5, 6 — consistent.
- `ScheduledJob(id=..., handler=..., interval=...)` used in Tasks 3, 4, 5 — consistent.
- `JobRegistry` used in Tasks 3, 4, 5, 6 — consistent.
- `finish_run(run_id, status, finished_at, *, duration_ms=..., error=...)` keyword-only after `finished_at` — consistent across Task 2 implementation and Task 4 usage.
- `state.scheduler` type `SchedulerRunner | None` consistent between Task 6 state.py change and app.py usage.

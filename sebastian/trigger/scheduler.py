from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sebastian.trigger.job_runs import ScheduledJobRunStore

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


class SchedulerRunner:
    def __init__(
        self,
        registry: JobRegistry,
        run_store: ScheduledJobRunStore,
        poll_interval: timedelta = timedelta(seconds=30),
    ) -> None:
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
        # Clean up completed task references to avoid memory leak
        self._running = {k: v for k, v in self._running.items() if not v.done()}
        for job in self._registry.list_jobs():
            next_run = self._next_run.get(job.id)
            if next_run is None or now < next_run:
                continue
            self._next_run[job.id] = now + job.interval
            running_task = self._running.get(job.id)
            if running_task is not None and not running_task.done():
                if job.concurrency_policy == "skip_if_running":
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

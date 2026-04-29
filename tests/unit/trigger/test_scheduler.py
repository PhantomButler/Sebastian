from __future__ import annotations

from datetime import timedelta

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

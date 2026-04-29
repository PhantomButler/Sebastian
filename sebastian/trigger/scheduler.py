from __future__ import annotations

import asyncio  # noqa: F401
import contextlib  # noqa: F401
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta  # noqa: F401
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

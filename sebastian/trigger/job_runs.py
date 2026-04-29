from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from sebastian.store.models import ScheduledJobRunRecord

logger = logging.getLogger(__name__)


def _naive(dt: datetime) -> datetime:
    """Strip timezone info before storing — SQLite columns are timezone-naive."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


class ScheduledJobRunStore:
    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

    async def start_run(self, job_id: str, started_at: datetime) -> str:
        run_id = str(ULID())
        async with self._db_factory() as session:
            async with session.begin():
                session.add(
                    ScheduledJobRunRecord(
                        id=run_id,
                        job_id=job_id,
                        status="running",
                        started_at=_naive(started_at),
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
                record.finished_at = _naive(finished_at)
                record.duration_ms = duration_ms
                record.error = error

    async def record_skipped(self, job_id: str, at: datetime, reason: str) -> None:
        naive_at = _naive(at)
        async with self._db_factory() as session:
            async with session.begin():
                session.add(
                    ScheduledJobRunRecord(
                        id=str(ULID()),
                        job_id=job_id,
                        status="skipped",
                        started_at=naive_at,
                        finished_at=naive_at,
                        duration_ms=0,
                        error=reason,
                    )
                )

    async def get_last_success_at(self, job_id: str) -> datetime | None:
        async with self._db_factory() as session:
            async with session.begin():
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

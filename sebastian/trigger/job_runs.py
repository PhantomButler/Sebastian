from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from sebastian.store.models import ScheduledJobRunRecord

logger = logging.getLogger(__name__)


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
            async with session.begin():
                success_at = func.coalesce(
                    ScheduledJobRunRecord.finished_at,
                    ScheduledJobRunRecord.started_at,
                )
                result = await session.execute(
                    select(success_at)
                    .where(
                        ScheduledJobRunRecord.job_id == job_id,
                        ScheduledJobRunRecord.status == "success",
                    )
                    .order_by(success_at.desc())
                    .limit(1)
                )
                return result.scalar_one_or_none()

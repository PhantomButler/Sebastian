from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update

from sebastian.memory.types import MemoryArtifact, MemoryStatus
from sebastian.store.models import ProfileMemoryRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProfileMemoryStore:
    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def add(self, artifact: MemoryArtifact) -> ProfileMemoryRecord:
        record = self._artifact_to_record(artifact)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_active_by_slot(
        self,
        subject_id: str,
        scope: str,
        slot_id: str,
    ) -> list[ProfileMemoryRecord]:
        now = datetime.now(UTC)
        result = await self._session.scalars(
            select(ProfileMemoryRecord).where(
                ProfileMemoryRecord.subject_id == subject_id,
                ProfileMemoryRecord.scope == scope,
                ProfileMemoryRecord.slot_id == slot_id,
                ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
                or_(
                    ProfileMemoryRecord.valid_until.is_(None),
                    ProfileMemoryRecord.valid_until > now,
                ),
            )
        )
        return list(result.all())

    async def supersede(
        self,
        old_ids: list[str],
        artifact: MemoryArtifact,
    ) -> ProfileMemoryRecord:
        now = datetime.now(UTC)
        if old_ids:
            await self._session.execute(
                update(ProfileMemoryRecord)
                .where(ProfileMemoryRecord.id.in_(old_ids))
                .values(
                    status=MemoryStatus.SUPERSEDED.value,
                    updated_at=now,
                )
            )
        record = await self.add(artifact)
        await self._session.flush()
        return record

    async def search_active(
        self,
        *,
        subject_id: str,
        scope: str | None = None,
        limit: int = 8,
    ) -> list[ProfileMemoryRecord]:
        now = datetime.now(UTC)
        statement = select(ProfileMemoryRecord).where(
            ProfileMemoryRecord.subject_id == subject_id,
            ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
            or_(
                ProfileMemoryRecord.valid_until.is_(None),
                ProfileMemoryRecord.valid_until > now,
            ),
        )
        if scope is not None:
            statement = statement.where(ProfileMemoryRecord.scope == scope)
        statement = statement.order_by(ProfileMemoryRecord.created_at.desc()).limit(limit)

        result = await self._session.scalars(statement)
        return list(result.all())

    async def search_recent_context(
        self,
        *,
        subject_id: str,
        window_days: int = 7,
        limit: int = 3,
    ) -> list[ProfileMemoryRecord]:
        """Return recent active FACT/PREFERENCE records within the time window."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=window_days)
        statement = (
            select(ProfileMemoryRecord)
            .where(
                ProfileMemoryRecord.subject_id == subject_id,
                ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
                or_(
                    ProfileMemoryRecord.valid_until.is_(None),
                    ProfileMemoryRecord.valid_until > now,
                ),
                ProfileMemoryRecord.created_at >= cutoff,
            )
            .order_by(ProfileMemoryRecord.created_at.desc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def touch(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        await self._session.execute(
            update(ProfileMemoryRecord)
            .where(ProfileMemoryRecord.id.in_(memory_ids))
            .values(
                access_count=ProfileMemoryRecord.access_count + 1,
                last_accessed_at=datetime.now(UTC),
            )
        )
        await self._session.flush()

    def _artifact_to_record(self, artifact: MemoryArtifact) -> ProfileMemoryRecord:
        return ProfileMemoryRecord(
            id=artifact.id,
            subject_id=artifact.subject_id,
            scope=artifact.scope.value,
            slot_id=artifact.slot_id or "",
            kind=artifact.kind.value,
            content=artifact.content,
            structured_payload=artifact.structured_payload,
            source=artifact.source.value,
            confidence=artifact.confidence,
            status=MemoryStatus.ACTIVE.value,
            valid_from=artifact.valid_from,
            valid_until=artifact.valid_until,
            provenance=artifact.provenance,
            policy_tags=artifact.policy_tags,
            created_at=artifact.recorded_at,
            updated_at=artifact.recorded_at,
            last_accessed_at=artifact.last_accessed_at,
            access_count=artifact.access_count,
        )

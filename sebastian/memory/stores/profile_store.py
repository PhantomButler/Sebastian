from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_, select, text, update
from sqlalchemy.engine import CursorResult

from sebastian.memory.retrieval.segmentation import build_match_query, segment_for_fts, terms_for_query
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
        await self._session.execute(
            text(
                "INSERT INTO profile_memories_fts(memory_id, content_segmented) "
                "VALUES (:memory_id, :content_segmented)"
            ),
            {"memory_id": record.id, "content_segmented": record.content_segmented},
        )
        await self._session.flush()
        return record

    async def find_active_exact(
        self,
        *,
        subject_id: str,
        scope: str,
        slot_id: str,
        kind: str,
        content: str,
    ) -> ProfileMemoryRecord | None:
        """Return the first active record that exactly matches all five fields, or None."""
        now = datetime.now(UTC)
        statement = select(ProfileMemoryRecord).where(
            ProfileMemoryRecord.subject_id == subject_id,
            ProfileMemoryRecord.scope == scope,
            ProfileMemoryRecord.slot_id == slot_id,
            ProfileMemoryRecord.kind == kind,
            ProfileMemoryRecord.content == content,
            ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
            or_(ProfileMemoryRecord.valid_until.is_(None), ProfileMemoryRecord.valid_until > now),
            or_(ProfileMemoryRecord.valid_from.is_(None), ProfileMemoryRecord.valid_from <= now),
        )
        result = await self._session.scalars(statement)
        return result.first()

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
                or_(
                    ProfileMemoryRecord.valid_from.is_(None),
                    ProfileMemoryRecord.valid_from <= now,
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

    async def expire(self, memory_id: str) -> int:
        """Mark a profile memory record as EXPIRED. Returns rowcount (0 = not found)."""
        now = datetime.now(UTC)
        cursor: CursorResult[tuple[()]] = await self._session.execute(  # type: ignore[assignment]
            update(ProfileMemoryRecord)
            .where(ProfileMemoryRecord.id == memory_id)
            .values(
                status=MemoryStatus.EXPIRED.value,
                updated_at=now,
            )
        )
        await self._session.flush()
        return cursor.rowcount

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
            or_(
                ProfileMemoryRecord.valid_from.is_(None),
                ProfileMemoryRecord.valid_from <= now,
            ),
        )
        if scope is not None:
            statement = statement.where(ProfileMemoryRecord.scope == scope)
        statement = statement.order_by(
            ProfileMemoryRecord.confidence.desc(),
            ProfileMemoryRecord.created_at.desc(),
        ).limit(limit)

        result = await self._session.scalars(statement)
        return list(result.all())

    async def search_recent_context(
        self,
        *,
        subject_id: str,
        query: str = "",
        window_days: int = 7,
        limit: int = 3,
    ) -> list[ProfileMemoryRecord]:
        """Return recent active records matching *query* within *window_days*.

        Uses FTS5 + jieba when *query* is non-empty and produces terms.
        Falls back to confidence-then-recency order when *query* is empty
        or produces no FTS terms.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=window_days)
        base_filters = [
            ProfileMemoryRecord.subject_id == subject_id,
            ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
            or_(ProfileMemoryRecord.valid_until.is_(None), ProfileMemoryRecord.valid_until > now),
            or_(ProfileMemoryRecord.valid_from.is_(None), ProfileMemoryRecord.valid_from <= now),
            ProfileMemoryRecord.created_at >= cutoff,
        ]

        terms = terms_for_query(query) if query else []
        if terms:
            match_counts: Counter[str] = Counter()
            for term in terms:
                phrase = build_match_query([term])
                fts_result = await self._session.execute(
                    text(
                        "SELECT memory_id FROM profile_memories_fts "
                        "WHERE content_segmented MATCH :query"
                    ),
                    {"query": phrase},
                )
                match_counts.update(row[0] for row in fts_result)

            if match_counts:
                ids_by_rank = [mid for mid, _ in match_counts.most_common()]
                rank_by_id = {mid: rank for rank, mid in enumerate(ids_by_rank)}

                rows = await self._session.scalars(
                    select(ProfileMemoryRecord).where(
                        *base_filters,
                        ProfileMemoryRecord.id.in_(ids_by_rank),
                    )
                )
                records = list(rows.all())
                records.sort(key=lambda r: (rank_by_id[r.id], -float(r.confidence or 0.0)))
                return records[:limit]

        # Fallback: confidence-then-recency
        statement = (
            select(ProfileMemoryRecord)
            .where(*base_filters)
            .order_by(
                ProfileMemoryRecord.confidence.desc(),
                ProfileMemoryRecord.created_at.desc(),
            )
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
            cardinality=artifact.cardinality.value if artifact.cardinality is not None else None,
            resolution_policy=(
                artifact.resolution_policy.value if artifact.resolution_policy is not None else None
            ),
            content=artifact.content,
            content_segmented=segment_for_fts(artifact.content),
            structured_payload=artifact.structured_payload,
            source=artifact.source.value,
            confidence=float(artifact.confidence),
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

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text, update

from sebastian.memory.segmentation import segment_for_fts, terms_for_query
from sebastian.memory.types import MemoryArtifact, MemoryKind, MemoryStatus
from sebastian.store.models import EpisodeMemoryRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


def _build_match_query(terms: list[str]) -> str:
    """Wrap each term as a double-quoted phrase for FTS5 MATCH.

    Prevents operators (AND/OR/NOT/*/quote/paren) inside the user query from
    being interpreted as FTS5 syntax. Empty term list yields an empty-string
    phrase, which FTS5 treats as no-match.
    """
    safe = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms if t]
    return " ".join(safe) if safe else '""'


async def ensure_episode_fts(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
            "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
        )
    )


class EpisodeMemoryStore:
    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def add_episode(self, artifact: MemoryArtifact) -> EpisodeMemoryRecord:
        record = self._artifact_to_record(artifact)
        self._session.add(record)
        await self._session.flush()
        await self._session.execute(
            text(
                "INSERT INTO episode_memories_fts(memory_id, content_segmented) "
                "VALUES (:memory_id, :content_segmented)"
            ),
            {
                "memory_id": record.id,
                "content_segmented": record.content_segmented,
            },
        )
        await self._session.flush()
        return record

    async def add_summary(self, artifact: MemoryArtifact) -> EpisodeMemoryRecord:
        summary = artifact.model_copy(update={"kind": MemoryKind.SUMMARY})
        return await self.add_episode(summary)

    async def _search_by_kind(
        self,
        *,
        subject_id: str,
        query: str,
        kinds: set[MemoryKind],
        limit: int,
    ) -> list[EpisodeMemoryRecord]:
        """FTS search filtered to the given set of MemoryKind values.

        Reuses terms_for_query / _build_match_query / match_counts ranking,
        then additionally filters by kind, subject_id, and active status.
        """
        terms = terms_for_query(query)
        if not terms:
            return []

        match_counts: Counter[str] = Counter()
        for term in terms:
            phrase = _build_match_query([term])
            result = await self._session.execute(
                text(
                    "SELECT memory_id FROM episode_memories_fts "
                    "WHERE content_segmented MATCH :query"
                ),
                {"query": phrase},
            )
            match_counts.update(row.memory_id for row in result)

        if not match_counts:
            return []

        ids_by_rank = [memory_id for memory_id, _count in match_counts.most_common()]
        rank_by_id = {memory_id: rank for rank, memory_id in enumerate(ids_by_rank)}

        kind_values = [k.value for k in kinds]
        episode_rows = await self._session.scalars(
            select(EpisodeMemoryRecord).where(
                EpisodeMemoryRecord.id.in_(ids_by_rank),
                EpisodeMemoryRecord.subject_id == subject_id,
                EpisodeMemoryRecord.status == MemoryStatus.ACTIVE.value,
                EpisodeMemoryRecord.kind.in_(kind_values),
            )
        )
        records = list(episode_rows.all())
        records.sort(
            key=lambda record: (
                rank_by_id[record.id],
                -record.recorded_at.timestamp(),
            )
        )
        return records[:limit]

    async def search(
        self,
        *,
        subject_id: str,
        query: str,
        limit: int = 8,
    ) -> list[EpisodeMemoryRecord]:
        return await self._search_by_kind(
            subject_id=subject_id,
            query=query,
            kinds={MemoryKind.SUMMARY, MemoryKind.EPISODE},
            limit=limit,
        )

    async def search_summaries_by_query(
        self,
        *,
        subject_id: str,
        query: str,
        limit: int = 8,
    ) -> list[EpisodeMemoryRecord]:
        """FTS search restricted to SUMMARY-kind records."""
        return await self._search_by_kind(
            subject_id=subject_id,
            query=query,
            kinds={MemoryKind.SUMMARY},
            limit=limit,
        )

    async def search_episodes_only(
        self,
        *,
        subject_id: str,
        query: str,
        limit: int = 8,
    ) -> list[EpisodeMemoryRecord]:
        """FTS search restricted to EPISODE-kind records."""
        return await self._search_by_kind(
            subject_id=subject_id,
            query=query,
            kinds={MemoryKind.EPISODE},
            limit=limit,
        )

    async def search_summaries(
        self,
        *,
        subject_id: str,
        limit: int = 8,
    ) -> list[EpisodeMemoryRecord]:
        """Return recent SUMMARY-kind active episodes for *subject_id*, newest first."""
        statement = (
            select(EpisodeMemoryRecord)
            .where(
                EpisodeMemoryRecord.subject_id == subject_id,
                EpisodeMemoryRecord.kind == MemoryKind.SUMMARY.value,
                EpisodeMemoryRecord.status == MemoryStatus.ACTIVE.value,
            )
            .order_by(EpisodeMemoryRecord.recorded_at.desc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def find_active_exact(
        self,
        *,
        subject_id: str,
        kind: MemoryKind,
        content: str,
    ) -> EpisodeMemoryRecord | None:
        """Return the first active record with an exact content match, or None."""
        statement = select(EpisodeMemoryRecord).where(
            EpisodeMemoryRecord.subject_id == subject_id,
            EpisodeMemoryRecord.kind == kind.value,
            EpisodeMemoryRecord.status == MemoryStatus.ACTIVE.value,
            EpisodeMemoryRecord.content == content,
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def touch(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        await self._session.execute(
            update(EpisodeMemoryRecord)
            .where(EpisodeMemoryRecord.id.in_(memory_ids))
            .values(
                access_count=EpisodeMemoryRecord.access_count + 1,
                last_accessed_at=datetime.now(UTC),
            )
        )
        await self._session.flush()

    def _artifact_to_record(self, artifact: MemoryArtifact) -> EpisodeMemoryRecord:
        session_id = _session_id_from_provenance(artifact.provenance)
        return EpisodeMemoryRecord(
            id=artifact.id,
            subject_id=artifact.subject_id,
            scope=artifact.scope.value,
            session_id=session_id,
            kind=artifact.kind.value,
            content=artifact.content,
            content_segmented=segment_for_fts(artifact.content),
            structured_payload=artifact.structured_payload,
            source=artifact.source.value,
            confidence=artifact.confidence,
            status=MemoryStatus.ACTIVE.value,
            recorded_at=artifact.recorded_at,
            valid_from=artifact.valid_from,
            valid_until=artifact.valid_until,
            provenance=artifact.provenance,
            links=artifact.links,
            policy_tags=artifact.policy_tags,
            last_accessed_at=artifact.last_accessed_at,
            access_count=artifact.access_count,
        )


def _session_id_from_provenance(provenance: dict[str, Any]) -> str | None:
    session_id = provenance.get("session_id")
    if isinstance(session_id, str):
        return session_id
    return None

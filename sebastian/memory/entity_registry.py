from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select

from sebastian.memory.segmentation import add_entity_terms
from sebastian.memory.types import MemoryStatus
from sebastian.store.models import EntityRecord, RelationCandidateRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class EntityRegistry:
    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def upsert_entity(
        self,
        canonical_name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EntityRecord:
        """Create or update an entity by canonical name.

        If an entity with the same canonical_name already exists, merges aliases
        (union, deduplicated) and updates metadata if provided. Otherwise creates
        a new EntityRecord. Does NOT commit — caller must flush/commit.
        """
        result = await self._session.scalars(
            select(EntityRecord).where(EntityRecord.canonical_name == canonical_name)
        )
        existing = result.first()

        now = datetime.now(UTC)

        if existing is not None:
            merged = list({*existing.aliases, *(aliases or [])})
            existing.aliases = merged
            if metadata is not None:
                existing.entity_metadata = metadata
            existing.updated_at = now
            await self._session.flush()
            return existing

        record = EntityRecord(
            id=str(uuid4()),
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=aliases or [],
            entity_metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def lookup(self, text: str) -> list[EntityRecord]:
        """Return entities whose canonical_name or aliases match text."""
        result = await self._session.scalars(select(EntityRecord))
        all_records = result.all()
        return [
            r for r in all_records
            if r.canonical_name == text or text in r.aliases
        ]

    async def list_relations(
        self,
        *,
        subject_id: str,
        limit: int = 3,
    ) -> list[RelationCandidateRecord]:
        """Return active relation candidates for a subject, newest first.

        Note: lifecycle filter (``valid_until``) deferred to Task F3 backfill;
        for now we only filter on ``status == ACTIVE``.
        """
        statement = (
            select(RelationCandidateRecord)
            .where(
                RelationCandidateRecord.subject_id == subject_id,
                RelationCandidateRecord.status == MemoryStatus.ACTIVE.value,
            )
            .order_by(RelationCandidateRecord.created_at.desc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def sync_jieba_terms(self) -> None:
        """Register all entity canonical names and aliases with jieba."""
        result = await self._session.scalars(select(EntityRecord))
        all_records = result.all()

        terms: list[str] = []
        for record in all_records:
            terms.append(record.canonical_name)
            terms.extend(record.aliases)

        add_entity_terms(terms)

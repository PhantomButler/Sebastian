from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import or_, select

from sebastian.memory.segmentation import add_entity_terms
from sebastian.memory.types import MemoryStatus
from sebastian.store.models import EntityRecord, RelationCandidateRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.retrieval import MemoryRetrievalPlanner


class EntityRegistry:
    def __init__(
        self,
        db_session: AsyncSession,
        *,
        planner: MemoryRetrievalPlanner | None = None,
    ) -> None:
        self._session = db_session
        self._planner = planner

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
            await self._notify_planner_reload()
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
        await self._notify_planner_reload()
        return record

    async def lookup(self, text: str) -> list[EntityRecord]:
        """Return entities whose canonical_name equals text or whose aliases JSON contains text."""
        import json as _json

        from sqlalchemy import func, or_

        # Encode the needle exactly like SQLAlchemy's default JSON serializer
        # (ensure_ascii=True, so "橘猫" is stored as "\u6a58\u732b"). This also
        # safely escapes literal quotes in `text`. SQLAlchemy binds `needle` as
        # a parameter via func.instr, so this is SQL-injection safe.
        needle = _json.dumps(text)
        result = await self._session.scalars(
            select(EntityRecord).where(
                or_(
                    EntityRecord.canonical_name == text,
                    func.instr(func.json(EntityRecord.aliases), needle) > 0,
                )
            )
        )
        return list(result.all())

    async def list_relations(
        self,
        *,
        subject_id: str,
        limit: int = 3,
    ) -> list[RelationCandidateRecord]:
        """Return currently valid active relation candidates for a subject, newest first."""
        now = datetime.now(UTC)
        statement = (
            select(RelationCandidateRecord)
            .where(
                RelationCandidateRecord.subject_id == subject_id,
                RelationCandidateRecord.status == MemoryStatus.ACTIVE.value,
                or_(
                    RelationCandidateRecord.valid_from.is_(None),
                    RelationCandidateRecord.valid_from <= now,
                ),
                or_(
                    RelationCandidateRecord.valid_until.is_(None),
                    RelationCandidateRecord.valid_until > now,
                ),
            )
            .order_by(RelationCandidateRecord.created_at.desc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def snapshot(self, *, limit: int = 64) -> list[EntityRecord]:
        """Return up to *limit* most recently created entities, newest first.

        Used to supply the consolidator with an entity registry overview so the
        LLM can avoid proposing duplicate canonical names.
        """
        statement = select(EntityRecord).order_by(EntityRecord.created_at.desc()).limit(limit)
        result = await self._session.scalars(statement)
        return list(result.all())

    async def list_all_names_and_aliases(self) -> list[str]:
        """Return all canonical_names and aliases as a flat list.

        Shared by sync_jieba_terms() and MemoryRetrievalPlanner
        .bootstrap_entity_triggers(). No deduplication — callers handle dedup.
        """
        result = await self._session.scalars(select(EntityRecord))
        names: list[str] = []
        for record in result.all():
            names.append(record.canonical_name)
            names.extend(record.aliases)
        return names

    async def sync_jieba_terms(self) -> None:
        """Register all entity canonical names and aliases with jieba."""
        terms = await self.list_all_names_and_aliases()
        add_entity_terms(terms)

    async def _notify_planner_reload(self) -> None:
        """Trigger planner trigger-set refresh after a write. No-op if unwired."""
        if self._planner is not None:
            await self._planner.reload_entity_triggers(self)

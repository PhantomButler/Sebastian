from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from sebastian.memory.episode_store import ensure_episode_fts
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.store.models import MemorySlotRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

    from sebastian.memory.slots import SlotRegistry


async def ensure_profile_fts(conn: AsyncConnection) -> None:
    """Create the profile_memories_fts virtual table if it does not exist."""
    await conn.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
            "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
        )
    )


async def _backfill_profile_fts(conn: AsyncConnection) -> None:
    """Index profile_memories rows not yet in the FTS virtual table."""
    from sebastian.memory.segmentation import segment_for_fts

    result = await conn.execute(
        text(
            "SELECT id, content FROM profile_memories "
            "WHERE id NOT IN (SELECT memory_id FROM profile_memories_fts)"
        )
    )
    rows = result.fetchall()
    for row in rows:
        segmented = segment_for_fts(row[1])
        await conn.execute(
            text(
                "INSERT INTO profile_memories_fts(memory_id, content_segmented) "
                "VALUES (:memory_id, :content_segmented)"
            ),
            {"memory_id": row[0], "content_segmented": segmented},
        )


async def init_memory_storage(engine: AsyncEngine) -> None:
    """Initialize memory storage virtual tables. Idempotent. Call after init_db()."""
    async with engine.begin() as conn:
        await ensure_episode_fts(conn)
        await ensure_profile_fts(conn)
        await _backfill_profile_fts(conn)


async def seed_builtin_slots(session: AsyncSession) -> None:
    """Insert MemorySlotRecord rows for every built-in slot; idempotent."""
    existing_rows = await session.execute(select(MemorySlotRecord.slot_id))
    existing = {row[0] for row in existing_rows.all()}
    now = datetime.now(UTC)
    for slot in DEFAULT_SLOT_REGISTRY.list_all():
        if slot.slot_id in existing:
            continue
        session.add(
            MemorySlotRecord(
                slot_id=slot.slot_id,
                scope=slot.scope.value,
                subject_kind=slot.subject_kind,
                cardinality=slot.cardinality.value,
                resolution_policy=slot.resolution_policy.value,
                kind_constraints=[k.value for k in slot.kind_constraints],
                description=slot.description,
                is_builtin=True,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()


async def bootstrap_slot_registry(
    session: AsyncSession,
    registry: SlotRegistry,
) -> None:
    """服务启动时调用：把 memory_slots 表全部数据灌入 registry。"""
    from sebastian.memory.slot_definition_store import SlotDefinitionStore

    store = SlotDefinitionStore(session)
    await registry.bootstrap_from_db(store)

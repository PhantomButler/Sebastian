from __future__ import annotations

from typing import TYPE_CHECKING

from sebastian.memory.episode_store import ensure_episode_fts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


async def init_memory_storage(engine: AsyncEngine) -> None:
    """Initialize memory storage virtual tables. Idempotent. Call after init_db()."""
    async with engine.begin() as conn:
        await ensure_episode_fts(conn)

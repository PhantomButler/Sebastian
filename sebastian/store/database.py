from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine as SyncEngine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _install_sqlite_fk_pragma(engine: AsyncEngine) -> None:
    """Enable SQLite ON DELETE cascade/set-null semantics on every connection."""
    sync_engine: SyncEngine = engine.sync_engine

    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from sebastian.config import settings

        _engine = create_async_engine(settings.database_url, echo=False, future=True)
        _install_sqlite_fk_pragma(_engine)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """Create all tables. Call once at startup."""
    from sebastian.store import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    logger.info("Database initialized")


async def _apply_idempotent_migrations(conn: Any) -> None:
    """Apply best-effort schema patches for columns added after initial create_all.

    Each entry: (table, column, DDL fragment). SQLite only.
    """
    patches: list[tuple[str, str, str]] = [
        ("llm_providers", "thinking_capability", "VARCHAR(20)"),
        ("agent_llm_bindings", "thinking_effort", "VARCHAR(16)"),
        ("memory_decision_log", "input_source", "TEXT"),
        ("memory_decision_log", "session_id", "TEXT"),
        ("profile_memories", "cardinality", "VARCHAR"),
        ("profile_memories", "resolution_policy", "VARCHAR"),
        ("profile_memories", "content_segmented", "VARCHAR DEFAULT ''"),
        ("episode_memories", "valid_from", "DATETIME"),
        ("episode_memories", "valid_until", "DATETIME"),
        ("relation_candidates", "policy_tags", "TEXT"),
        ("relation_candidates", "source", "VARCHAR DEFAULT 'system_derived'"),
        ("memory_slots", "proposed_by", "TEXT"),
        ("memory_slots", "proposed_in_session", "TEXT"),
    ]
    for table, column, ddl in patches:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {row[1] for row in result.fetchall()}
        if column not in existing:
            await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            logger.info("Applied migration: %s.%s", table, column)

    await _drop_obsolete_columns(conn)


async def _drop_obsolete_columns(conn: Any) -> None:
    """删除已废弃的列。idempotent：列不存在时静默跳过。"""
    result = await conn.exec_driver_sql(
        "SELECT name FROM pragma_table_info('agent_llm_bindings') WHERE name = 'thinking_adaptive'"
    )
    if result.first():
        await conn.exec_driver_sql("ALTER TABLE agent_llm_bindings DROP COLUMN thinking_adaptive")
        logger.info("Dropped obsolete column: agent_llm_bindings.thinking_adaptive")

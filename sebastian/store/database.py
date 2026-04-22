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
        ("relation_candidates", "valid_from", "DATETIME"),
        ("relation_candidates", "valid_until", "DATETIME"),
        ("relation_candidates", "updated_at", "DATETIME"),
        ("memory_slots", "proposed_by", "TEXT"),
        ("memory_slots", "proposed_in_session", "TEXT"),
        # tasks 表：新增 agent_type
        ("tasks", "agent_type", "VARCHAR(100) DEFAULT 'sebastian'"),
        # checkpoints 表：新增 session_id 和 agent_type
        ("checkpoints", "session_id", "TEXT DEFAULT ''"),
        ("checkpoints", "agent_type", "VARCHAR(100) DEFAULT 'sebastian'"),
        # session_consolidations：新增增量游标字段
        ("session_consolidations", "last_consolidated_seq", "INTEGER"),
        ("session_consolidations", "last_seen_item_seq", "INTEGER"),
        ("session_consolidations", "last_consolidated_source_seq", "INTEGER"),
        ("session_consolidations", "consolidation_mode", "VARCHAR(50) DEFAULT 'full_session'"),
    ]
    for table, column, ddl in patches:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        rows = result.fetchall()
        if not rows:
            # 表不存在，跳过（create_all 会负责建表）
            continue
        existing = {row[1] for row in rows}
        if column not in existing:
            await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            logger.info("Applied migration: %s.%s", table, column)

    await _apply_idempotent_indexes(conn)
    await _drop_obsolete_columns(conn)
    await _normalize_confidence_types(conn)


async def _normalize_confidence_types(conn: Any) -> None:
    """修复历史 str 型 confidence（SQLite dynamic typing）。

    由于 SQLite 允许 REAL 列存储 text，早期写入路径可能留下 text 型数值，
    导致读出后做 `<` / `-confidence` 比较时抛 TypeError。
    逐表扫描 typeof(confidence) = 'text' 的行并 CAST 回 REAL。
    idempotent：没有 text 行时空跑。
    """
    tables = ("profile_memories", "episode_memories", "relation_candidates")
    for table in tables:
        result = await conn.exec_driver_sql(
            f"UPDATE {table} SET confidence = CAST(confidence AS REAL) "
            f"WHERE typeof(confidence) = 'text'"
        )
        if result.rowcount:
            logger.info("Normalized %d str confidence rows in %s", result.rowcount, table)


async def _apply_idempotent_indexes(conn: Any) -> None:
    """幂等创建 session/timeline 查询索引。"""
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_checkpoints_session ON checkpoints (agent_type, session_id, task_id)",
        "CREATE INDEX IF NOT EXISTS ix_session_consolidations_agent ON session_consolidations (agent_type)",
    ]
    for sql in indexes:
        await conn.exec_driver_sql(sql)


async def _drop_obsolete_columns(conn: Any) -> None:
    """删除已废弃的列。idempotent：列不存在时静默跳过。"""
    result = await conn.exec_driver_sql(
        "SELECT name FROM pragma_table_info('agent_llm_bindings') WHERE name = 'thinking_adaptive'"
    )
    if result.first():
        await conn.exec_driver_sql("ALTER TABLE agent_llm_bindings DROP COLUMN thinking_adaptive")
        logger.info("Dropped obsolete column: agent_llm_bindings.thinking_adaptive")

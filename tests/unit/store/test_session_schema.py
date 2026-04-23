from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def fresh_engine():
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sessions_pk_column_order(fresh_engine):
    """sessions 表 PRIMARY KEY 第一列必须是 agent_type。"""
    async with fresh_engine.begin() as conn:
        row = await conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'")
        )
        sql = (row.scalar() or "").lower()
    m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
    assert m is not None, "sessions 表无 PRIMARY KEY 子句"
    assert m.group(1) == "agent_type", (
        f"sessions PRIMARY KEY 首列应为 agent_type，实际为 {m.group(1)!r}\n{sql}"
    )


@pytest.mark.asyncio
async def test_session_consolidations_pk_column_order(fresh_engine):
    """session_consolidations 表 PRIMARY KEY 第一列必须是 agent_type。"""
    async with fresh_engine.begin() as conn:
        row = await conn.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='session_consolidations'"
            )
        )
        sql = (row.scalar() or "").lower()
    m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
    assert m is not None
    assert m.group(1) == "agent_type", (
        f"session_consolidations PRIMARY KEY 首列应为 agent_type，实际为 {m.group(1)!r}"
    )


@pytest.mark.asyncio
async def test_verify_schema_invariants_passes_on_correct_schema():
    """正确 schema 下 _verify_schema_invariants 不抛出。

    手动构建所有表的「规范」状态（各表 PK 首列为 agent_type），验证检查通过。
    session_todos 的模型当前 PK 顺序有历史问题（session_id 在前），
    此测试绕开 create_all，直接构建符合 spec 的正确 schema 来验证检查器本身的逻辑。
    """
    from sebastian.store.database import _verify_schema_invariants

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # sessions：正确 PK (agent_type, id)
        await conn.exec_driver_sql(
            "CREATE TABLE sessions ("
            "  agent_type TEXT NOT NULL,"
            "  id TEXT NOT NULL,"
            "  title TEXT DEFAULT '',"
            "  PRIMARY KEY (agent_type, id)"
            ")"
        )
        # session_consolidations：正确 PK (agent_type, session_id)
        await conn.exec_driver_sql(
            "CREATE TABLE session_consolidations ("
            "  agent_type TEXT NOT NULL,"
            "  session_id TEXT NOT NULL,"
            "  consolidated_at TEXT NOT NULL,"
            "  worker_version TEXT NOT NULL DEFAULT 'v1',"
            "  consolidation_mode TEXT NOT NULL DEFAULT 'full_session',"
            "  PRIMARY KEY (agent_type, session_id)"
            ")"
        )
        # session_todos：正确 PK (agent_type, session_id)
        await conn.exec_driver_sql(
            "CREATE TABLE session_todos ("
            "  agent_type TEXT NOT NULL,"
            "  session_id TEXT NOT NULL,"
            "  todos TEXT NOT NULL DEFAULT '[]',"
            "  updated_at TEXT NOT NULL,"
            "  PRIMARY KEY (agent_type, session_id)"
            ")"
        )
        # session_items：含 uq_session_items_seq 约束和 ix_session_items_ctx 索引
        await conn.exec_driver_sql(
            "CREATE TABLE session_items ("
            "  id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  session_id TEXT NOT NULL,"
            "  seq INTEGER NOT NULL,"
            "  archived INTEGER NOT NULL DEFAULT 0,"
            "  PRIMARY KEY (id),"
            "  CONSTRAINT uq_session_items_seq UNIQUE (agent_type, session_id, seq)"
            ")"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX ix_session_items_ctx"
            " ON session_items (agent_type, session_id, archived, seq)"
        )
        await _verify_schema_invariants(conn)  # must not raise
    await engine.dispose()


@pytest.mark.asyncio
async def test_verify_schema_invariants_detects_wrong_sessions_pk():
    """sessions 表 PK 顺序错误时 _verify_schema_invariants 抛出 RuntimeError。"""
    from sebastian.store.database import _verify_schema_invariants

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # 手动建出 PK 顺序错误的 sessions 表
        await conn.exec_driver_sql(
            "CREATE TABLE sessions ("
            "  id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  title TEXT DEFAULT '',"
            "  PRIMARY KEY (id, agent_type)"
            ")"
        )
        with pytest.raises(RuntimeError, match="sessions"):
            await _verify_schema_invariants(conn)
    await engine.dispose()


@pytest.mark.asyncio
async def test_rebuild_pk_preserves_data():
    """_rebuild_pk_if_needed 修正 PK 顺序后，原有行数据保持正确。

    使用 session_consolidations 表：Base.metadata 中 PK 为 (agent_type, session_id)，
    手动建出 PK 为 (session_id, agent_type) 的旧版，插入测试行，调用迁移，验证数据无误。
    """
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import _rebuild_pk_if_needed

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    table = "session_consolidations"
    async with engine.begin() as conn:
        # 建出 PK 顺序错误的旧版表（首列 session_id）
        await conn.exec_driver_sql(
            f"CREATE TABLE {table} ("
            "  session_id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  consolidated_at TEXT NOT NULL,"
            "  worker_version TEXT NOT NULL DEFAULT 'v1',"
            "  consolidation_mode TEXT NOT NULL DEFAULT 'full_session',"
            "  PRIMARY KEY (session_id, agent_type)"
            ")"
        )
        # 插入测试行
        await conn.exec_driver_sql(
            f"INSERT INTO {table} (session_id, agent_type, consolidated_at, worker_version)"
            " VALUES ('sid1', 'myagent', '2024-01-01', 'v1')"
        )

    async with engine.begin() as conn:
        await _rebuild_pk_if_needed(conn, table, wrong_first_col="session_id")

        # 验证数据仍然正确（列值未因位置映射错位）
        result = await conn.exec_driver_sql(
            f"SELECT session_id, agent_type, worker_version FROM {table}"
        )
        row = result.fetchone()
        assert row is not None, "重建后数据行丢失"
        assert row[0] == "sid1", f"session_id 列数据错误: {row[0]!r}"
        assert row[1] == "myagent", f"agent_type 列数据错误: {row[1]!r}"
        assert row[2] == "v1", f"worker_version 列数据错误: {row[2]!r}"

        # 验证新表 PK 首列是 agent_type
        pk_result = await conn.execute(
            text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        )
        sql = (pk_result.scalar() or "").lower()
        m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
        assert m is not None, f"重建后 {table} 无 PRIMARY KEY 子句"
        assert m.group(1) == "agent_type", (
            f"重建后 {table} PRIMARY KEY 首列应为 agent_type，实际为 {m.group(1)!r}"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_rebuild_pk_with_existing_indexes_preserves_data():
    """重建带已有索引的旧 sessions 表时，不应因同名 index 冲突失败。"""
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import _rebuild_pk_if_needed

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE sessions ("
            "  id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  title TEXT DEFAULT '',"
            "  goal TEXT DEFAULT '',"
            "  status TEXT DEFAULT 'active',"
            "  depth INTEGER DEFAULT 0,"
            "  parent_session_id TEXT,"
            "  last_activity_at DATETIME,"
            "  created_at DATETIME,"
            "  updated_at DATETIME,"
            "  task_count INTEGER DEFAULT 0,"
            "  active_task_count INTEGER DEFAULT 0,"
            "  next_item_seq INTEGER DEFAULT 1,"
            "  PRIMARY KEY (id, agent_type)"
            ")"
        )
        await conn.exec_driver_sql("CREATE INDEX ix_sessions_agent_type ON sessions (agent_type)")
        await conn.exec_driver_sql(
            "CREATE INDEX ix_sessions_agent_parent_status"
            " ON sessions (agent_type, parent_session_id, status)"
        )
        await conn.exec_driver_sql(
            "INSERT INTO sessions ("
            "  id, agent_type, title, goal, status, depth, last_activity_at,"
            "  created_at, updated_at, task_count, active_task_count, next_item_seq"
            ") VALUES ("
            "  'sid1', 'forge', 'Title', 'Goal', 'active', 2,"
            "  '2026-04-22 00:00:00', '2026-04-22 00:00:00',"
            "  '2026-04-22 00:00:00', 3, 1, 9"
            ")"
        )

    async with engine.begin() as conn:
        await _rebuild_pk_if_needed(conn, "sessions", wrong_first_col="id")

        result = await conn.exec_driver_sql(
            "SELECT agent_type, id, title, goal, task_count, active_task_count, next_item_seq"
            " FROM sessions"
        )
        row = result.fetchone()
        assert row is not None
        assert row == ("forge", "sid1", "Title", "Goal", 3, 1, 9)

        pk_result = await conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'")
        )
        sql = (pk_result.scalar() or "").lower()
        m = re.search(r'primary key\s*\(\s*"?(\w+)"?', sql)
        assert m is not None
        assert m.group(1) == "agent_type"

        idx_result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master"
            " WHERE type='index' AND tbl_name='sessions'"
            " AND name='ix_sessions_agent_type'"
        )
        assert idx_result.fetchone() is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_verify_schema_invariants_detects_missing_ix_session_items_ctx():
    """缺少 ix_session_items_ctx 索引时 _verify_schema_invariants 抛出 RuntimeError。"""
    from sebastian.store.database import _verify_schema_invariants

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # 建出含 uq_session_items_seq 但缺少 ix_session_items_ctx 的 session_items 表
        await conn.exec_driver_sql(
            "CREATE TABLE session_items ("
            "  id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  session_id TEXT NOT NULL,"
            "  seq INTEGER NOT NULL,"
            "  archived INTEGER NOT NULL DEFAULT 0,"
            "  PRIMARY KEY (id),"
            "  CONSTRAINT uq_session_items_seq UNIQUE (agent_type, session_id, seq)"
            ")"
        )
        # 故意不创建 ix_session_items_ctx 索引
        with pytest.raises(RuntimeError, match="ix_session_items_ctx"):
            await _verify_schema_invariants(conn)
    await engine.dispose()


@pytest.mark.asyncio
async def test_verify_schema_invariants_detects_wrong_session_todos_pk():
    """session_todos 表 PK 首列不是 agent_type 时 _verify_schema_invariants 抛出 RuntimeError。"""
    from sebastian.store.database import _verify_schema_invariants

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # 建出 PK 顺序错误的 session_todos 表（首列 session_id）
        await conn.exec_driver_sql(
            "CREATE TABLE session_todos ("
            "  session_id TEXT NOT NULL,"
            "  agent_type TEXT NOT NULL,"
            "  data TEXT DEFAULT '',"
            "  PRIMARY KEY (session_id, agent_type)"
            ")"
        )
        with pytest.raises(RuntimeError, match="session_todos"):
            await _verify_schema_invariants(conn)
    await engine.dispose()

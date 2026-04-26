from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.types import TodoItem
from sebastian.store.todo_store import TodoStore


@pytest.fixture
async def sqlite_session_factory():
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base, _apply_idempotent_migrations

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


@pytest.fixture
def db_todo_store(sqlite_session_factory):
    return TodoStore(db_factory=sqlite_session_factory)


@pytest.mark.asyncio
async def test_missing_todos_returns_empty_list(db_todo_store):
    result = await db_todo_store.read("sebastian", "nonexistent-session")
    assert result == []


@pytest.mark.asyncio
async def test_write_and_read_roundtrip(db_todo_store):
    todos = [
        TodoItem(content="Buy milk", active_form="buying milk", status="pending"),
        TodoItem(content="Walk dog", active_form="walking dog", status="in_progress"),
    ]
    await db_todo_store.write("sebastian", "sess-1", todos)
    result = await db_todo_store.read("sebastian", "sess-1")
    assert len(result) == 2
    assert result[0].content == "Buy milk"
    assert result[1].content == "Walk dog"


@pytest.mark.asyncio
async def test_overwrite_replaces_all(db_todo_store):
    original = [TodoItem(content="Old", active_form="old stuff", status="pending")]
    await db_todo_store.write("sebastian", "sess-1", original)
    new = [TodoItem(content="New", active_form="new stuff", status="completed")]
    await db_todo_store.write("sebastian", "sess-1", new)
    result = await db_todo_store.read("sebastian", "sess-1")
    assert len(result) == 1
    assert result[0].content == "New"


@pytest.mark.asyncio
async def test_agent_session_isolation(db_todo_store):
    t1 = [TodoItem(content="Agent A Todo", active_form="doing A", status="pending")]
    t2 = [TodoItem(content="Agent B Todo", active_form="doing B", status="pending")]
    await db_todo_store.write("agent_a", "sess-1", t1)
    await db_todo_store.write("agent_b", "sess-1", t2)
    result_a = await db_todo_store.read("agent_a", "sess-1")
    result_b = await db_todo_store.read("agent_b", "sess-1")
    assert result_a[0].content == "Agent A Todo"
    assert result_b[0].content == "Agent B Todo"


@pytest.mark.asyncio
async def test_no_filesystem_directories_created(db_todo_store, tmp_path):
    """DB-backed store 不应创建 sessions/{agent}/{session_id}/todos.json。"""
    todos = [TodoItem(content="test", active_form="testing", status="pending")]
    await db_todo_store.write("sebastian", "sess-test", todos)
    # 确认没有创建文件
    for p in tmp_path.rglob("todos.json"):
        raise AssertionError(f"Found unexpected todos.json: {p}")


@pytest.mark.asyncio
async def test_rebuild_fk_drops_orphaned_rows() -> None:
    """_rebuild_if_missing_fk 应删除孤儿 todo（对应 session 不存在），迁移不应抛 FK violation。"""
    import asyncio

    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base, _rebuild_if_missing_fk

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        async with engine.begin() as conn:
            # 建一张没有 FK 约束的老版 session_todos（模拟旧 schema）
            await conn.exec_driver_sql(
                "CREATE TABLE session_todos ("
                "  agent_type VARCHAR NOT NULL,"
                "  session_id VARCHAR NOT NULL,"
                "  todos JSON NOT NULL,"
                "  updated_at DATETIME NOT NULL,"
                "  PRIMARY KEY (agent_type, session_id)"
                ")"
            )
            # 同时建一张空的 sessions 表（供 FK 引用目标）
            await conn.run_sync(
                lambda sync_conn: Base.metadata.tables["sessions"].create(
                    sync_conn, checkfirst=True
                )
            )
            # 写入一条孤儿记录（sessions 表里没有对应行）
            await conn.exec_driver_sql(
                "INSERT INTO session_todos VALUES ('sebastian', 'orphan-session', '[]', '2024-01-01 00:00:00')"
            )

        # 运行迁移 —— 不应抛异常
        async with engine.begin() as conn:
            await _rebuild_if_missing_fk(conn, "session_todos")

        # 迁移后孤儿记录应被删除
        async with engine.begin() as conn:
            result = await conn.exec_driver_sql(
                "SELECT COUNT(*) FROM session_todos WHERE session_id='orphan-session'"
            )
            assert result.fetchone()[0] == 0, (
                "orphaned todo should have been deleted during migration"
            )
    finally:
        await engine.dispose()
        await asyncio.sleep(0)

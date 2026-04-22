from __future__ import annotations

import sqlalchemy
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def sqlite_session_factory():
    import sebastian.store.models  # noqa: F401 — 注册所有 ORM 类到 Base.metadata
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


@pytest.mark.asyncio
async def test_session_storage_tables_exist(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        rows = await session.execute(sqlalchemy.text("PRAGMA table_info(sessions)"))
        columns = {row[1] for row in rows.fetchall()}
        assert {"id", "agent_type", "next_item_seq"}.issubset(columns)


@pytest.mark.asyncio
async def test_session_items_table_exists(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        rows = await session.execute(sqlalchemy.text("PRAGMA table_info(session_items)"))
        columns = {row[1] for row in rows.fetchall()}
        assert {"id", "session_id", "agent_type", "seq", "kind", "archived", "effective_seq"}.issubset(columns)


@pytest.mark.asyncio
async def test_session_todos_table_exists(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        rows = await session.execute(sqlalchemy.text("PRAGMA table_info(session_todos)"))
        columns = {row[1] for row in rows.fetchall()}
        assert {"session_id", "agent_type", "todos"}.issubset(columns)


@pytest.mark.asyncio
async def test_session_consolidations_cursor_fields_exist(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        rows = await session.execute(sqlalchemy.text("PRAGMA table_info(session_consolidations)"))
        columns = {row[1] for row in rows.fetchall()}
        assert {"last_consolidated_seq", "last_seen_item_seq", "last_consolidated_source_seq", "consolidation_mode"}.issubset(columns)


# ── Task 2: Session Records CRUD/List Tests ──────────────────────────────────

from datetime import UTC, datetime, timedelta

from sebastian.core.types import Session, SessionStatus
from sebastian.store.session_store import SessionStore


def _make_session_store(factory):
    """SessionStore 构造：优先 db_factory，兼容测试注入。"""
    return SessionStore(db_factory=factory)


@pytest.mark.asyncio
async def test_create_and_get_session(sqlite_session_factory):
    store = _make_session_store(sqlite_session_factory)
    session = Session(agent_type="sebastian", title="Test Session", goal="do stuff")
    await store.create_session(session)

    loaded = await store.get_session(session.id, "sebastian")
    assert loaded is not None
    assert loaded.title == "Test Session"
    assert loaded.agent_type == "sebastian"
    assert loaded.goal == "do stuff"


@pytest.mark.asyncio
async def test_update_session(sqlite_session_factory):
    store = _make_session_store(sqlite_session_factory)
    session = Session(agent_type="sebastian", title="Old Title")
    await store.create_session(session)

    session.title = "New Title"
    await store.update_session(session)

    loaded = await store.get_session(session.id, "sebastian")
    assert loaded.title == "New Title"


@pytest.mark.asyncio
async def test_list_sessions(sqlite_session_factory):
    store = _make_session_store(sqlite_session_factory)
    s1 = Session(agent_type="sebastian", title="A")
    s2 = Session(agent_type="sebastian", title="B")
    await store.create_session(s1)
    await store.create_session(s2)

    sessions = await store.list_sessions()
    ids = {s["id"] for s in sessions}
    assert s1.id in ids
    assert s2.id in ids


@pytest.mark.asyncio
async def test_list_sessions_by_agent_type(sqlite_session_factory):
    store = _make_session_store(sqlite_session_factory)
    s1 = Session(agent_type="sebastian", title="A")
    s2 = Session(agent_type="other_agent", title="B")
    await store.create_session(s1)
    await store.create_session(s2)

    sessions = await store.list_sessions_by_agent_type("sebastian")
    ids = {s["id"] for s in sessions}
    assert s1.id in ids
    assert s2.id not in ids


@pytest.mark.asyncio
async def test_list_active_children(sqlite_session_factory):
    store = _make_session_store(sqlite_session_factory)
    parent = Session(agent_type="sebastian", title="Parent")
    child_active = Session(
        agent_type="sebastian",
        title="Child Active",
        parent_session_id=parent.id,
        status=SessionStatus.ACTIVE,
    )
    child_completed = Session(
        agent_type="sebastian",
        title="Child Done",
        parent_session_id=parent.id,
        status=SessionStatus.COMPLETED,
    )
    await store.create_session(parent)
    await store.create_session(child_active)
    await store.create_session(child_completed)

    children = await store.list_active_children("sebastian", parent.id)
    ids = {s["id"] for s in children}
    assert child_active.id in ids
    assert child_completed.id not in ids


@pytest.mark.asyncio
async def test_update_activity_transitions_stalled_to_active(sqlite_session_factory):
    store = _make_session_store(sqlite_session_factory)
    session = Session(agent_type="sebastian", title="Stalled", status=SessionStatus.STALLED)
    await store.create_session(session)

    await store.update_activity(session.id, "sebastian")

    loaded = await store.get_session(session.id, "sebastian")
    assert loaded.status == SessionStatus.ACTIVE

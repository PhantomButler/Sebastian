from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.types import Session
from sebastian.store.session_store import SessionStore


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


@pytest.fixture
async def store(sqlite_session_factory):
    return SessionStore(db_factory=sqlite_session_factory)


@pytest.fixture
async def session_in_db(store):
    s = Session(agent_type="sebastian", title="Test")
    await store.create_session(s)
    return s


@pytest.mark.asyncio
async def test_append_items_assigns_contiguous_seq(store, session_in_db):
    """append_timeline_items 分配的 seq 是连续的。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "hello"},
        {"kind": "assistant_message", "role": "assistant", "content": "hi"},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian")
    seqs = sorted(item["seq"] for item in all_items)
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


@pytest.mark.asyncio
async def test_next_item_seq_advances(store, session_in_db):
    """每次 append 后 sessions.next_item_seq 递增。"""
    items = [{"kind": "user_message", "role": "user", "content": "msg"}]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian")
    seqs = sorted(item["seq"] for item in all_items)
    assert seqs == [1, 2]


@pytest.mark.asyncio
async def test_append_message_user_creates_user_message(store, session_in_db):
    await store.append_message(session_in_db.id, "user", "Hello", "sebastian")
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    assert len(items) == 1
    assert items[0]["kind"] == "user_message"
    assert items[0]["role"] == "user"


@pytest.mark.asyncio
async def test_append_message_system_creates_system_event(store, session_in_db):
    await store.append_message(session_in_db.id, "system", "System msg", "sebastian")
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    assert items[0]["kind"] == "system_event"


@pytest.mark.asyncio
async def test_append_message_plain_assistant(store, session_in_db):
    await store.append_message(session_in_db.id, "assistant", "Response", "sebastian")
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    assert items[0]["kind"] == "assistant_message"
    assert items[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_get_context_timeline_items_excludes_archived(store, session_in_db):
    """get_context_timeline_items 返回未归档 item，包含 context_summary。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "msg1", "archived": False},
        {"kind": "user_message", "role": "user", "content": "msg2", "archived": True},
        {"kind": "context_summary", "role": None, "content": "summary", "archived": False,
         "effective_seq": 1, "payload": {"source_seq_start": 1, "source_seq_end": 2}},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    ctx = await store.get_context_timeline_items(session_in_db.id, "sebastian")
    kinds = [i["kind"] for i in ctx]
    assert "user_message" in kinds      # 未归档原文
    assert "context_summary" in kinds   # summary 包含
    # 归档的 msg2 不出现在 content 中（或通过 archived 字段确认）
    archived_items = [i for i in ctx if i.get("archived")]
    assert len(archived_items) == 0


@pytest.mark.asyncio
async def test_get_timeline_items_includes_archived(store, session_in_db):
    """get_timeline_items(include_archived=True) 返回完整历史。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "old", "archived": True},
        {"kind": "user_message", "role": "user", "content": "new", "archived": False},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian", include_archived=True)
    assert len(all_items) == 2


@pytest.mark.asyncio
async def test_get_recent_timeline_items(store, session_in_db):
    """get_recent_timeline_items 返回最近 limit 条未归档 item（正序）。"""
    for i in range(5):
        await store.append_message(session_in_db.id, "user", f"msg{i}", "sebastian")

    recent = await store.get_recent_timeline_items(session_in_db.id, "sebastian", limit=3)
    assert len(recent) == 3
    # 正序（seq 升序）
    seqs = [i["seq"] for i in recent]
    assert seqs == sorted(seqs)
    # 应该是最后 3 条（seq 3, 4, 5）
    assert seqs[-1] == 5


@pytest.mark.asyncio
async def test_get_messages_since(store, session_in_db):
    """get_messages_since 返回 seq > after_seq 的 item，不含 thinking/raw_block。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "msg1"},
        {"kind": "thinking", "role": "assistant", "content": "think"},
        {"kind": "assistant_message", "role": "assistant", "content": "reply"},
        {"kind": "raw_block", "role": None, "content": "raw"},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    since = await store.get_messages_since(session_in_db.id, "sebastian", after_seq=1)
    kinds = [i["kind"] for i in since]
    assert "assistant_message" in kinds
    assert "thinking" not in kinds
    assert "raw_block" not in kinds


@pytest.mark.asyncio
async def test_concurrent_append_no_duplicate_seq(store, session_in_db):
    """并发 append 后 seq 不重复且无空洞。"""
    async def append_one(content: str) -> None:
        await store.append_timeline_items(
            session_in_db.id, "sebastian",
            [{"kind": "user_message", "role": "user", "content": content}],
        )

    await asyncio.gather(*[append_one(f"msg{i}") for i in range(5)])

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian")
    seqs = sorted(item["seq"] for item in all_items)
    assert len(seqs) == len(set(seqs)), "seq 有重复"
    assert seqs == list(range(1, 6)), f"seq 有空洞: {seqs}"

from __future__ import annotations

import asyncio

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


@pytest.mark.asyncio
async def test_append_message_preserves_turn_id_from_blocks(store, session_in_db):
    """append_message 传入带 turn_id 的 blocks 时，写入 DB 的 item 应保留 turn_id。"""
    blocks = [
        {
            "type": "thinking",
            "thinking": "thought",
            "turn_id": "01JQTEST00000000000000000A",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "type": "text",
            "text": "reply",
            "turn_id": "01JQTEST00000000000000000A",
            "provider_call_index": 0,
            "block_index": 1,
        },
    ]
    await store.append_message(
        session_in_db.id, "assistant", "reply",
        agent_type="sebastian", blocks=blocks,
    )
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    thinking = next(i for i in items if i["kind"] == "thinking")
    text = next(i for i in items if i["kind"] == "assistant_message")

    assert thinking["turn_id"] == "01JQTEST00000000000000000A"
    assert thinking["provider_call_index"] == 0
    assert thinking["block_index"] == 0
    assert text["turn_id"] == "01JQTEST00000000000000000A"
    assert text["block_index"] == 1


@pytest.mark.asyncio
async def test_append_message_tool_use_block_content_is_json_input(store, session_in_db):
    """tool_use/tool block 的 content 字段应为 JSON 序列化的 input，不为空。"""
    blocks = [
        {
            "type": "tool_use",
            "tool_id": "tc1",
            "name": "my_tool",
            "input": {"key": "value"},
            "turn_id": "01JQTEST00000000000000000B",
            "provider_call_index": 0,
            "block_index": 0,
        }
    ]
    await store.append_message(
        session_in_db.id, "assistant", "",
        agent_type="sebastian", blocks=blocks,
    )
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    tool_call = next(i for i in items if i["kind"] == "tool_call")
    import json
    assert tool_call["content"] == json.dumps({"key": "value"})


@pytest.mark.asyncio
async def test_get_messages_since_excludes_system_event(store, session_in_db):
    """get_messages_since 不返回 system_event 类型。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "hello"},
        {"kind": "system_event", "role": "system", "content": "session started"},
        {"kind": "assistant_message", "role": "assistant", "content": "hi"},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    since = await store.get_messages_since(session_in_db.id, "sebastian", after_seq=0)
    kinds = [i["kind"] for i in since]
    assert "system_event" not in kinds, f"system_event should be excluded, got: {kinds}"
    assert "user_message" in kinds
    assert "assistant_message" in kinds


@pytest.mark.asyncio
async def test_get_context_items_excludes_system_event(store, session_in_db):
    """get_context_timeline_items 不返回 system_event（影响 LLM context）。"""
    items = [
        {"kind": "user_message", "role": "user", "content": "hello"},
        {"kind": "system_event", "role": "system", "content": "started"},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    ctx = await store.get_context_timeline_items(session_in_db.id, "sebastian")
    kinds = [i["kind"] for i in ctx]
    assert "system_event" not in kinds, f"system_event should not be in context: {kinds}"


@pytest.mark.asyncio
async def test_get_timeline_items_orders_by_effective_seq_then_seq(store, session_in_db):
    """get_timeline_items 按 (effective_seq, seq) 排序，context_summary 出现在原位。

    场景：5 条普通消息 seq=1..5（effective_seq 同 seq）；
    再插入一条 context_summary，effective_seq=3，seq=6。
    排序后该 summary 应紧跟 seq=3 的消息之后，出现在 seq=4 的消息之前。
    """
    from typing import Any
    # 写 5 条普通 item（seq=1..5，effective_seq 同 seq）
    items = [{"kind": "user_message", "role": "user", "content": f"msg{i}"} for i in range(5)]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    # 插入一条 effective_seq=3 的 context_summary（seq=6，但逻辑位置在 seq=3 处）
    summary: dict[str, Any] = {
        "kind": "context_summary",
        "role": None,
        "content": "summary",
        "effective_seq": 3,
        "payload": {"source_seq_start": 1, "source_seq_end": 3},
    }
    await store.append_timeline_items(session_in_db.id, "sebastian", [summary])

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian")
    kinds = [i["kind"] for i in all_items]
    # summary（effective_seq=3, seq=6）排在 seq=3 的 user_message 之后、seq=4 之前
    summary_idx = next(i for i, item in enumerate(all_items) if item["kind"] == "context_summary")
    msg4_idx = next(
        i for i, item in enumerate(all_items)
        if item["kind"] == "user_message" and item["seq"] == 4
    )
    assert summary_idx < msg4_idx, (
        f"context_summary (effective_seq=3) should appear before seq=4 item; "
        f"got order: {[(item['kind'], item['seq']) for item in all_items]}"
    )


@pytest.mark.asyncio
async def test_get_context_with_thinking_excludes_system_event(store, session_in_db):
    """get_context_messages include_thinking=True 不应将 system_event 混入投影。

    A2: get_context_items_with_thinking 的 excluded 集合遗漏了 system_event，
    导致 system_event 打断同一 turn 内 thinking + assistant_message 的分组，
    产生两条 assistant 消息而非一条。
    """
    items = [
        {"kind": "user_message", "role": "user", "content": "hi",
         "turn_id": "t1", "provider_call_index": 0, "block_index": 0},
        {"kind": "thinking", "role": "assistant", "content": "thoughts",
         "turn_id": "t1", "provider_call_index": 0, "block_index": 1,
         "payload": {"signature": "sig1"}},
        # system_event 不属于 LLM 上下文，不应出现在任何 context 视图
        {"kind": "system_event", "role": "system", "content": "internal marker"},
        {"kind": "assistant_message", "role": "assistant", "content": "reply",
         "turn_id": "t1", "provider_call_index": 0, "block_index": 2},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    msgs = await store.get_context_messages(
        session_in_db.id, "sebastian", "anthropic", include_thinking=True
    )

    # system_event 内容不应出现在任何 message 中
    assert "internal marker" not in str(msgs), "system_event leaked into context messages"

    # thinking 和 assistant_message 同属 t1/pci=0，应合并在同一 assistant 消息里
    asst_msgs = [m for m in msgs if m.get("role") == "assistant"]
    assert len(asst_msgs) == 1, (
        f"system_event broke assistant grouping; expected 1 assistant msg, got {len(asst_msgs)}: {asst_msgs}"
    )
    content = asst_msgs[0].get("content", [])
    assert isinstance(content, list), "Assistant content should be a block list"
    block_types = [b.get("type") for b in content]
    assert "thinking" in block_types, f"thinking block missing: {block_types}"
    assert "text" in block_types, f"text block missing: {block_types}"


@pytest.mark.asyncio
async def test_effective_seq_zero_preserved(store, session_in_db):
    """effective_seq=0 写入后应保留 0，不被 `or seq` 替换。

    C1: `eff_seq = item.get('effective_seq') or seq` 当 effective_seq=0 时
    erroneously 回退到 seq；应改为 is None 判断。
    """
    items = [
        {
            "kind": "context_summary", "role": None, "content": "summary",
            "effective_seq": 0,
            "payload": {"source_seq_start": 0, "source_seq_end": 0},
        }
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    all_items = await store.get_timeline_items(session_in_db.id, "sebastian")
    summary = next(i for i in all_items if i["kind"] == "context_summary")
    assert summary["effective_seq"] == 0, (
        f"effective_seq should be 0, got {summary['effective_seq']} "
        f"(likely overridden by `or seq` falsy check)"
    )


@pytest.mark.asyncio
async def test_get_recent_items_orders_by_effective_seq(store, session_in_db):
    """get_recent_timeline_items 含 context_summary 时按 (effective_seq, seq) 排序。

    C2: 当前仅按 seq.desc() 取 top-N 再 sort(seq)，
    context_summary 的 effective_seq 被忽略，顺序与 get_context_items 不一致。
    """
    base_items = [
        {"kind": "user_message", "role": "user", "content": f"msg{i}"}
        for i in range(5)
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", base_items)

    # context_summary: seq=6, effective_seq=2（逻辑上属于 seq=2 位置）
    summary = {
        "kind": "context_summary", "role": None, "content": "summary",
        "effective_seq": 2,
        "payload": {"source_seq_start": 1, "source_seq_end": 2},
    }
    await store.append_timeline_items(session_in_db.id, "sebastian", [summary])

    recent = await store.get_recent_timeline_items(session_in_db.id, "sebastian", limit=6)
    effective_seqs = [i["effective_seq"] for i in recent]
    assert effective_seqs == sorted(effective_seqs), (
        f"get_recent_items not sorted by effective_seq; got: {effective_seqs}"
    )

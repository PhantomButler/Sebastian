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
        await asyncio.sleep(0)


@pytest.fixture
async def store(sqlite_session_factory):
    return SessionStore(db_factory=sqlite_session_factory)


@pytest.fixture
async def session_in_db(store):
    s = Session(agent_type="sebastian", title="Test")
    await store.create_session(s)
    return s


# ── 默认上下文不含 thinking ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_context_excludes_thinking(store, session_in_db):
    items = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "hello",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "kind": "thinking",
            "role": "assistant",
            "content": "hmm",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 1,
            "payload": {"signature": "sig1"},
        },
        {
            "kind": "assistant_message",
            "role": "assistant",
            "content": "hi",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 2,
        },
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    msgs = await store.get_context_messages(session_in_db.id, "sebastian", "anthropic")
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    # thinking 不在 context messages 里（默认 include_thinking=False）
    contents = str(msgs)
    assert "hmm" not in contents  # thinking content 不出现


# ── Anthropic 投影 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_tool_call_projection(store, session_in_db):
    """tool_call + tool_result 投影为合法 Anthropic block 序列。"""
    items = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "use tool",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "kind": "tool_call",
            "role": "assistant",
            "content": "",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 1,
            "payload": {"tool_call_id": "tc1", "tool_name": "my_tool", "input": {"x": 1}},
        },
        {
            "kind": "tool_result",
            "role": "tool",
            "content": "",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 2,
            "payload": {
                "tool_call_id": "tc1",
                "model_content": "result_text",
                "display": "Result: result_text",
            },
        },
        {
            "kind": "assistant_message",
            "role": "assistant",
            "content": "done",
            "turn_id": "t1",
            "provider_call_index": 1,
            "block_index": 0,
        },
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    msgs = await store.get_context_messages(session_in_db.id, "sebastian", "anthropic")

    # user message
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "use tool"

    # assistant message with tool_use block
    asst_with_tool = next(
        m for m in msgs if m["role"] == "assistant" and isinstance(m["content"], list)
    )
    tool_use_block = next(b for b in asst_with_tool["content"] if b.get("type") == "tool_use")
    assert tool_use_block["id"] == "tc1"
    assert tool_use_block["name"] == "my_tool"
    assert tool_use_block["input"] == {"x": 1}

    # user message with tool_result block
    user_with_result = next(
        m
        for m in msgs
        if m["role"] == "user"
        and isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    )
    result_block = next(b for b in user_with_result["content"] if b["type"] == "tool_result")
    assert result_block["tool_use_id"] == "tc1"
    assert result_block["content"] == "result_text"


# ── OpenAI 投影 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_tool_call_projection(store, session_in_db):
    """OpenAI 格式：assistant tool_calls + role=tool messages。"""
    items = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "use tool",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "kind": "tool_call",
            "role": "assistant",
            "content": "",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 1,
            "payload": {"tool_call_id": "tc1", "tool_name": "my_tool", "input": {"x": 1}},
        },
        {
            "kind": "tool_result",
            "role": "tool",
            "content": "",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 2,
            "payload": {"tool_call_id": "tc1", "model_content": "result_text"},
        },
        {
            "kind": "assistant_message",
            "role": "assistant",
            "content": "done",
            "turn_id": "t1",
            "provider_call_index": 1,
            "block_index": 0,
        },
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    msgs = await store.get_context_messages(session_in_db.id, "sebastian", "openai")

    # assistant with tool_calls
    asst = next(m for m in msgs if m["role"] == "assistant" and m.get("tool_calls"))
    assert asst["tool_calls"][0]["id"] == "tc1"
    assert asst["tool_calls"][0]["function"]["name"] == "my_tool"

    # tool result message
    tool_msg = next(m for m in msgs if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "tc1"
    assert tool_msg["content"] == "result_text"


# ── include_thinking=True 保留 Anthropic signature ─────────────────────────


@pytest.mark.asyncio
async def test_anthropic_include_thinking_preserves_signature(store, session_in_db):
    items = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "think",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "kind": "thinking",
            "role": "assistant",
            "content": "deep thoughts",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 1,
            "payload": {"signature": "sig_abc"},
        },
        {
            "kind": "assistant_message",
            "role": "assistant",
            "content": "answer",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 2,
        },
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    msgs = await store.get_context_messages(
        session_in_db.id, "sebastian", "anthropic", include_thinking=True
    )

    asst_msg = next(m for m in msgs if m["role"] == "assistant")
    assert isinstance(asst_msg["content"], list)
    thinking_block = next(b for b in asst_msg["content"] if b.get("type") == "thinking")
    assert thinking_block["thinking"] == "deep thoughts"
    assert thinking_block["signature"] == "sig_abc"


# ── context_summary 按 effective_seq 出现在正确位置 ──────────────────────


@pytest.mark.asyncio
async def test_context_summary_effective_seq_ordering(store, session_in_db):
    """context_summary.effective_seq < 后续原文 seq，summary 应排在前面。"""
    items = [
        # 已归档的旧消息（archived=True，不出现在 context）
        {"kind": "user_message", "role": "user", "content": "old1", "archived": True},
        # context_summary: effective_seq = 1（指向被压缩范围起点）
        {
            "kind": "context_summary",
            "role": None,
            "content": "Summary of old",
            "archived": False,
            "effective_seq": 1,
            "payload": {"source_seq_start": 1, "source_seq_end": 2},
        },
        # 新的未归档消息，seq=3，effective_seq=3
        {"kind": "user_message", "role": "user", "content": "new1", "archived": False},
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items)

    ctx = await store.get_context_timeline_items(session_in_db.id, "sebastian")
    kinds = [i["kind"] for i in ctx]
    # summary 应在 new user_message 前面
    assert kinds.index("context_summary") < kinds.index("user_message")


# ── legacy messages 投影 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_messages_role_content_only(store, session_in_db):
    """build_legacy_messages：只有 role/content，不含 provider-specific blocks。"""
    from sebastian.store.session_context import build_legacy_messages

    items_input = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "hello",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "kind": "tool_call",
            "role": "assistant",
            "content": "",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 1,
            "payload": {"tool_call_id": "tc1", "tool_name": "my_tool", "input": {}},
        },
        {
            "kind": "assistant_message",
            "role": "assistant",
            "content": "hi",
            "turn_id": "t1",
            "provider_call_index": 1,
            "block_index": 0,
        },
    ]
    await store.append_timeline_items(session_in_db.id, "sebastian", items_input)
    all_items = await store.get_context_timeline_items(session_in_db.id, "sebastian")

    legacy = build_legacy_messages(all_items)

    # 只包含 user_message 和 assistant_message，不包含 tool_call
    roles = [m["role"] for m in legacy]
    assert "user" in roles
    assert "assistant" in roles
    assert "tool" not in roles  # tool_result 不出现

    # content 必须是字符串（不是 list）
    for msg in legacy:
        assert isinstance(msg["content"], str), f"content should be str: {msg}"

    # 不含 tool_calls 字段
    for msg in legacy:
        assert "tool_calls" not in msg


def test_openai_mixed_tool_and_text_single_assistant_message():
    """同一 turn 含 tool_calls 和文本时，OpenAI 投影只产生一条 assistant 消息。"""
    from sebastian.store.session_context import build_context_messages

    items = [
        {
            "kind": "assistant_message",
            "role": "assistant",
            "content": "I'll use the tool.",
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 0,
            "seq": 1,
            "effective_seq": 1,
            "archived": False,
            "payload": {},
        },
        {
            "kind": "tool_call",
            "role": "assistant",
            "content": '{"q": "weather"}',
            "turn_id": "t1",
            "provider_call_index": 0,
            "block_index": 1,
            "seq": 2,
            "effective_seq": 2,
            "archived": False,
            "payload": {
                "tool_call_id": "tc1",
                "tool_name": "search",
                "input": {"q": "weather"},
            },
        },
    ]
    messages = build_context_messages(items, provider_format="openai")

    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1, (
        f"Expected 1 assistant message, got {len(assistant_msgs)}: {assistant_msgs}"
    )
    msg = assistant_msgs[0]
    assert msg.get("tool_calls"), "Should have tool_calls"
    assert msg.get("content") == "I'll use the tool.", "Text should be in content field"

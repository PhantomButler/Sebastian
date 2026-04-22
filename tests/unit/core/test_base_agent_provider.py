from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from sebastian.core.stream_events import (
    ProviderCallEnd,
    ProviderCallStart,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ToolCallBlockStart,
    ToolCallReady,
)
from tests.unit.core.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_base_agent_uses_injected_provider() -> None:
    """BaseAgent passes the injected LLMProvider to AgentLoop."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Hello from sub."),
            TextBlockStop(block_id="b0_0", text="Hello from sub."),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        provider=provider,
    )

    result = await agent.run("hi", session_id="test_sess_01")
    assert result == "Hello from sub."
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_stream_inner_sets_turn_id_and_pci() -> None:
    """_stream_inner 写入的 assistant items 应携带非空 turn_id 和正确的 provider_call_index。

    2-iteration 流程:
      iteration 0: ProviderCallStart(0), ToolCallReady (tool_use), ProviderCallEnd(tool_use)
      iteration 1: ProviderCallStart(1), TextBlockStop("done"), ProviderCallEnd(end_turn)
    """
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    # Turn 0: tool call; Turn 1: text reply
    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="noop"),
            ToolCallReady(block_id="b0_0", tool_id="toolu_1", name="noop", inputs={}),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="done"),
            TextBlockStop(block_id="b1_0", text="done"),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    # Gate mock: noop tool returns success
    gate = MagicMock()
    tool_result = MagicMock()
    tool_result.ok = True
    tool_result.output = "noop_result"
    tool_result.display = "noop_result"
    tool_result.empty_hint = None
    tool_result.error = None
    gate.call = AsyncMock(return_value=tool_result)
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(
        gate=gate,
        session_store=session_store,
        provider=provider,
    )

    result = await agent.run("hi", session_id="test_sess_pci")
    assert result == "done"

    # append_message is called once for user msg, once for assistant TurnDone
    calls = session_store.append_message.call_args_list
    assistant_calls = [c for c in calls if c.args[1] == "assistant"]
    assert len(assistant_calls) == 1

    # Extract blocks from the TurnDone assistant call
    blocks = assistant_calls[0].kwargs.get("blocks") or []
    assert len(blocks) >= 2, f"Expected at least 2 blocks, got: {blocks}"

    # All blocks share the same turn_id (26-char ULID)
    turn_ids = {b["turn_id"] for b in blocks}
    assert len(turn_ids) == 1, f"Expected one unique turn_id, got: {turn_ids}"
    turn_id = next(iter(turn_ids))
    assert len(turn_id) == 26, f"turn_id should be 26-char ULID, got: {turn_id!r}"

    # Tool block is from iteration 0
    tool_blocks = [b for b in blocks if b["type"] == "tool"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0]["provider_call_index"] == 0

    # Text block is from iteration 1
    text_blocks = [b for b in blocks if b["type"] == "text"]
    assert len(text_blocks) == 1
    assert text_blocks[0]["provider_call_index"] == 1


@pytest.mark.asyncio
async def test_cancel_session_flushes_pending_blocks() -> None:
    """cancel_session 后 finally 块应 flush 已缓冲的 assistant_blocks，不丢 thinking/tool blocks。"""
    import asyncio

    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    # Provider yields a thinking block, then hangs (never resolves)
    hang_event = asyncio.Event()

    from collections.abc import AsyncGenerator
    from typing import Any

    from sebastian.core.stream_events import LLMStreamEvent
    from sebastian.llm.provider import LLMProvider

    class SlowProvider(LLMProvider):
        """Yields a ThinkingBlockStop then blocks forever until cancelled."""

        message_format = "anthropic"
        call_count = 0

        async def stream(
            self,
            *,
            system: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            model: str,
            max_tokens: int,
            block_id_prefix: str = "",
            thinking_effort: str | None = None,
        ) -> AsyncGenerator[LLMStreamEvent, None]:
            self.call_count += 1
            yield ThinkingBlockStart(block_id="b0_0")
            yield ThinkingBlockStop(block_id="b0_0", thinking="I am thinking...", signature=None)
            # Block until cancelled
            await hang_event.wait()

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    gate = MagicMock()
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    provider = SlowProvider()
    agent = TestAgent(
        gate=gate,
        session_store=session_store,
        provider=provider,
    )

    # Start the run task and let it reach the hang point
    run_task = asyncio.create_task(agent.run("hi", session_id="test_sess_cancel"))
    # Give the coroutine time to process the thinking block and reach the hang
    await asyncio.sleep(0.05)

    # Cancel via cancel_session
    await agent.cancel_session("test_sess_cancel", intent="cancel")

    # Wait for the run task to finish
    try:
        await asyncio.wait_for(run_task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # append_message should have been called for the flushed assistant blocks
    calls = session_store.append_message.call_args_list
    assistant_calls = [c for c in calls if c.args[1] == "assistant"]
    assert len(assistant_calls) >= 1, "Expected at least one assistant append_message call"

    # The flushed call should include the thinking block
    flushed_call = assistant_calls[-1]
    blocks = flushed_call.kwargs.get("blocks") or []
    thinking_blocks = [b for b in blocks if b["type"] == "thinking"]
    assert len(thinking_blocks) >= 1, (
        f"Expected thinking block in flushed blocks, got: {blocks}"
    )

    # Verify thinking block has correct turn_id, provider_call_index, and block_index
    thinking_block = thinking_blocks[0]
    assert thinking_block["turn_id"] is not None
    assert len(thinking_block["turn_id"]) == 26, (
        f"turn_id should be 26-char ULID, got: {thinking_block['turn_id']!r}"
    )
    assert thinking_block["provider_call_index"] == 0
    assert thinking_block["block_index"] == 0


@pytest.mark.asyncio
async def test_tool_call_block_uses_canonical_field_names() -> None:
    """ToolCallReady → blocks 中的 tool 记录使用 tool_call_id/tool_name/input(dict)。

    A1: 写入端字段名必须与 session_context.py 读取端一致。
    """
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_42", name="search"),
            ToolCallReady(block_id="b0_0", tool_id="toolu_42", name="search", inputs={"q": "test"}),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="done"),
            TextBlockStop(block_id="b1_0", text="done"),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are test."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    gate = MagicMock()
    tr = MagicMock()
    tr.ok = True
    tr.output = "search_result"
    tr.display = "search_result"
    tr.empty_hint = None
    tr.error = None
    gate.call = AsyncMock(return_value=tr)
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(gate=gate, session_store=session_store, provider=provider)
    await agent.run("hi", session_id="sess_a1_fields")

    calls = session_store.append_message.call_args_list
    assistant_calls = [c for c in calls if c.args[1] == "assistant"]
    blocks = assistant_calls[-1].kwargs.get("blocks") or []
    tool_blocks = [b for b in blocks if b.get("type") == "tool"]
    assert len(tool_blocks) == 1, f"Expected 1 tool block, got: {tool_blocks}"
    tb = tool_blocks[0]

    # 字段名必须是 tool_call_id（不是 tool_id）
    assert "tool_call_id" in tb, f"Expected 'tool_call_id', got keys: {list(tb.keys())}"
    assert "tool_id" not in tb, f"Unexpected 'tool_id' key; should be 'tool_call_id'"
    assert tb["tool_call_id"] == "toolu_42"

    # 字段名必须是 tool_name（不是 name）
    assert "tool_name" in tb, f"Expected 'tool_name', got keys: {list(tb.keys())}"
    assert "name" not in tb, f"Unexpected 'name' key; should be 'tool_name'"
    assert tb["tool_name"] == "search"

    # input 必须是 dict，不是 JSON 字符串
    assert isinstance(tb["input"], dict), (
        f"input should be dict, got {type(tb['input'])}: {tb['input']!r}"
    )
    assert tb["input"] == {"q": "test"}


@pytest.mark.asyncio
async def test_turn_done_flushes_tool_result_block() -> None:
    """TurnDone flush 的 blocks 中必须包含 type=tool_result 记录。

    B1: spec 要求 tool_result 作为独立 item 入库，供会话恢复时重建 LLM 上下文。
    """
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_99", name="calc"),
            ToolCallReady(block_id="b0_0", tool_id="toolu_99", name="calc", inputs={"x": 1}),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="42"),
            TextBlockStop(block_id="b1_0", text="42"),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are test."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    gate = MagicMock()
    tr = MagicMock()
    tr.ok = True
    tr.output = "42"
    tr.display = "Result: 42"
    tr.empty_hint = None
    tr.error = None
    gate.call = AsyncMock(return_value=tr)
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(gate=gate, session_store=session_store, provider=provider)
    await agent.run("calc 1", session_id="sess_b1_result")

    calls = session_store.append_message.call_args_list
    assistant_calls = [c for c in calls if c.args[1] == "assistant"]
    blocks = assistant_calls[-1].kwargs.get("blocks") or []

    # B1: 必须存在 type=tool_result 的 block
    result_blocks = [b for b in blocks if b.get("type") == "tool_result"]
    assert len(result_blocks) >= 1, (
        f"Expected ≥1 tool_result block, got block types: {[b.get('type') for b in blocks]}"
    )
    rb = result_blocks[0]
    assert rb.get("tool_call_id") == "toolu_99", f"tool_call_id mismatch: {rb}"
    assert rb.get("model_content") == "42", f"model_content should be '42': {rb}"

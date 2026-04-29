from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ToolCallBlockStart,
    ToolCallReady,
)
from sebastian.llm.provider import LLMProvider
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
async def test_stream_inner_sets_assistant_turn_id_and_pci() -> None:
    """_stream_inner 写入的 assistant items 应携带非空 assistant_turn_id。

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

    # All blocks share the same assistant_turn_id (26-char ULID)
    assistant_turn_ids = {b["assistant_turn_id"] for b in blocks}
    assert len(assistant_turn_ids) == 1, (
        f"Expected one unique assistant_turn_id, got: {assistant_turn_ids}"
    )
    assistant_turn_id = next(iter(assistant_turn_ids))
    assert len(assistant_turn_id) == 26, (
        f"assistant_turn_id should be 26-char ULID, got: {assistant_turn_id!r}"
    )

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
    """cancel_session 后 finally 块应 flush 已缓冲 blocks。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    # Provider yields a thinking block, then hangs (never resolves)
    hang_event = asyncio.Event()

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
    except (asyncio.CancelledError, TimeoutError):
        pass

    # append_message should have been called for the flushed assistant blocks
    calls = session_store.append_message.call_args_list
    assistant_calls = [c for c in calls if c.args[1] == "assistant"]
    assert len(assistant_calls) >= 1, "Expected at least one assistant append_message call"

    # The flushed call should include the thinking block
    flushed_call = assistant_calls[-1]
    blocks = flushed_call.kwargs.get("blocks") or []
    thinking_blocks = [b for b in blocks if b["type"] == "thinking"]
    assert len(thinking_blocks) >= 1, f"Expected thinking block in flushed blocks, got: {blocks}"

    # Verify thinking block has correct assistant_turn_id, provider_call_index, and block_index
    thinking_block = thinking_blocks[0]
    assert thinking_block["assistant_turn_id"] is not None
    assert len(thinking_block["assistant_turn_id"]) == 26, (
        f"assistant_turn_id should be 26-char ULID, got: {thinking_block['assistant_turn_id']!r}"
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
    assert "tool_id" not in tb, "Unexpected 'tool_id' key; should be 'tool_call_id'"
    assert tb["tool_call_id"] == "toolu_42"

    # 字段名必须是 tool_name（不是 name）
    assert "tool_name" in tb, f"Expected 'tool_name', got keys: {list(tb.keys())}"
    assert "name" not in tb, "Unexpected 'name' key; should be 'tool_name'"
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


@pytest.mark.asyncio
async def test_tool_result_model_content_uses_llm_facing_string() -> None:
    """持久化 model_content 必须与 AgentLoop 喂给 LLM 的字符串一致。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_json", name="inspect"),
            ToolCallReady(
                block_id="b0_0",
                tool_id="toolu_json",
                name="inspect",
                inputs={},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            ToolCallBlockStart(block_id="b1_0", tool_id="toolu_empty", name="empty"),
            ToolCallReady(
                block_id="b1_0",
                tool_id="toolu_empty",
                name="empty",
                inputs={},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b2_0"),
            TextDelta(block_id="b2_0", delta="done"),
            TextBlockStop(block_id="b2_0", text="done"),
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

    first = MagicMock()
    first.ok = True
    first.output = {"stdout": "ok"}
    first.display = "human ok"
    first.empty_hint = None
    first.error = None

    second = MagicMock()
    second.ok = True
    second.output = []
    second.display = ""
    second.empty_hint = "No rows found"
    second.error = None

    gate = MagicMock()
    gate.call = AsyncMock(side_effect=[first, second])
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(gate=gate, session_store=session_store, provider=provider)
    await agent.run("inspect", session_id="sess_model_content")

    assistant_calls = [
        c for c in session_store.append_message.call_args_list if c.args[1] == "assistant"
    ]
    blocks = assistant_calls[-1].kwargs.get("blocks") or []
    result_blocks = [b for b in blocks if b.get("type") == "tool_result"]

    json_result = next(b for b in result_blocks if b["tool_call_id"] == "toolu_json")
    empty_result = next(b for b in result_blocks if b["tool_call_id"] == "toolu_empty")
    assert json_result["model_content"] == '{"stdout": "ok"}'
    assert empty_result["model_content"] == "No rows found"


@pytest.mark.asyncio
async def test_send_file_artifact_realtime_tool_result_does_not_leak_to_provider() -> None:
    """AgentLoop 实时回灌给 provider 的 tool_result 也必须走 artifact 窄通道。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_file", name="send_file"),
            ToolCallReady(
                block_id="b0_0",
                tool_id="toolu_file",
                name="send_file",
                inputs={"file_path": "test.txt"},
            ),
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

    tool_result = MagicMock()
    tool_result.ok = True
    tool_result.output = {
        "artifact": {
            "kind": "text_file",
            "attachment_id": "att-private",
            "filename": "test.txt",
            "mime_type": "text/plain",
            "size_bytes": 25,
            "download_url": "/api/v1/attachments/att-private",
            "text_excerpt": "private file content",
        }
    }
    tool_result.display = "已向用户发送文件 test.txt"
    tool_result.empty_hint = None
    tool_result.error = None

    gate = MagicMock()
    gate.call = AsyncMock(return_value=tool_result)
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(gate=gate, session_store=session_store, provider=provider)
    await agent.run("send file", session_id="sess_send_file_realtime")

    second_messages = provider.last_messages
    tool_result_message = second_messages[-1]
    content = tool_result_message["content"][0]["content"]
    assert content == "已向用户发送文件 test.txt"
    assert "artifact" not in content
    assert "attachment_id" not in content
    assert "download_url" not in content
    assert "text_excerpt" not in content
    assert "private file content" not in content


@pytest.mark.asyncio
async def test_tool_dispatch_exception_persists_failed_tool_result() -> None:
    """工具抛异常时，DB flush 中也必须有匹配的失败 tool_result。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_fail", name="boom"),
            ToolCallReady(block_id="b0_0", tool_id="toolu_fail", name="boom", inputs={}),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="recovered"),
            TextBlockStop(block_id="b1_0", text="recovered"),
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
    gate.call = AsyncMock(side_effect=RuntimeError("tool exploded"))
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(gate=gate, session_store=session_store, provider=provider)
    await agent.run("boom", session_id="sess_tool_failure")

    assistant_calls = [
        c for c in session_store.append_message.call_args_list if c.args[1] == "assistant"
    ]
    blocks = assistant_calls[-1].kwargs.get("blocks") or []
    tool_call = next(b for b in blocks if b.get("type") == "tool")
    tool_result = next(b for b in blocks if b.get("type") == "tool_result")

    assert tool_call["tool_call_id"] == "toolu_fail"
    assert tool_result["tool_call_id"] == "toolu_fail"
    assert tool_result["ok"] is False
    assert tool_result["model_content"] == "Error: tool exploded"
    assert tool_result["error"] == "tool exploded"


@pytest.mark.asyncio
async def test_exchange_id_propagated_to_all_blocks() -> None:
    """db_factory 存在时，run_streaming 应为该 exchange 分配 exchange_id/exchange_index，
    并将其传递给 user 消息和 assistant 消息的所有 blocks。
    """
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Hi!"),
            TextBlockStop(block_id="b0_0", text="Hi!"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_context_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()
    session_store.allocate_exchange = AsyncMock(return_value=("01JEXCHANGE0000000000000001", 1))

    # Pass a non-None db_factory to trigger the allocate_exchange path
    fake_db_factory = MagicMock()

    gate = MagicMock()
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(
        gate=gate,
        session_store=session_store,
        provider=provider,
        db_factory=fake_db_factory,
    )

    result = await agent.run("hi", session_id="sess_exchange")
    assert result == "Hi!"

    # allocate_exchange should have been called once
    session_store.allocate_exchange.assert_called_once_with("sess_exchange", "test")

    calls = session_store.append_message.call_args_list
    # All calls (user + assistant) should carry exchange fields
    for call in calls:
        assert call.kwargs.get("exchange_id") == "01JEXCHANGE0000000000000001", (
            f"exchange_id missing or wrong in call: {call}"
        )
        assert call.kwargs.get("exchange_index") == 1, (
            f"exchange_index missing or wrong in call: {call}"
        )


@pytest.mark.asyncio
async def test_cancel_during_tool_call_flushes_cancelled_tool_result() -> None:
    """取消发生在工具执行中时，flush 不能留下孤立 tool_call。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    tool_started = asyncio.Event()
    tool_release = asyncio.Event()

    class ToolThenWaitProvider(LLMProvider):
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
            yield ToolCallBlockStart(block_id="b0_0", tool_id="toolu_slow", name="slow")
            yield ToolCallReady(
                block_id="b0_0",
                tool_id="toolu_slow",
                name="slow",
                inputs={},
            )
            yield ProviderCallEnd(stop_reason="tool_use")

    async def slow_tool(*_args: Any, **_kwargs: Any) -> MagicMock:
        tool_started.set()
        await tool_release.wait()
        result = MagicMock()
        result.ok = True
        result.output = "late"
        result.display = "late"
        result.empty_hint = None
        result.error = None
        return result

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are test."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()

    gate = MagicMock()
    gate.call = AsyncMock(side_effect=slow_tool)
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(gate=gate, session_store=session_store, provider=ToolThenWaitProvider())
    run_task = asyncio.create_task(agent.run("slow", session_id="sess_cancel_tool"))

    await asyncio.wait_for(tool_started.wait(), timeout=2.0)

    await agent.cancel_session("sess_cancel_tool", intent="cancel")
    try:
        await asyncio.wait_for(run_task, timeout=2.0)
    except asyncio.CancelledError:
        pass
    finally:
        tool_release.set()

    assistant_calls = [
        c for c in session_store.append_message.call_args_list if c.args[1] == "assistant"
    ]
    blocks = assistant_calls[-1].kwargs.get("blocks") or []
    tool_call = next(b for b in blocks if b.get("type") == "tool")
    tool_result = next(b for b in blocks if b.get("type") == "tool_result")

    assert tool_call["tool_call_id"] == "toolu_slow"
    assert tool_result["tool_call_id"] == "toolu_slow"
    assert tool_result["ok"] is False
    assert "cancel" in tool_result["model_content"].lower()


@pytest.mark.asyncio
async def test_cancel_flush_carries_same_exchange_as_user_message() -> None:
    """cancel-flush 的 append_message 应携带与 user-message 相同的 exchange_id/exchange_index。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    hang_event = asyncio.Event()

    class SlowThinkProvider(LLMProvider):
        """Yields a ThinkingBlockStop then hangs until cancelled."""

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
            yield ThinkingBlockStop(block_id="b0_0", thinking="pondering...", signature=None)
            await hang_event.wait()

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    _EXCHANGE_ID = "01JEXCHANGE_CANCEL000000001"
    _EXCHANGE_IDX = 7

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_context_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()
    session_store.allocate_exchange = AsyncMock(return_value=(_EXCHANGE_ID, _EXCHANGE_IDX))

    fake_db_factory = MagicMock()

    gate = MagicMock()
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    agent = TestAgent(
        gate=gate,
        session_store=session_store,
        provider=SlowThinkProvider(),
        db_factory=fake_db_factory,
    )

    run_task = asyncio.create_task(agent.run("hi", session_id="sess_cancel_exchange"))
    await asyncio.sleep(0.05)

    await agent.cancel_session("sess_cancel_exchange", intent="cancel")
    try:
        await asyncio.wait_for(run_task, timeout=2.0)
    except (asyncio.CancelledError, TimeoutError):
        pass

    calls = session_store.append_message.call_args_list
    # Every call (user + cancel-flush assistant) must carry the same exchange pair
    assert len(calls) >= 2, "Expected user append + cancel-flush append"
    for call in calls:
        assert call.kwargs.get("exchange_id") == _EXCHANGE_ID, (
            f"exchange_id mismatch in call: {call}"
        )
        assert call.kwargs.get("exchange_index") == _EXCHANGE_IDX, (
            f"exchange_index mismatch in call: {call}"
        )


# ---------------------------------------------------------------------------
# Compaction scheduler integration
# ---------------------------------------------------------------------------


class FakeCompactionScheduler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def maybe_schedule_after_turn(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_stream_inner_schedules_compaction_after_turn() -> None:
    """After TurnDone is persisted, the compaction scheduler receives one call
    containing session_id, agent_type, usage (from ProviderCallEnd), messages,
    and system_prompt.
    """
    from sebastian.context.usage import TokenUsage
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    fake_usage = TokenUsage(input_tokens=1000, output_tokens=200)

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Hello."),
            TextBlockStop(block_id="b0_0", text="Hello."),
            ProviderCallEnd(stop_reason="end_turn", usage=fake_usage),
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

    gate = MagicMock()
    gate.get_tool_specs = MagicMock(return_value=[])
    gate.get_skill_specs = MagicMock(return_value=[])

    scheduler = FakeCompactionScheduler()

    agent = TestAgent(
        gate=gate,
        session_store=session_store,
        provider=provider,
        compaction_scheduler=scheduler,
    )

    result = await agent.run("hi", session_id="sess_compaction")
    assert result == "Hello."

    # Scheduler must have been called exactly once
    assert len(scheduler.calls) == 1, f"Expected 1 scheduler call, got: {scheduler.calls}"

    call = scheduler.calls[0]
    assert call["session_id"] == "sess_compaction"
    assert call["agent_type"] == "test"
    # usage forwarded from ProviderCallEnd
    assert call["usage"] is fake_usage
    # messages include user message
    assert any(m.get("role") == "user" for m in call["messages"])
    # system_prompt is non-empty
    assert isinstance(call["system_prompt"], str)
    assert len(call["system_prompt"]) > 0

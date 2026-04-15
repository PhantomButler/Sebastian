from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
    ToolCallBlockStart,
    ToolCallReady,
    ToolResult,
    TurnDone,
)
from sebastian.llm.provider import LLMProvider


class MockLLMProvider(LLMProvider):
    """Test double that replays pre-configured event sequences."""

    def __init__(self, *turns: list[LLMStreamEvent]) -> None:
        self._turns = list(turns)
        self.call_count = 0
        self.last_messages: list[dict] = []

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
        if self.call_count >= len(self._turns):
            raise RuntimeError(
                f"MockLLMProvider has no more turns (called {self.call_count} times)"
            )
        self.last_messages = list(messages)
        events = self._turns[self.call_count]
        self.call_count += 1
        for event in events:
            yield event


async def _collect(gen: Any) -> list[object]:
    events: list[object] = []
    try:
        while True:
            events.append(await gen.asend(None))
    except StopAsyncIteration:
        return events


@pytest.mark.asyncio
async def test_agent_loop_streams_thinking_and_text_then_turn_done() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider(
        [
            ThinkingBlockStart(block_id="b0_0"),
            ThinkingDelta(block_id="b0_0", delta="Need to inspect."),
            ThinkingBlockStop(block_id="b0_0", thinking="Need to inspect."),
            TextBlockStart(block_id="b0_1"),
            TextDelta(block_id="b0_1", delta="Hello there!"),
            TextBlockStop(block_id="b0_1", text="Hello there!"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    loop = AgentLoop(provider, CapabilityRegistry())
    events = await _collect(
        loop.stream(system_prompt="You are helpful.", messages=[{"role": "user", "content": "Hi"}])
    )

    assert events == [
        ThinkingBlockStart(block_id="b0_0"),
        ThinkingDelta(block_id="b0_0", delta="Need to inspect."),
        ThinkingBlockStop(block_id="b0_0", thinking="Need to inspect."),
        TextBlockStart(block_id="b0_1"),
        TextDelta(block_id="b0_1", delta="Hello there!"),
        TextBlockStop(block_id="b0_1", text="Hello there!"),
        TurnDone(full_text="Hello there!"),
    ]
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_agent_loop_ends_after_single_no_tool_turn() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Done."),
            TextBlockStop(block_id="b0_0", text="Done."),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    loop = AgentLoop(provider, CapabilityRegistry())
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "Hi"}])

    assert await gen.asend(None) == TextBlockStart(block_id="b0_0")
    assert await gen.asend(None) == TextDelta(block_id="b0_0", delta="Done.")
    assert await gen.asend(None) == TextBlockStop(block_id="b0_0", text="Done.")
    assert await gen.asend(None) == TurnDone(full_text="Done.")

    with pytest.raises(StopAsyncIteration):
        await gen.asend(None)

    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_agent_loop_accepts_injected_tool_result_and_continues() -> None:
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Checking..."),
            TextBlockStop(block_id="b0_0", text="Checking..."),
            ToolCallBlockStart(block_id="b0_1", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_1",
                tool_id="toolu_1",
                name="weather_lookup",
                inputs={"city": "Shanghai"},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="It is sunny."),
            TextBlockStop(block_id="b1_0", text="It is sunny."),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    registry = MagicMock()
    registry.get_all_tool_specs.return_value = [
        {
            "name": "weather_lookup",
            "description": "Lookup weather",
            "input_schema": {"type": "object"},
        }
    ]

    loop = AgentLoop(provider, registry)
    gen = loop.stream(
        system_prompt="sys",
        messages=[{"role": "user", "content": "What's the weather?"}],
    )

    assert await gen.asend(None) == TextBlockStart(block_id="b0_0")
    assert await gen.asend(None) == TextDelta(block_id="b0_0", delta="Checking...")
    assert await gen.asend(None) == TextBlockStop(block_id="b0_0", text="Checking...")
    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_1", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_1", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )

    injected = ToolResult(
        tool_id="toolu_1", name="weather_lookup", ok=True, output="Sunny", error=None
    )
    assert await gen.asend(injected) == TextBlockStart(block_id="b1_0")
    assert await gen.asend(None) == TextDelta(block_id="b1_0", delta="It is sunny.")
    assert await gen.asend(None) == TextBlockStop(block_id="b1_0", text="It is sunny.")
    assert await gen.asend(None) == TurnDone(full_text="Checking...It is sunny.")

    assert provider.call_count == 2
    second_messages = provider.last_messages
    assert second_messages[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny"}],
    }


@pytest.mark.asyncio
async def test_agent_loop_rejects_missing_tool_result_injection() -> None:
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_0",
                tool_id="toolu_1",
                name="weather_lookup",
                inputs={"city": "Shanghai"},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ]
    )

    loop = AgentLoop(provider, MagicMock(get_all_tool_specs=MagicMock(return_value=[])))
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "weather"}])

    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )

    with pytest.raises(RuntimeError, match="requires an injected ToolResult"):
        await gen.asend(None)


@pytest.mark.asyncio
async def test_agent_loop_rejects_mismatched_tool_result_injection() -> None:
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_0",
                tool_id="toolu_1",
                name="weather_lookup",
                inputs={"city": "Shanghai"},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ]
    )

    loop = AgentLoop(provider, MagicMock(get_all_tool_specs=MagicMock(return_value=[])))
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "weather"}])

    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )

    with pytest.raises(RuntimeError, match="does not match current tool call"):
        await gen.asend(
            ToolResult(tool_id="toolu_2", name="other_tool", ok=True, output="X", error=None)
        )


@pytest.mark.asyncio
async def test_agent_loop_formats_failed_tool_result_for_next_turn() -> None:
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_0",
                tool_id="toolu_1",
                name="weather_lookup",
                inputs={"city": "Shanghai"},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="Fallback."),
            TextBlockStop(block_id="b1_0", text="Fallback."),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    loop = AgentLoop(provider, MagicMock(get_all_tool_specs=MagicMock(return_value=[])))
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "weather"}])

    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )
    assert await gen.asend(
        ToolResult(
            tool_id="toolu_1", name="weather_lookup", ok=False, output=None, error="network down"
        )
    ) == TextBlockStart(block_id="b1_0")
    assert await gen.asend(None) == TextDelta(block_id="b1_0", delta="Fallback.")
    assert await gen.asend(None) == TextBlockStop(block_id="b1_0", text="Fallback.")
    assert await gen.asend(None) == TurnDone(full_text="Fallback.")

    last_messages = provider.last_messages
    assert last_messages[-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "Error: network down",
                "is_error": True,
            }
        ],
    }


@pytest.mark.asyncio
async def test_agent_loop_passes_thinking_effort_to_provider() -> None:
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    captured: dict = {}

    async def _empty_stream(**kwargs):
        captured.update(kwargs)
        yield ProviderCallEnd(stop_reason="end_turn")

    provider = MagicMock()
    provider.message_format = "anthropic"
    provider.stream = _empty_stream

    tool_provider = MagicMock()
    tool_provider.get_all_tool_specs = MagicMock(return_value=[])

    loop = AgentLoop(provider=provider, tool_provider=tool_provider, model="m", max_tokens=1000)
    gen = loop.stream(system_prompt="sys", messages=[], task_id=None, thinking_effort="high")
    try:
        while True:
            await gen.asend(None)
    except StopAsyncIteration:
        pass
    assert captured.get("thinking_effort") == "high"


@pytest.mark.asyncio
async def test_agent_loop_preserves_thinking_signature_across_iterations() -> None:
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    iteration_calls: list[list[dict]] = []

    async def _two_iter_stream(**kwargs):
        iteration_calls.append(list(kwargs["messages"]))
        if len(iteration_calls) == 1:
            yield ThinkingBlockStop(block_id="b0_0", thinking="thought", signature="sig_1")
            yield ToolCallReady(block_id="b0_1", tool_id="tu_1", name="noop", inputs={})
            yield ProviderCallEnd(stop_reason="tool_use")
        else:
            yield ProviderCallEnd(stop_reason="end_turn")

    provider = MagicMock()
    provider.message_format = "anthropic"
    provider.stream = _two_iter_stream

    tool_provider = MagicMock()
    tool_provider.get_all_tool_specs = MagicMock(return_value=[])

    loop = AgentLoop(provider=provider, tool_provider=tool_provider, model="m", max_tokens=1000)
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "hi"}])

    send_val = None
    try:
        while True:
            ev = await gen.asend(send_val)
            send_val = None
            if isinstance(ev, ToolCallReady):
                send_val = ToolResult(
                    tool_id="tu_1", name="noop", ok=True, output="done", error=None
                )
    except StopAsyncIteration:
        pass

    assert len(iteration_calls) == 2
    second_msgs = iteration_calls[1]
    assistant_msgs = [m for m in second_msgs if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    blocks = assistant_msgs[0]["content"]
    thinking_blocks = [b for b in blocks if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["thinking"] == "thought"
    assert thinking_blocks[0]["signature"] == "sig_1"


@pytest.mark.asyncio
async def test_agent_loop_passes_allowed_tools_to_provider() -> None:
    """AgentLoop 存的 allowed_tools 应传给 registry.get_callable_specs，
    过滤后的 tools 传给 provider.stream。"""
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    registry = MagicMock()
    registry.get_callable_specs = MagicMock(
        return_value=[{"name": "Read", "description": "read", "input_schema": {}}]
    )

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextBlockStop(block_id="b0_0", text="ok"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )
    captured_tools: list[Any] = []
    original_stream = provider.stream

    async def spy_stream(**kwargs: Any) -> Any:
        captured_tools.append(kwargs["tools"])
        async for event in original_stream(**kwargs):
            yield event

    provider.stream = spy_stream  # type: ignore[method-assign]

    loop = AgentLoop(
        provider,
        registry,
        model="test",
        allowed_tools={"Read"},
        allowed_skills=None,
    )
    await _collect(loop.stream(system_prompt="s", messages=[{"role": "user", "content": "hi"}]))

    registry.get_callable_specs.assert_called_once_with(allowed_tools={"Read"}, allowed_skills=None)
    assert captured_tools == [[{"name": "Read", "description": "read", "input_schema": {}}]]


@pytest.mark.asyncio
async def test_agent_loop_none_allowed_tools_means_unrestricted() -> None:
    """allowed_tools=None 表示不限制，registry 收到 None。"""
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    registry = MagicMock()
    registry.get_callable_specs = MagicMock(return_value=[])

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextBlockStop(block_id="b0_0", text="ok"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    loop = AgentLoop(provider, registry, model="test")
    await _collect(loop.stream(system_prompt="s", messages=[{"role": "user", "content": "hi"}]))

    registry.get_callable_specs.assert_called_once_with(allowed_tools=None, allowed_skills=None)

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

    provider = MockLLMProvider([
        ThinkingBlockStart(block_id="b0_0"),
        ThinkingDelta(block_id="b0_0", delta="Need to inspect."),
        ThinkingBlockStop(block_id="b0_0", thinking="Need to inspect."),
        TextBlockStart(block_id="b0_1"),
        TextDelta(block_id="b0_1", delta="Hello there!"),
        TextBlockStop(block_id="b0_1", text="Hello there!"),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    loop = AgentLoop(provider, CapabilityRegistry())
    events = await _collect(
        loop.stream(system_prompt="You are helpful.",
                    messages=[{"role": "user", "content": "Hi"}])
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

    provider = MockLLMProvider([
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Done."),
        TextBlockStop(block_id="b0_0", text="Done."),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

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
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Checking..."),
            TextBlockStop(block_id="b0_0", text="Checking..."),
            ToolCallBlockStart(block_id="b0_1", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_1", tool_id="toolu_1", name="weather_lookup",
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
        {"name": "weather_lookup", "description": "Lookup weather",
         "input_schema": {"type": "object"}}
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

    injected = ToolResult(tool_id="toolu_1", name="weather_lookup", ok=True, output="Sunny", error=None)
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
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider([
        ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
        ToolCallReady(
            block_id="b0_0", tool_id="toolu_1", name="weather_lookup",
            inputs={"city": "Shanghai"},
        ),
        ProviderCallEnd(stop_reason="tool_use"),
    ])

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
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider([
        ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
        ToolCallReady(
            block_id="b0_0", tool_id="toolu_1", name="weather_lookup",
            inputs={"city": "Shanghai"},
        ),
        ProviderCallEnd(stop_reason="tool_use"),
    ])

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
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_0", tool_id="toolu_1", name="weather_lookup",
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
        ToolResult(tool_id="toolu_1", name="weather_lookup", ok=False, output=None, error="network down")
    ) == TextBlockStart(block_id="b1_0")
    assert await gen.asend(None) == TextDelta(block_id="b1_0", delta="Fallback.")
    assert await gen.asend(None) == TextBlockStop(block_id="b1_0", text="Fallback.")
    assert await gen.asend(None) == TurnDone(full_text="Fallback.")

    last_messages = provider.last_messages
    assert last_messages[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Error: network down", "is_error": True}],
    }

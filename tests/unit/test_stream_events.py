from __future__ import annotations

import dataclasses
from typing import get_args


def test_stream_event_types_are_dataclasses() -> None:
    from sebastian.core.stream_events import (
        LLMStreamEvent,
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

    thinking_start = ThinkingBlockStart(block_id="b0_0")
    assert thinking_start.block_id == "b0_0"
    assert dataclasses.is_dataclass(thinking_start)

    thinking_delta = ThinkingDelta(block_id="b0_0", delta="pondering")
    assert thinking_delta.delta == "pondering"

    thinking_stop = ThinkingBlockStop(block_id="b0_0")
    assert thinking_stop.block_id == "b0_0"

    text_start = TextBlockStart(block_id="b0_1")
    assert text_start.block_id == "b0_1"

    text_delta = TextDelta(block_id="b0_1", delta="hello")
    assert text_delta.delta == "hello"

    text_stop = TextBlockStop(block_id="b0_1")
    assert text_stop.block_id == "b0_1"

    tool_call_start = ToolCallBlockStart(block_id="b0_2", tool_id="tu_01", name="search")
    assert tool_call_start.tool_id == "tu_01"

    tool_call_ready = ToolCallReady(
        block_id="b0_2",
        tool_id="tu_01",
        name="search",
        inputs={"q": "x"},
    )
    assert tool_call_ready.inputs == {"q": "x"}

    result = ToolResult(tool_id="tu_01", name="search", ok=True, output="data", error=None)
    assert result.ok is True

    done = TurnDone(full_text="hello")
    assert done.full_text == "hello"

    assert set(get_args(LLMStreamEvent)) == {
        ThinkingBlockStart,
        ThinkingDelta,
        ThinkingBlockStop,
        TextBlockStart,
        TextDelta,
        TextBlockStop,
        ToolCallBlockStart,
        ToolCallReady,
        ToolResult,
        TurnDone,
    }

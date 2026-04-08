from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ThinkingBlockStart:
    block_id: str


@dataclass
class ThinkingDelta:
    block_id: str
    delta: str


@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str  # full accumulated thinking text for this block
    signature: str | None = None


@dataclass
class TextBlockStart:
    block_id: str


@dataclass
class TextDelta:
    block_id: str
    delta: str


@dataclass
class TextBlockStop:
    block_id: str
    text: str  # full accumulated text for this block


@dataclass
class ToolCallBlockStart:
    block_id: str
    tool_id: str
    name: str


@dataclass
class ToolCallReady:
    block_id: str
    tool_id: str
    name: str
    inputs: dict[str, Any]


@dataclass
class ToolResult:
    tool_id: str
    name: str
    ok: bool
    output: Any
    error: str | None
    empty_hint: str | None = None


@dataclass
class ProviderCallEnd:
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"


@dataclass
class TurnDone:
    full_text: str


LLMStreamEvent = (
    ThinkingBlockStart
    | ThinkingDelta
    | ThinkingBlockStop
    | TextBlockStart
    | TextDelta
    | TextBlockStop
    | ToolCallBlockStart
    | ToolCallReady
    | ToolResult
    | ProviderCallEnd
    | TurnDone
)

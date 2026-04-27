from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import openai

from sebastian.context.usage import TokenUsage
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
)
from sebastian.llm.provider import LLMProvider


class OpenAICompatProvider(LLMProvider):
    """OpenAI /v1/chat/completions adapter.

    thinking_format values:
      None                — no thinking, plain text + tool calls
      "reasoning_content" — DeepSeek-R1 style: delta.reasoning_content field
      "think_tags"        — llama.cpp style: <think>...</think> in text content
    """

    message_format = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        thinking_format: str | None = None,
        thinking_capability: str | None = None,
    ) -> None:
        self._client = (
            openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else openai.AsyncOpenAI(api_key=api_key)
        )
        self._thinking_format = thinking_format
        self._capability = thinking_capability

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
        openai_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *messages,
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        if getattr(self, "_capability", None) == "effort" and thinking_effort in (
            "low",
            "medium",
            "high",
            "max",
        ):
            kwargs["reasoning_effort"] = thinking_effort

        text_block_id = f"{block_id_prefix}0"
        text_buffer = ""
        think_buffer = ""
        text_block_started = False
        think_block_started = False
        # tool_calls_raw: index → {id, name, arguments_str}
        tool_calls_raw: dict[int, dict[str, str]] = {}
        stop_reason = "end_turn"
        last_usage: TokenUsage | None = None

        async for chunk in await self._client.chat.completions.create(**kwargs):
            raw_usage = getattr(chunk, "usage", None)
            if raw_usage is not None:
                last_usage = TokenUsage(
                    input_tokens=getattr(raw_usage, "prompt_tokens", None),
                    output_tokens=getattr(raw_usage, "completion_tokens", None),
                    total_tokens=getattr(raw_usage, "total_tokens", None),
                    reasoning_tokens=(
                        getattr(
                            getattr(raw_usage, "completion_tokens_details", None),
                            "reasoning_tokens",
                            None,
                        )
                    ),
                    raw=raw_usage.model_dump() if hasattr(raw_usage, "model_dump") else None,
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish = choice.finish_reason
            delta = choice.delta

            # --- text / thinking content ---
            content: str = delta.content or ""
            reasoning: str = getattr(delta, "reasoning_content", None) or ""

            if self._thinking_format == "reasoning_content" and reasoning:
                if not think_block_started:
                    think_block_id = f"{block_id_prefix}think"
                    yield ThinkingBlockStart(block_id=think_block_id)
                    think_block_started = True
                think_buffer += reasoning
                yield ThinkingDelta(block_id=f"{block_id_prefix}think", delta=reasoning)

            if content:
                if self._thinking_format == "think_tags":
                    # Buffer and parse <think>...</think> inline
                    think_buffer, text_buffer, events = _parse_think_tags(
                        think_buffer,
                        text_buffer,
                        content,
                        f"{block_id_prefix}think",
                        text_block_id,
                        think_block_started,
                        text_block_started,
                    )
                    for ev in events:
                        if isinstance(ev, ThinkingBlockStart):
                            think_block_started = True
                        if isinstance(ev, TextBlockStart):
                            text_block_started = True
                        yield ev
                else:
                    if not text_block_started:
                        yield TextBlockStart(block_id=text_block_id)
                        text_block_started = True
                    text_buffer += content
                    yield TextDelta(block_id=text_block_id, delta=content)

            # --- tool call accumulation ---
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_raw[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_raw[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_raw[idx]["arguments"] += tc.function.arguments

            if finish is not None:
                stop_reason = finish

        # Flush open text/thinking blocks
        if think_block_started and self._thinking_format in ("reasoning_content", "think_tags"):
            yield ThinkingBlockStop(block_id=f"{block_id_prefix}think", thinking=think_buffer)
        if text_block_started:
            yield TextBlockStop(block_id=text_block_id, text=text_buffer)

        # Emit tool calls
        for idx in sorted(tool_calls_raw):
            tc = tool_calls_raw[idx]
            tc_block_id = f"{block_id_prefix}{idx + 1}"
            try:
                inputs = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                inputs = {}
            yield ToolCallBlockStart(block_id=tc_block_id, tool_id=tc["id"], name=tc["name"])
            yield ToolCallReady(
                block_id=tc_block_id,
                tool_id=tc["id"],
                name=tc["name"],
                inputs=inputs,
            )
            stop_reason = "tool_use"

        yield ProviderCallEnd(stop_reason=stop_reason, usage=last_usage)


def _parse_think_tags(
    think_buffer: str,
    text_buffer: str,
    new_content: str,
    think_block_id: str,
    text_block_id: str,
    think_block_started: bool,
    text_block_started: bool,
) -> tuple[str, str, list[LLMStreamEvent]]:
    """Parse <think>...</think> from streaming text. Returns updated buffers + events."""
    events: list[LLMStreamEvent] = []
    _combined = (  # state machine uses `remaining` directly; kept for readability
        think_buffer if think_block_started and not text_block_started else ""
    ) + new_content

    # Simple state machine: if we haven't seen </think> yet, check if this content has it
    in_think = think_block_started and not text_block_started

    remaining = new_content
    while remaining:
        if in_think:
            close_idx = remaining.find("</think>")
            if close_idx == -1:
                think_buffer += remaining
                events.append(ThinkingDelta(block_id=think_block_id, delta=remaining))
                remaining = ""
            else:
                think_part = remaining[:close_idx]
                think_buffer += think_part
                if think_part:
                    events.append(ThinkingDelta(block_id=think_block_id, delta=think_part))
                events.append(ThinkingBlockStop(block_id=think_block_id, thinking=think_buffer))
                think_buffer = ""
                in_think = False
                remaining = remaining[close_idx + len("</think>") :]
        else:
            open_idx = remaining.find("<think>")
            if open_idx == -1:
                if not text_block_started:
                    events.append(TextBlockStart(block_id=text_block_id))
                    text_block_started = True
                text_buffer += remaining
                events.append(TextDelta(block_id=text_block_id, delta=remaining))
                remaining = ""
            else:
                pre = remaining[:open_idx]
                if pre:
                    if not text_block_started:
                        events.append(TextBlockStart(block_id=text_block_id))
                        text_block_started = True
                    text_buffer += pre
                    events.append(TextDelta(block_id=text_block_id, delta=pre))
                events.append(ThinkingBlockStart(block_id=think_block_id))
                in_think = True
                remaining = remaining[open_idx + len("<think>") :]

    return think_buffer, text_buffer, events

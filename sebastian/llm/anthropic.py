from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import anthropic

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


class AnthropicProvider(LLMProvider):
    """Anthropic SDK adapter. Supports thinking blocks and tool use."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            **({"base_url": base_url} if base_url else {}),
        )

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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for raw in stream:
                block_index = getattr(raw, "index", 0)
                block_id = f"{block_id_prefix}{block_index}"

                if raw.type == "content_block_start":
                    block_type = raw.content_block.type
                    if block_type == "thinking":
                        yield ThinkingBlockStart(block_id=block_id)
                    elif block_type == "text":
                        yield TextBlockStart(block_id=block_id)
                    elif block_type == "tool_use":
                        yield ToolCallBlockStart(
                            block_id=block_id,
                            tool_id=raw.content_block.id,
                            name=raw.content_block.name,
                        )
                    continue

                if raw.type == "content_block_delta":
                    delta_type = raw.delta.type
                    if delta_type == "thinking_delta":
                        yield ThinkingDelta(block_id=block_id, delta=raw.delta.thinking)
                    elif delta_type == "text_delta":
                        yield TextDelta(block_id=block_id, delta=raw.delta.text)
                    # input_json_delta for tool_use: accumulated by SDK, read at content_block_stop
                    continue

                if raw.type != "content_block_stop":
                    continue

                block = stream.current_message.content[block_index]
                if block.type == "thinking":
                    yield ThinkingBlockStop(block_id=block_id, thinking=block.thinking)
                elif block.type == "text":
                    yield TextBlockStop(block_id=block_id, text=block.text)
                elif block.type == "tool_use":
                    yield ToolCallReady(
                        block_id=block_id,
                        tool_id=block.id,
                        name=block.name,
                        inputs=block.input,
                    )

            final = await stream.get_final_message()
            yield ProviderCallEnd(stop_reason=final.stop_reason)

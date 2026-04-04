from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
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

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20


def _tool_result_content(result: ToolResult) -> str:
    if result.ok:
        return str(result.output)
    return f"Error: {result.error}"


def _validate_injected_tool_result(
    *,
    tool_id: str,
    tool_name: str,
    result: ToolResult | None,
) -> ToolResult:
    if result is None:
        raise RuntimeError(f"Tool call {tool_name} ({tool_id}) requires an injected ToolResult")
    if result.tool_id != tool_id or result.name != tool_name:
        raise RuntimeError(
            f"Injected ToolResult does not match current tool call {tool_name} ({tool_id})"
        )
    return result


class AgentLoop:
    """Core reasoning loop that streams structured LLM events turn by turn."""

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        registry: CapabilityRegistry,
        model: str = "claude-opus-4-6",
        max_tokens: int | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            from sebastian.config import settings

            self._max_tokens = settings.llm_max_tokens

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        task_id: str | None = None,
    ) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
        """Yield LLM stream events and accept tool results injected via asend()."""
        working = list(messages)
        tools = self._registry.get_all_tool_specs()
        full_text_parts: list[str] = []

        for iteration in range(MAX_ITERATIONS):
            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": self._max_tokens,
                "system": system_prompt,
                "messages": working,
            }
            if tools:
                kwargs["tools"] = tools

            assistant_content: list[dict[str, Any]] = []
            tool_results_for_next: list[dict[str, Any]] = []

            async with self._client.messages.stream(**kwargs) as stream:
                async for raw in stream:
                    block_index = getattr(raw, "index", 0)
                    block_id = f"b{iteration}_{block_index}"

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
                            yield ThinkingDelta(
                                block_id=block_id,
                                delta=raw.delta.thinking,
                            )
                        elif delta_type == "text_delta":
                            full_text_parts.append(raw.delta.text)
                            yield TextDelta(
                                block_id=block_id,
                                delta=raw.delta.text,
                            )
                        continue

                    if raw.type != "content_block_stop":
                        continue

                    block = stream.current_message.content[block_index]
                    if block.type == "thinking":
                        assistant_content.append(
                            {
                                "type": "thinking",
                                "thinking": block.thinking,
                            }
                        )
                        yield ThinkingBlockStop(block_id=block_id)
                    elif block.type == "text":
                        assistant_content.append(
                            {
                                "type": "text",
                                "text": block.text,
                            }
                        )
                        yield TextBlockStop(block_id=block_id)
                    elif block.type == "tool_use":
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )
                        injected = yield ToolCallReady(
                            block_id=block_id,
                            tool_id=block.id,
                            name=block.name,
                            inputs=block.input,
                        )
                        validated_result = _validate_injected_tool_result(
                            tool_id=block.id,
                            tool_name=block.name,
                            result=injected,
                        )
                        tool_results_for_next.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": _tool_result_content(validated_result),
                            }
                        )

                final_message = await stream.get_final_message()

            working.append({"role": "assistant", "content": assistant_content})

            if final_message.stop_reason != "tool_use":
                yield TurnDone(full_text="".join(full_text_parts))
                return

            working.append({"role": "user", "content": tool_results_for_next})

        logger.warning("Reached MAX_ITERATIONS (%d) for task_id=%s", MAX_ITERATIONS, task_id)
        yield TurnDone(full_text="".join(full_text_parts))

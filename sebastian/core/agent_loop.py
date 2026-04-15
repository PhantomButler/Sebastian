from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from sebastian.core.protocols import ToolSpecProvider
from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStop,
    ThinkingDelta,
    ToolCallReady,
    ToolResult,
    TurnDone,
)

if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider

logger = logging.getLogger(__name__)
_llm_stream_logger = logging.getLogger("sebastian.llm.stream")

MAX_ITERATIONS = 20


def _is_empty_output(output: Any) -> bool:
    """Check if tool output is semantically empty."""
    if output is None:
        return True
    if isinstance(output, (str, list, dict)) and not output:
        return True
    return False


def _tool_result_content(result: ToolResult) -> str:
    if not result.ok:
        return f"Error: {result.error}"
    if result.empty_hint:
        return result.empty_hint
    if _is_empty_output(result.output):
        return "<empty output>"
    output = result.output
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(output)


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
    """Core reasoning loop. Drives multi-turn LLM conversation via LLMProvider."""

    def __init__(
        self,
        provider: LLMProvider | None,
        tool_provider: ToolSpecProvider,
        model: str = "claude-opus-4-6",
        max_tokens: int | None = None,
        allowed_tools: set[str] | None = None,
        allowed_skills: set[str] | None = None,
    ) -> None:
        self._provider = provider
        self._registry = tool_provider
        self._model = model
        self._allowed_tools = allowed_tools
        self._allowed_skills = allowed_skills
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
        thinking_effort: str | None = None,
    ) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
        """Yield LLM stream events; accept tool results injected via asend()."""
        if self._provider is None:
            raise RuntimeError("No LLM provider configured. Add one via the Settings page.")
        working = list(messages)
        tools = self._registry.get_callable_specs(
            allowed_tools=self._allowed_tools,
            allowed_skills=self._allowed_skills,
        )
        full_text_parts: list[str] = []
        is_openai = self._provider.message_format == "openai"

        for iteration in range(MAX_ITERATIONS):
            # Anthropic: list of content blocks; OpenAI: list of tool_calls entries
            assistant_blocks: list[dict[str, Any]] = []
            tool_calls_openai: list[dict[str, Any]] = []
            text_parts: list[str] = []
            # Anthropic: list of tool_result blocks; OpenAI: list of role:tool messages
            tool_results_for_next: list[dict[str, Any]] = []
            stop_reason = "end_turn"

            async for event in self._provider.stream(
                system=system_prompt,
                messages=working,
                tools=tools,
                model=self._model,
                max_tokens=self._max_tokens,
                block_id_prefix=f"b{iteration}_",
                thinking_effort=thinking_effort,
            ):
                _llm_stream_logger.debug(
                    "stream_event type=%s task_id=%s", type(event).__name__, task_id
                )

                if isinstance(event, ProviderCallEnd):
                    stop_reason = event.stop_reason
                    continue

                if isinstance(event, ThinkingBlockStop):
                    if not is_openai:
                        block_dict: dict[str, Any] = {
                            "type": "thinking",
                            "thinking": event.thinking,
                        }
                        if event.signature is not None:
                            block_dict["signature"] = event.signature
                        assistant_blocks.append(block_dict)
                    yield event

                elif isinstance(event, TextBlockStop):
                    full_text_parts.append(event.text)
                    text_parts.append(event.text)
                    if not is_openai:
                        assistant_blocks.append({"type": "text", "text": event.text})
                    yield event

                elif isinstance(event, ToolCallReady):
                    if is_openai:
                        tool_calls_openai.append(
                            {
                                "id": event.tool_id,
                                "type": "function",
                                "function": {
                                    "name": event.name,
                                    "arguments": json.dumps(event.inputs),
                                },
                            }
                        )
                    else:
                        assistant_blocks.append(
                            {
                                "type": "tool_use",
                                "id": event.tool_id,
                                "name": event.name,
                                "input": event.inputs,
                            }
                        )

                    injected = yield event
                    validated = _validate_injected_tool_result(
                        tool_id=event.tool_id,
                        tool_name=event.name,
                        result=injected,
                    )

                    if is_openai:
                        tool_results_for_next.append(
                            {
                                "role": "tool",
                                "tool_call_id": event.tool_id,
                                "content": _tool_result_content(validated),
                            }
                        )
                    else:
                        block: dict[str, Any] = {
                            "type": "tool_result",
                            "tool_use_id": event.tool_id,
                            "content": _tool_result_content(validated),
                        }
                        if not validated.ok:
                            block["is_error"] = True
                        tool_results_for_next.append(block)

                else:
                    if isinstance(event, TextDelta):
                        _llm_stream_logger.debug(
                            "text_delta block_id=%s delta=%r task_id=%s",
                            event.block_id,
                            event.delta,
                            task_id,
                        )
                    elif isinstance(event, ThinkingDelta):
                        _llm_stream_logger.debug(
                            "thinking_delta block_id=%s delta=%r task_id=%s",
                            event.block_id,
                            event.delta,
                            task_id,
                        )
                    yield event

            # Append assistant turn in provider-appropriate format
            if is_openai:
                text = "".join(text_parts)
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": text or None,
                }
                if tool_calls_openai:
                    assistant_msg["tool_calls"] = tool_calls_openai
                working.append(assistant_msg)
            else:
                working.append({"role": "assistant", "content": assistant_blocks})

            if stop_reason != "tool_use":
                yield TurnDone(full_text="".join(full_text_parts))
                return

            # Append tool results in provider-appropriate format
            if is_openai:
                working.extend(tool_results_for_next)
            else:
                working.append({"role": "user", "content": tool_results_for_next})

        logger.warning("Reached MAX_ITERATIONS (%d) for task_id=%s", MAX_ITERATIONS, task_id)
        yield TurnDone(full_text="".join(full_text_parts))

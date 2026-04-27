from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, ClassVar

import anthropic

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


class AnthropicProvider(LLMProvider):
    """Anthropic SDK adapter. Supports thinking blocks and tool use."""

    message_format = "anthropic"

    # Fixed-budget mode (thinking_capability='effort'): map effort -> budget_tokens.
    FIXED_EFFORT_TO_BUDGET: ClassVar[dict[str, int]] = {
        "low": 2048,
        "medium": 8192,
        "high": 24576,
    }

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        thinking_capability: str | None = None,
    ) -> None:
        self._client = (
            anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
            if base_url
            else anthropic.AsyncAnthropic(api_key=api_key)
        )
        self._capability = thinking_capability

    def _build_thinking_kwargs(
        self, thinking_effort: str | None, max_tokens: int
    ) -> dict[str, Any]:
        """Translate (capability, effort) -> SDK kwargs fragment.

        Returns empty dict when no thinking should be enabled (capability
        is none/always_on/unset, or effort is off/None, or toggle=off).

        Raises ValueError for ``capability='effort'`` when:
          - thinking_effort 不在 low/medium/high 中（快速失败，不静默降级）
          - FIXED_EFFORT_TO_BUDGET[effort] >= max_tokens（预算无法容纳思考+正文）
        """
        capability = getattr(self, "_capability", None)

        if capability is None or capability in ("none", "always_on"):
            return {}
        if thinking_effort in (None, "off"):
            return {}

        if capability == "toggle":
            if thinking_effort == "on":
                return {"thinking": {"type": "enabled"}}
            return {}

        if capability == "adaptive":
            if thinking_effort in ("low", "medium", "high", "max"):
                return {
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": thinking_effort},
                }
            return {}

        if capability == "effort":
            budget = self.FIXED_EFFORT_TO_BUDGET.get(thinking_effort or "")
            if budget is None:
                raise ValueError(
                    f"thinking_effort={thinking_effort!r} not allowed for "
                    f"thinking_capability='effort' (allowed: low/medium/high)"
                )
            if budget >= max_tokens:
                raise ValueError(
                    f"budget_tokens={budget} must be strictly less than "
                    f"max_tokens={max_tokens}; raise max_tokens or lower effort"
                )
            return {"thinking": {"type": "enabled", "budget_tokens": budget}}

        if capability == "output_effort":
            # Third-party Anthropic-compat APIs (e.g. DeepSeek Anthropic format):
            # enable thinking via type=enabled and control intensity via output_config.effort.
            if thinking_effort not in ("high", "max"):
                raise ValueError(
                    f"thinking_effort={thinking_effort!r} not allowed for "
                    f"thinking_capability='output_effort' (allowed: high/max)"
                )
            return {
                "thinking": {"type": "enabled"},
                "output_config": {"effort": thinking_effort},
            }

        return {}

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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        kwargs.update(self._build_thinking_kwargs(thinking_effort, max_tokens))

        async with self._client.messages.stream(**kwargs) as stream:
            async for raw in stream:
                block_index = getattr(raw, "index", 0)
                block_id = f"{block_id_prefix}{block_index}"

                if raw.type == "content_block_start":
                    content_block = raw.content_block
                    block_type = content_block.type
                    if block_type == "thinking":
                        yield ThinkingBlockStart(block_id=block_id)
                    elif block_type == "text":
                        yield TextBlockStart(block_id=block_id)
                    elif block_type == "tool_use":
                        yield ToolCallBlockStart(
                            block_id=block_id,
                            tool_id=content_block.id,  # type: ignore[union-attr]
                            name=content_block.name,  # type: ignore[union-attr]
                        )
                    continue

                if raw.type == "content_block_delta":
                    delta = raw.delta
                    delta_type = delta.type
                    if delta_type == "thinking_delta":
                        yield ThinkingDelta(block_id=block_id, delta=delta.thinking)  # type: ignore[union-attr]
                    elif delta_type == "text_delta":
                        yield TextDelta(block_id=block_id, delta=delta.text)  # type: ignore[union-attr]
                    continue

                if raw.type != "content_block_stop":
                    continue

                block = stream.current_message_snapshot.content[block_index]
                if block.type == "thinking":
                    yield ThinkingBlockStop(
                        block_id=block_id,
                        thinking=block.thinking,
                        signature=getattr(block, "signature", None),
                    )
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
            usage = final.usage
            token_usage = TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None),
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None),
                raw=usage.model_dump() if hasattr(usage, "model_dump") else None,
            )
            yield ProviderCallEnd(stop_reason=final.stop_reason or "end_turn", usage=token_usage)

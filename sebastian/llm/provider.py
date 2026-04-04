from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Literal

from sebastian.core.stream_events import LLMStreamEvent


class LLMProvider(ABC):
    """Single-call LLM abstraction. Multi-turn loop lives in AgentLoop, not here.

    Implementations map SDK-specific streaming events to LLMStreamEvent and
    emit ProviderCallEnd as the final event with the stop_reason.

    message_format controls how AgentLoop builds conversation history:
      "anthropic" — assistant content as block list, tool results in user message
      "openai"    — assistant with tool_calls field, tool results as role:tool messages
    """

    message_format: Literal["anthropic", "openai"] = "anthropic"

    @abstractmethod
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
        """Yield LLMStreamEvent objects for one complete LLM call.

        The last event MUST be ProviderCallEnd(stop_reason=...).
        block_id_prefix is prepended to every block_id (e.g. "b0_") to keep
        IDs unique across AgentLoop iterations.
        """
        ...
        yield  # satisfy type checker that this is an async generator

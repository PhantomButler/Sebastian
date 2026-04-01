from __future__ import annotations
import logging
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20


class AgentLoop:
    """Core reasoning loop: send messages to LLM, execute tool calls, repeat
    until stop_reason is not 'tool_use' or MAX_ITERATIONS reached."""

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        registry: CapabilityRegistry,
        model: str = "claude-opus-4-6",
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        task_id: str | None = None,
    ) -> str:
        """Run the agent loop. Returns the final text response."""
        working = list(messages)
        tools = self._registry.get_all_tool_specs()

        for iteration in range(MAX_ITERATIONS):
            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": working,
            }
            if tools:
                kwargs["tools"] = tools

            response = await self._client.messages.create(**kwargs)
            logger.debug("Iteration %d stop_reason=%s", iteration, response.stop_reason)

            # Build assistant content list
            assistant_content: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                elif hasattr(block, "text"):
                    assistant_content.append({"type": "text", "text": block.text})

            working.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        return block.text
                return ""

            # Execute tool calls, collect results
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                logger.info("Tool call: %s(%s)", block.name, block.input)
                result: ToolResult = await self._registry.call(block.name, **block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        str(result.output) if result.ok else f"Error: {result.error}"
                    ),
                })

            working.append({"role": "user", "content": tool_results})

        logger.warning("Reached MAX_ITERATIONS (%d) for task_id=%s", MAX_ITERATIONS, task_id)
        return "Max iterations reached without a final response."

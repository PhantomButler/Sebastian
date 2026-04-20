from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from sebastian.memory.provider_bindings import MEMORY_EXTRACTOR_BINDING
from sebastian.memory.types import CandidateArtifact, ProposedSlot

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider

logger = logging.getLogger(__name__)


class ExtractorInput(BaseModel):
    task: Literal["extract_memory_artifacts"] = "extract_memory_artifacts"
    subject_context: dict[str, Any]
    conversation_window: list[dict[str, Any]]
    known_slots: list[dict[str, Any]]


class ExtractorOutput(BaseModel):
    artifacts: list[CandidateArtifact]
    proposed_slots: list[ProposedSlot] = []


class MemoryExtractor:
    """LLM-backed extractor that converts a conversation window into candidate memory artifacts.

    On any failure (provider network/timeout error OR JSON parse/schema failure)
    the extractor retries up to *max_retries* times with exponential backoff
    (0.5s, 1s, 2s, ...), then returns an empty list — it never raises.
    """

    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None:
        self._registry = llm_registry
        self._max_retries = max_retries

    async def extract(self, input: ExtractorInput) -> ExtractorOutput:
        """Call LLM to extract candidate memory artifacts.

        Returns ExtractorOutput(artifacts=[], proposed_slots=[]) on any failure after retries.
        """
        resolved = await self._registry.get_provider(MEMORY_EXTRACTOR_BINDING)
        system = (
            "You are a memory extraction assistant. "
            "Analyze the conversation and extract memory artifacts. "
            "Respond with ONLY valid JSON in this exact format: "
            '{"artifacts": [<CandidateArtifact objects>], "proposed_slots": []}. '
            "No explanation, no markdown, no code blocks. Only JSON."
        )
        user_content = input.model_dump_json()
        messages = [{"role": "user", "content": user_content}]
        empty = ExtractorOutput(artifacts=[], proposed_slots=[])

        for attempt in range(self._max_retries + 1):
            try:
                raw = await self._call_llm(resolved, system, messages)
                return ExtractorOutput.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001 — provider exception types vary
                if attempt < self._max_retries:
                    logger.warning(
                        "Extractor attempt %d failed: %s",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                logger.warning(
                    "Extractor exhausted %d retries, returning empty: %s",
                    self._max_retries + 1,
                    exc,
                )
                return empty
        return empty  # unreachable; satisfies type checker

    async def _call_llm(
        self,
        resolved: ResolvedProvider,
        system: str,
        messages: list[dict[str, Any]],
    ) -> str:
        """Stream from LLM and collect all TextDelta events into a single string."""
        from sebastian.core.stream_events import TextDelta

        text = ""
        # Note: temperature is not exposed in the current LLMProvider abstraction;
        # providers use their configured default temperature.
        async for event in resolved.provider.stream(
            system=system,
            messages=messages,
            tools=[],
            model=resolved.model,
            max_tokens=2048,
        ):
            if isinstance(event, TextDelta):
                text += event.delta
        return text

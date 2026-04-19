from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from sebastian.memory.provider_bindings import MEMORY_EXTRACTOR_BINDING
from sebastian.memory.types import CandidateArtifact

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider

logger = logging.getLogger(__name__)


class ExtractorInput(BaseModel):
    subject_context: dict[str, Any]
    conversation_window: list[dict[str, Any]]
    known_slots: list[dict[str, Any]]


class ExtractorOutput(BaseModel):
    artifacts: list[CandidateArtifact]


class MemoryExtractor:
    """LLM-backed extractor that converts a conversation window into candidate memory artifacts.

    On any parse or schema failure the extractor retries up to *max_retries* times,
    then returns an empty list — it never raises.
    """

    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None:
        self._registry = llm_registry
        self._max_retries = max_retries

    async def extract(self, input: ExtractorInput) -> list[CandidateArtifact]:
        """Call LLM to extract candidate memory artifacts.

        Returns [] on schema failure after retry.
        """
        resolved = await self._registry.get_provider(MEMORY_EXTRACTOR_BINDING)
        system = (
            "You are a memory extraction assistant. "
            "Analyze the conversation and extract memory artifacts. "
            "Respond with ONLY valid JSON in this exact format: "
            '{"artifacts": [<CandidateArtifact objects>]}. '
            "No explanation, no markdown, no code blocks. Only JSON."
        )
        user_content = input.model_dump_json()
        messages = [{"role": "user", "content": user_content}]

        for attempt in range(self._max_retries + 1):
            raw = await self._call_llm(resolved, system, messages)
            try:
                output = ExtractorOutput.model_validate_json(raw)
                return output.artifacts
            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                if attempt < self._max_retries:
                    logger.warning(
                        "Extractor output invalid (attempt %d), retrying: %s",
                        attempt + 1,
                        e,
                    )
                    continue
                logger.warning(
                    "Extractor failed after %d retries, returning empty: %s",
                    self._max_retries + 1,
                    e,
                )
                return []
        return []  # unreachable; satisfies type checker

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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from sebastian.memory.provider_bindings import MEMORY_CONSOLIDATOR_BINDING
from sebastian.memory.types import CandidateArtifact

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider

logger = logging.getLogger(__name__)


class ConsolidatorInput(BaseModel):
    task: str = "consolidate_memory"
    session_messages: list[dict[str, Any]]
    candidate_artifacts: list[CandidateArtifact]
    active_memories_for_subject: list[dict[str, Any]]
    recent_summaries: list[dict[str, Any]]
    slot_definitions: list[dict[str, Any]]
    entity_registry_snapshot: list[dict[str, Any]]


class MemorySummary(BaseModel):
    content: str
    subject_id: str
    scope: str = "user"
    session_id: str | None = None


class ProposedAction(BaseModel):
    action: str  # e.g. "ADD", "SUPERSEDE", "EXPIRE"
    memory_id: str | None = None
    reason: str


class ConsolidationResult(BaseModel):
    summaries: list[MemorySummary] = []
    proposed_artifacts: list[CandidateArtifact] = []
    proposed_actions: list[ProposedAction] = []


class MemoryConsolidator:
    """LLM-backed consolidator that produces summaries and proposed memory actions.

    On any parse or schema failure the consolidator retries up to *max_retries* times,
    then returns an empty ConsolidationResult — it never raises.
    """

    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None:
        self._registry = llm_registry
        self._max_retries = max_retries

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        """Call LLM to consolidate session memory.

        Returns empty ConsolidationResult on schema failure.
        """
        resolved = await self._registry.get_provider(MEMORY_CONSOLIDATOR_BINDING)
        system = (
            "You are a memory consolidation assistant. "
            "Analyze the session and produce a ConsolidationResult. "
            "Respond with ONLY valid JSON: "
            '{"summaries": [...], "proposed_artifacts": [...], "proposed_actions": [...]}. '
            "No explanation, no markdown, no code blocks. Only JSON."
        )
        messages = [{"role": "user", "content": input.model_dump_json()}]
        empty = ConsolidationResult()

        for attempt in range(self._max_retries + 1):
            raw = await self._call_llm(resolved, system, messages)
            try:
                return ConsolidationResult.model_validate_json(raw)
            except (ValidationError, ValueError) as e:
                if attempt < self._max_retries:
                    logger.warning(
                        "Consolidator output invalid (attempt %d), retrying: %s",
                        attempt + 1,
                        e,
                    )
                    continue
                logger.warning(
                    "Consolidator failed after %d retries, returning empty: %s",
                    self._max_retries + 1,
                    e,
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
        async for event in resolved.provider.stream(
            system=system,
            messages=messages,
            tools=[],
            model=resolved.model,
            max_tokens=4096,
        ):
            if isinstance(event, TextDelta):
                text += event.delta
        return text

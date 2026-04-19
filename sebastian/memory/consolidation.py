from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.memory.provider_bindings import MEMORY_CONSOLIDATOR_BINDING
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)

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


class SessionConsolidationWorker:
    """Consolidate a completed session's messages into persistent memory stores.

    Idempotent: if a :class:`SessionConsolidationRecord` already exists for the
    given (session_id, agent_type) pair the worker returns immediately without
    making any further writes.

    Memory-disabled: if ``memory_settings_fn`` returns ``False`` the worker
    returns immediately without writing anything.
    """

    _WORKER_ID = "session_consolidation_worker"
    _RULE_VERSION = "phase_c_v1"

    def __init__(
        self,
        *,
        db_factory: async_sessionmaker[AsyncSession],
        consolidator: MemoryConsolidator,
        session_store: Any,
        memory_settings_fn: Callable[[], bool],
    ) -> None:
        self._db_factory = db_factory
        self._consolidator = consolidator
        self._session_store = session_store
        self._memory_settings_fn = memory_settings_fn

    async def consolidate_session(self, session_id: str, agent_type: str) -> None:
        """Run consolidation for a completed session.

        All writes happen in one atomic transaction; the marker record is
        added inside the same transaction so the operation is idempotent.
        """
        # 1. Check feature flag
        if not self._memory_settings_fn():
            return

        # 2. Check idempotency — open a read-only session
        async with self._db_factory() as check_session:
            existing = await check_session.get(
                _consolidation_record_class(),
                {"session_id": session_id, "agent_type": agent_type},
            )
            if existing is not None:
                return

        # 3. Fetch session messages
        messages: list[dict[str, Any]] = await self._session_store.get_messages(
            session_id, agent_type
        )

        # 4. Build consolidator input
        consolidator_input = ConsolidatorInput(
            session_messages=messages,
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )

        # 5. Call the consolidator
        result: ConsolidationResult = await self._consolidator.consolidate(consolidator_input)

        # 6. Persist everything in one atomic transaction
        async with self._db_factory() as session:
            from sebastian.memory.decision_log import MemoryDecisionLogger
            from sebastian.memory.episode_store import EpisodeMemoryStore
            from sebastian.memory.profile_store import ProfileMemoryStore
            from sebastian.memory.resolver import resolve_candidate
            from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
            from sebastian.store.models import SessionConsolidationRecord

            episode_store = EpisodeMemoryStore(session)
            profile_store = ProfileMemoryStore(session)
            decision_logger = MemoryDecisionLogger(session)

            for summary in result.summaries:
                artifact = _summary_to_artifact(summary)
                await episode_store.add_summary(artifact)

            for candidate in result.proposed_artifacts:
                decision = await resolve_candidate(
                    candidate,
                    subject_id="owner",
                    profile_store=profile_store,
                    slot_registry=DEFAULT_SLOT_REGISTRY,
                )
                if (
                    decision.decision != MemoryDecisionType.DISCARD
                    and decision.new_memory is not None
                ):
                    if decision.decision == MemoryDecisionType.ADD:
                        await profile_store.add(decision.new_memory)
                    elif decision.decision == MemoryDecisionType.SUPERSEDE:
                        await profile_store.supersede(
                            decision.old_memory_ids, decision.new_memory
                        )
                await decision_logger.append(
                    decision,
                    worker=self._WORKER_ID,
                    model=None,
                    rule_version=self._RULE_VERSION,
                )

            marker = SessionConsolidationRecord(
                session_id=session_id,
                agent_type=agent_type,
                consolidated_at=datetime.now(UTC),
                worker_version=self._RULE_VERSION,
            )
            session.add(marker)
            await session.commit()


def _consolidation_record_class() -> type:
    """Return SessionConsolidationRecord avoiding circular import at module level."""
    from sebastian.store.models import SessionConsolidationRecord

    return SessionConsolidationRecord


def _summary_to_artifact(summary: MemorySummary) -> MemoryArtifact:
    """Convert a :class:`MemorySummary` into a :class:`MemoryArtifact` ready for storage."""
    return MemoryArtifact(
        id=str(uuid4()),
        kind=MemoryKind.SUMMARY,
        scope=MemoryScope(summary.scope),
        subject_id=summary.subject_id,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        content=summary.content,
        structured_payload={},
        source=MemorySource.SYSTEM_DERIVED,
        confidence=0.8,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=datetime.now(UTC),
        last_accessed_at=None,
        access_count=0,
        provenance={},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )

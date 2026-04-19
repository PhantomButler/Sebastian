from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.memory.errors import InvalidCandidateError
from sebastian.memory.extraction import ExtractorInput, MemoryExtractor
from sebastian.memory.provider_bindings import MEMORY_CONSOLIDATOR_BINDING
from sebastian.memory.subject import resolve_subject
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ResolveDecision,
)
from sebastian.protocol.events.types import Event, EventType

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider
    from sebastian.protocol.events.bus import EventBus

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
    model_config = ConfigDict(extra="forbid")
    content: str
    subject_id: str
    scope: MemoryScope = MemoryScope.USER
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

    On any failure (provider network/timeout error OR JSON parse/schema failure)
    the consolidator retries up to *max_retries* times with exponential backoff
    (0.5s, 1s, 2s, ...), then returns an empty ConsolidationResult — it never raises.
    """

    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None:
        self._registry = llm_registry
        self._max_retries = max_retries
        self.last_resolved: ResolvedProvider | None = None

    async def consolidate(self, consolidator_input: ConsolidatorInput) -> ConsolidationResult:
        """Call LLM to consolidate session memory.

        Returns empty ConsolidationResult on any failure after retries.
        """
        resolved = await self._registry.get_provider(MEMORY_CONSOLIDATOR_BINDING)
        self.last_resolved = resolved
        system = (
            "You are a memory consolidation assistant. "
            "Analyze the session and produce a ConsolidationResult. "
            "Respond with ONLY valid JSON: "
            '{"summaries": [...], "proposed_artifacts": [...], "proposed_actions": [...]}. '
            "No explanation, no markdown, no code blocks. Only JSON."
        )
        messages = [{"role": "user", "content": consolidator_input.model_dump_json()}]
        empty = ConsolidationResult()

        for attempt in range(self._max_retries + 1):
            try:
                raw = await self._call_llm(resolved, system, messages)
                return ConsolidationResult.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001 — provider exception types vary
                if attempt < self._max_retries:
                    logger.warning(
                        "Consolidator attempt %d failed: %s",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                logger.warning(
                    "Consolidator exhausted %d retries, returning empty: %s",
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
        extractor: MemoryExtractor,
        session_store: Any,
        memory_settings_fn: Callable[[], bool],
    ) -> None:
        self._db_factory = db_factory
        self._consolidator = consolidator
        self._extractor = extractor
        self._session_store = session_store
        self._memory_settings_fn = memory_settings_fn

    async def consolidate_session(self, session_id: str, agent_type: str) -> None:
        """Run consolidation for a completed session.

        All writes happen in one atomic transaction; the marker record is
        added inside the same transaction so the operation is idempotent.
        If a concurrent task already committed the marker, IntegrityError is
        caught and we return early — our uncommitted writes are rolled back
        automatically by the context manager.
        """
        # 1. Check feature flag
        if not self._memory_settings_fn():
            return

        # 2. Fetch session messages
        messages: list[dict[str, Any]] = await self._session_store.get_messages(
            session_id, agent_type
        )

        # 3. Open one atomic transaction that wraps context-gathering,
        #    consolidation and persistence. The marker insert at the end
        #    will raise IntegrityError if a concurrent task already committed
        #    for the same (session_id, agent_type) pair, preserving
        #    idempotency.
        async with self._db_factory() as session:
            from sebastian.memory.decision_log import MemoryDecisionLogger
            from sebastian.memory.entity_registry import EntityRegistry
            from sebastian.memory.episode_store import EpisodeMemoryStore
            from sebastian.memory.profile_store import ProfileMemoryStore
            from sebastian.memory.resolver import resolve_candidate
            from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
            from sebastian.memory.write_router import persist_decision
            from sebastian.store.models import SessionConsolidationRecord

            episode_store = EpisodeMemoryStore(session)
            profile_store = ProfileMemoryStore(session)
            entity_registry = EntityRegistry(session)
            decision_logger = MemoryDecisionLogger(session)

            # 4. Pull consolidator context inside the transaction so the LLM
            #    can see existing memories and avoid proposing duplicates.
            context_subject_id = await resolve_subject(
                MemoryScope.USER,
                session_id=session_id,
                agent_type=agent_type,
            )
            active_rows = await profile_store.search_active(subject_id=context_subject_id, limit=32)
            recent_summary_rows = await episode_store.search_summaries(
                subject_id=context_subject_id, limit=8
            )
            entity_rows = await entity_registry.snapshot(limit=64)

            # 4a. Run the extractor first so the consolidator sees explicit
            #     candidate artifacts instead of having to re-extract from raw
            #     messages. Extractor returns [] on LLM failure, never raises.
            extractor_input = ExtractorInput(
                subject_context={
                    "subject_id": context_subject_id,
                    "agent_type": agent_type,
                },
                conversation_window=messages,
                known_slots=[s.model_dump() for s in DEFAULT_SLOT_REGISTRY.list_all()],
            )
            candidate_artifacts = await self._extractor.extract(extractor_input)

            consolidator_input = ConsolidatorInput(
                session_messages=messages,
                candidate_artifacts=candidate_artifacts,
                active_memories_for_subject=[
                    {
                        "id": r.id,
                        "slot_id": r.slot_id,
                        "kind": r.kind,
                        "content": r.content,
                        "confidence": r.confidence,
                        "source": r.source,
                    }
                    for r in active_rows
                ],
                recent_summaries=[{"content": r.content} for r in recent_summary_rows],
                slot_definitions=[s.model_dump() for s in DEFAULT_SLOT_REGISTRY.list_all()],
                entity_registry_snapshot=[
                    {
                        "canonical_name": r.canonical_name,
                        "aliases": r.aliases,
                        "type": r.entity_type,
                    }
                    for r in entity_rows
                ],
            )

            # 5. Call the consolidator
            result: ConsolidationResult = await self._consolidator.consolidate(consolidator_input)
            resolved_provider = getattr(self._consolidator, "last_resolved", None)
            model_name = resolved_provider.model if resolved_provider is not None else None

            for summary in result.summaries:
                summary_subject_id = await resolve_subject(
                    summary.scope,
                    session_id=session_id,
                    agent_type=agent_type,
                )
                summary_candidate = CandidateArtifact(
                    kind=MemoryKind.SUMMARY,
                    content=summary.content,
                    structured_payload={},
                    subject_hint=summary_subject_id,
                    scope=summary.scope,
                    slot_id=None,
                    cardinality=None,
                    resolution_policy=None,
                    confidence=0.8,
                    source=MemorySource.SYSTEM_DERIVED,
                    evidence=[{"session_id": session_id}],
                    valid_from=None,
                    valid_until=None,
                    policy_tags=[],
                    needs_review=False,
                )
                summary_decision = await resolve_candidate(
                    summary_candidate,
                    subject_id=summary_subject_id,
                    profile_store=profile_store,
                    slot_registry=DEFAULT_SLOT_REGISTRY,
                )
                if summary_decision.new_memory is not None:
                    await persist_decision(
                        summary_decision,
                        session=session,
                        profile_store=profile_store,
                        episode_store=episode_store,
                        entity_registry=entity_registry,
                    )
                await decision_logger.append(
                    summary_decision,
                    worker=self._WORKER_ID,
                    model=model_name,
                    rule_version=self._RULE_VERSION,
                )

            for candidate in result.proposed_artifacts:
                candidate_subject_id = await resolve_subject(
                    candidate.scope,
                    session_id=session_id,
                    agent_type=agent_type,
                )
                try:
                    DEFAULT_SLOT_REGISTRY.validate_candidate(candidate)
                except InvalidCandidateError as e:
                    bad_decision = ResolveDecision(
                        decision=MemoryDecisionType.DISCARD,
                        reason=f"validate: {e}",
                        old_memory_ids=[],
                        new_memory=None,
                        candidate=candidate,
                        subject_id=candidate_subject_id,
                        scope=candidate.scope,
                        slot_id=candidate.slot_id,
                    )
                    await decision_logger.append(
                        bad_decision,
                        worker=self._WORKER_ID,
                        model=model_name,
                        rule_version=self._RULE_VERSION,
                    )
                    continue
                decision = await resolve_candidate(
                    candidate,
                    subject_id=candidate_subject_id,
                    profile_store=profile_store,
                    slot_registry=DEFAULT_SLOT_REGISTRY,
                )
                if (
                    decision.decision != MemoryDecisionType.DISCARD
                    and decision.new_memory is not None
                ):
                    await persist_decision(
                        decision,
                        session=session,
                        profile_store=profile_store,
                        episode_store=episode_store,
                        entity_registry=entity_registry,
                    )
                await decision_logger.append(
                    decision,
                    worker=self._WORKER_ID,
                    model=model_name,
                    rule_version=self._RULE_VERSION,
                )

            # Execute EXPIRE actions proposed by the consolidator. SUPERSEDE
            # actions are paired with proposed_artifacts and handled above;
            # ignore them here to prevent double-processing.
            for action in result.proposed_actions:
                if action.action != "EXPIRE" or not action.memory_id:
                    continue
                await profile_store.expire(action.memory_id)
                placeholder_candidate = CandidateArtifact(
                    kind=MemoryKind.FACT,
                    content=f"EXPIRE: {action.reason}",
                    structured_payload={},
                    subject_hint=context_subject_id,
                    scope=MemoryScope.USER,
                    slot_id=None,
                    cardinality=None,
                    resolution_policy=None,
                    confidence=0.0,
                    source=MemorySource.SYSTEM_DERIVED,
                    evidence=[{"session_id": session_id}],
                    valid_from=None,
                    valid_until=None,
                    policy_tags=[],
                    needs_review=False,
                )
                expire_decision = ResolveDecision(
                    decision=MemoryDecisionType.EXPIRE,
                    reason=action.reason,
                    old_memory_ids=[action.memory_id],
                    new_memory=None,
                    candidate=placeholder_candidate,
                    subject_id=context_subject_id,
                    scope=MemoryScope.USER,
                    slot_id=None,
                )
                await decision_logger.append(
                    expire_decision,
                    worker=self._WORKER_ID,
                    model=model_name,
                    rule_version=self._RULE_VERSION,
                )

            marker = SessionConsolidationRecord(
                session_id=session_id,
                agent_type=agent_type,
                consolidated_at=datetime.now(UTC),
                worker_version=self._RULE_VERSION,
            )
            session.add(marker)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return  # already consolidated by a concurrent task


class MemoryConsolidationScheduler:
    """Subscribes to SESSION_COMPLETED and schedules consolidation tasks.

    The handler checks the memory feature flag *before* creating the asyncio task
    so that disabled-memory paths never enter the event loop queue.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        worker: SessionConsolidationWorker,
        memory_settings_fn: Callable[[], bool],
    ) -> None:
        self._worker = worker
        self._memory_settings_fn = memory_settings_fn
        self._pending_tasks: set[asyncio.Task[None]] = set()
        event_bus.subscribe(self._handle, EventType.SESSION_COMPLETED)

    async def _handle(self, event: Event) -> None:
        if not self._memory_settings_fn():
            return
        session_id = event.data.get("session_id", "")
        agent_type = event.data.get("agent_type", "")
        if not session_id or not agent_type:
            return
        task: asyncio.Task[None] = asyncio.create_task(
            self._worker.consolidate_session(session_id, agent_type),
            name=f"consolidation_{session_id}",
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._log_exception)
        task.add_done_callback(self._pending_tasks.discard)

    @staticmethod
    def _log_exception(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Consolidation task failed: %s", exc, exc_info=exc)

    async def drain(self) -> None:
        """Wait for all pending consolidation tasks to finish (for tests and graceful shutdown)."""
        pending = list(self._pending_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def aclose(self) -> None:
        """Cancel all pending consolidation tasks on shutdown."""
        for task in list(self._pending_tasks):
            task.cancel()
        if self._pending_tasks:
            await asyncio.gather(*list(self._pending_tasks), return_exceptions=True)
        self._pending_tasks.clear()


async def sweep_unconsolidated(
    *,
    db_factory: async_sessionmaker[AsyncSession],
    worker: SessionConsolidationWorker,
    index_store: Any,
    memory_settings_fn: Callable[[], bool],
) -> None:
    """Catch up sessions that completed while the gateway was down.

    Queries the session index for ``status == "completed"`` entries, removes
    those already marked by :class:`SessionConsolidationRecord`, and invokes
    :meth:`SessionConsolidationWorker.consolidate_session` for the rest. A
    single failing session is logged and skipped — it must not abort the sweep.
    """
    if not memory_settings_fn():
        return

    from sebastian.store.models import SessionConsolidationRecord

    entries = await index_store.list_all()
    completed = [e for e in entries if e.get("status") == "completed"]
    if not completed:
        return

    async with db_factory() as db:
        rows = await db.execute(
            select(
                SessionConsolidationRecord.session_id,
                SessionConsolidationRecord.agent_type,
            )
        )
        consolidated_pairs = {(r[0], r[1]) for r in rows.all()}

    for entry in completed:
        session_id = entry.get("id")
        agent_type = entry.get("agent_type")
        if not session_id or not agent_type:
            continue
        if (session_id, agent_type) in consolidated_pairs:
            continue
        try:
            await worker.consolidate_session(session_id, agent_type)
        except Exception as exc:  # noqa: BLE001 — never abort the sweep
            logger.warning(
                "sweep_unconsolidated: failed for (%s, %s): %s",
                session_id,
                agent_type,
                exc,
            )

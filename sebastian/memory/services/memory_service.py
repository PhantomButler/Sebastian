from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from sebastian.memory.contracts.retrieval import (
    ExplicitMemorySearchRequest,
    ExplicitMemorySearchResult,
    PromptMemoryRequest,
    PromptMemoryResult,
)
from sebastian.memory.contracts.writing import MemoryWriteRequest, MemoryWriteResult
from sebastian.memory.services.retrieval import MemoryRetrievalService
from sebastian.memory.services.writing import MemoryWriteService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.memory.resident.resident_snapshot import ResidentMemorySnapshotRefresher
    from sebastian.memory.writing.slots import SlotRegistry

# Store imports needed when MemoryService owns the session (mutation_scope path)
from sebastian.memory.writing.decision_log import MemoryDecisionLogger
from sebastian.memory.stores.entity_registry import EntityRegistry
from sebastian.memory.stores.episode_store import EpisodeMemoryStore
from sebastian.memory.stores.profile_store import ProfileMemoryStore
from sebastian.memory.retrieval.retrieval import DEFAULT_RETRIEVAL_PLANNER
from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore
from sebastian.memory.writing.slot_proposals import SlotProposalHandler
from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self,
        *,
        db_factory: async_sessionmaker[AsyncSession] | None,
        retrieval: MemoryRetrievalService | None = None,
        writing: MemoryWriteService | None = None,
        resident_snapshot_refresher: ResidentMemorySnapshotRefresher | None = None,
        memory_settings_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._retrieval = retrieval if retrieval is not None else MemoryRetrievalService()
        if writing is not None:
            self._writing: MemoryWriteService | None = writing
        elif db_factory is not None:
            self._writing = MemoryWriteService(db_factory=db_factory)
        else:
            self._writing = None
        self._resident_snapshot_refresher = resident_snapshot_refresher
        self._memory_settings_fn = memory_settings_fn

    def _is_enabled(self) -> bool:
        if self._memory_settings_fn is not None:
            return self._memory_settings_fn()
        return True

    def is_enabled(self) -> bool:
        return self._is_enabled()

    async def retrieve_for_prompt(self, request: PromptMemoryRequest) -> PromptMemoryResult:
        if not self._is_enabled():
            return PromptMemoryResult(section="")
        if self._db_factory is None:
            return PromptMemoryResult(section="")
        try:
            async with self._db_factory() as db_session:
                return await self._retrieval.retrieve_for_prompt(request, db_session=db_session)
        except Exception:
            logger.warning("memory: retrieve_for_prompt failed", exc_info=True)
            return PromptMemoryResult(section="")

    async def search(
        self, request: ExplicitMemorySearchRequest
    ) -> ExplicitMemorySearchResult:
        if not self._is_enabled():
            return ExplicitMemorySearchResult(items=[])
        if self._db_factory is None:
            return ExplicitMemorySearchResult(items=[])
        try:
            async with self._db_factory() as db_session:
                return await self._retrieval.search(request, db_session=db_session)
        except Exception:
            logger.warning("memory: search failed", exc_info=True)
            return ExplicitMemorySearchResult(items=[])

    async def write_candidates(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        if not self._is_enabled():
            return MemoryWriteResult()
        if self._writing is None:
            return MemoryWriteResult()

        # No refresher: delegate directly (MemoryWriteService owns session + commit).
        if self._resident_snapshot_refresher is None:
            return await self._writing.write_candidates(request)

        # Refresher present: own the session so we can wrap the commit inside
        # mutation_scope(), preventing concurrent snapshot readers from seeing a
        # stale snapshot between DB commit and dirty-flag write.
        assert self._db_factory is not None  # guaranteed when refresher is set

        async with self._db_factory() as db_session:
            slot_store = SlotDefinitionStore(db_session)
            profile_store = ProfileMemoryStore(db_session)
            episode_store = EpisodeMemoryStore(db_session)
            entity_registry = EntityRegistry(db_session, planner=DEFAULT_RETRIEVAL_PLANNER)
            decision_logger = MemoryDecisionLogger(db_session)
            slot_proposal_handler = SlotProposalHandler(
                store=slot_store, registry=DEFAULT_SLOT_REGISTRY
            )

            result = await self._writing.write_candidates_in_session(
                request,
                db_session=db_session,
                profile_store=profile_store,
                episode_store=episode_store,
                entity_registry=entity_registry,
                decision_logger=decision_logger,
                slot_registry=DEFAULT_SLOT_REGISTRY,
                slot_proposal_handler=slot_proposal_handler,
            )

            async with self._resident_snapshot_refresher.mutation_scope():
                await db_session.commit()
                if result.saved_count > 0:
                    await self._resident_snapshot_refresher.mark_dirty_locked()

        return result

    async def write_candidates_in_session(
        self,
        request: MemoryWriteRequest,
        *,
        db_session: AsyncSession,
        profile_store: ProfileMemoryStore,
        episode_store: EpisodeMemoryStore,
        entity_registry: EntityRegistry,
        decision_logger: MemoryDecisionLogger,
        slot_registry: SlotRegistry,
        slot_proposal_handler: SlotProposalHandler | None,
    ) -> MemoryWriteResult:
        if not self._is_enabled():
            return MemoryWriteResult()
        if self._writing is None:
            return MemoryWriteResult()
        return await self._writing.write_candidates_in_session(
            request,
            db_session=db_session,
            profile_store=profile_store,
            episode_store=episode_store,
            entity_registry=entity_registry,
            decision_logger=decision_logger,
            slot_registry=slot_registry,
            slot_proposal_handler=slot_proposal_handler,
        )

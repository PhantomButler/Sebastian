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

    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.resident_snapshot import ResidentMemorySnapshotRefresher
    from sebastian.memory.slot_proposals import SlotProposalHandler
    from sebastian.memory.slots import SlotRegistry

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
        self._writing = (
            writing if writing is not None else MemoryWriteService(db_factory=db_factory)
        )
        self._resident_snapshot_refresher = resident_snapshot_refresher
        self._memory_settings_fn = memory_settings_fn

    def _is_enabled(self) -> bool:
        if self._memory_settings_fn is not None:
            return self._memory_settings_fn()
        return True

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
        async with self._db_factory() as db_session:
            return await self._retrieval.search(request, db_session=db_session)

    async def write_candidates(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        result = await self._writing.write_candidates(request)
        if result.saved_count > 0 and self._resident_snapshot_refresher is not None:
            self._resident_snapshot_refresher.schedule_refresh()
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

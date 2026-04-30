from __future__ import annotations

from typing import TYPE_CHECKING

from sebastian.memory.contracts.writing import MemoryWriteRequest, MemoryWriteResult
from sebastian.memory.pipeline import process_candidates

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slot_proposals import SlotProposalHandler
    from sebastian.memory.slots import SlotRegistry


class MemoryWriteService:
    def __init__(self, *, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

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
        pipeline_result = await process_candidates(
            request.candidates,
            request.proposed_slots,
            session_id=request.session_id,
            agent_type=request.agent_type,
            db_session=db_session,
            profile_store=profile_store,
            episode_store=episode_store,
            entity_registry=entity_registry,
            decision_logger=decision_logger,
            slot_registry=slot_registry,
            slot_proposal_handler=slot_proposal_handler,
            worker_id=request.worker_id,
            model_name=request.model_name,
            rule_version=request.rule_version,
            input_source=request.input_source,
            proposed_by=request.proposed_by,
        )
        return MemoryWriteResult(
            decisions=pipeline_result.decisions,
            proposed_slots_registered=pipeline_result.proposed_slots_registered,
            proposed_slots_rejected=pipeline_result.proposed_slots_rejected,
        )

    async def write_candidates(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        from sebastian.memory.decision_log import MemoryDecisionLogger
        from sebastian.memory.entity_registry import EntityRegistry
        from sebastian.memory.episode_store import EpisodeMemoryStore
        from sebastian.memory.profile_store import ProfileMemoryStore
        from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER
        from sebastian.memory.slot_definition_store import SlotDefinitionStore
        from sebastian.memory.slot_proposals import SlotProposalHandler
        from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

        async with self._db_factory() as db_session:
            slot_store = SlotDefinitionStore(db_session)
            profile_store = ProfileMemoryStore(db_session)
            episode_store = EpisodeMemoryStore(db_session)
            entity_registry = EntityRegistry(db_session, planner=DEFAULT_RETRIEVAL_PLANNER)
            decision_logger = MemoryDecisionLogger(db_session)
            slot_proposal_handler = SlotProposalHandler(
                store=slot_store, registry=DEFAULT_SLOT_REGISTRY
            )

            result = await self.write_candidates_in_session(
                request,
                db_session=db_session,
                profile_store=profile_store,
                episode_store=episode_store,
                entity_registry=entity_registry,
                decision_logger=decision_logger,
                slot_registry=DEFAULT_SLOT_REGISTRY,
                slot_proposal_handler=slot_proposal_handler,
            )
            await db_session.commit()
            return result

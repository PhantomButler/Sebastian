from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sebastian.memory.errors import InvalidCandidateError, InvalidSlotProposalError
from sebastian.memory.writing.resolver import resolve_candidate
from sebastian.memory.writing.slot_proposals import SlotProposalHandler
from sebastian.memory.subject import resolve_subject
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryDecisionType,
    ProposedSlot,
    ResolveDecision,
)
from sebastian.memory.writing.write_router import persist_decision

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.writing.decision_log import MemoryDecisionLogger
    from sebastian.memory.stores.entity_registry import EntityRegistry
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.writing.slots import SlotRegistry

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Structured result from process_candidates()."""

    decisions: list[ResolveDecision] = field(default_factory=list)
    proposed_slots_registered: list[str] = field(default_factory=list)
    proposed_slots_rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def saved_count(self) -> int:
        return sum(
            1
            for d in self.decisions
            if d.decision != MemoryDecisionType.DISCARD and d.new_memory is not None
        )

    @property
    def discarded_count(self) -> int:
        return sum(1 for d in self.decisions if d.decision == MemoryDecisionType.DISCARD)


async def process_candidates(
    candidates: list[CandidateArtifact],
    proposed_slots: list[ProposedSlot] | None = None,
    *,
    session_id: str,
    agent_type: str,
    db_session: AsyncSession,
    profile_store: ProfileMemoryStore,
    episode_store: EpisodeMemoryStore,
    entity_registry: EntityRegistry,
    decision_logger: MemoryDecisionLogger,
    slot_registry: SlotRegistry,
    slot_proposal_handler: SlotProposalHandler | None = None,
    worker_id: str,
    model_name: str | None,
    rule_version: str,
    input_source: dict[str, Any],
    proposed_by: Literal["extractor", "consolidator"] = "extractor",
) -> PipelineResult:
    """Process candidate artifacts through the full write pipeline.

    Steps:
    1. (Optional) Register proposed_slots via SlotProposalHandler before processing
       candidates — failed slots downgrade matching candidates' slot_id to None.
    2. For each candidate:
       a. Resolve subject_id from candidate.scope + session context
       b. Validate against slot registry (DISCARD + log on failure)
       c. Resolve against existing memories (ADD/SUPERSEDE/MERGE/DISCARD)
       d. Persist non-DISCARD decisions
       e. Append to decision log

    Returns PipelineResult with decisions, proposed_slots_registered, proposed_slots_rejected.
    Does NOT handle EXPIRE actions — those stay inline in the caller.
    Does NOT commit db_session — caller is responsible.
    """
    registered: list[str] = []
    rejected: list[dict[str, Any]] = []
    failed_slot_ids: set[str] = set()

    # Step 1: process proposed_slots before candidates
    # 只注册被至少一个 candidate 引用的 slot，避免在 consolidator 失败（candidates 为空）
    # 时留下无对应记忆的孤儿 slot。
    if proposed_slots:
        if slot_proposal_handler is None:
            raise ValueError(
                f"process_candidates: proposed_slots 非空（{len(proposed_slots)} 个）"
                " 但 slot_proposal_handler 为 None；"
                " 调用方必须传入 SlotProposalHandler 实例"
            )
        referenced_slot_ids = {c.slot_id for c in candidates if c.slot_id is not None}
        for p in proposed_slots:
            if p.slot_id not in referenced_slot_ids:
                logger.debug(
                    "slot.proposal.skipped_no_candidate slot_id=%s proposed_by=%s",
                    p.slot_id,
                    proposed_by,
                )
                continue
            try:
                schema = await slot_proposal_handler.register_or_reuse(
                    p,
                    proposed_by=proposed_by,
                    proposed_in_session=session_id,
                )
                registered.append(schema.slot_id)
                logger.info(
                    "slot.proposal.accepted slot_id=%s proposed_by=%s session=%s",
                    schema.slot_id,
                    proposed_by,
                    session_id,
                )
            except InvalidSlotProposalError as exc:
                rejected.append({"slot_id": p.slot_id, "reason": str(exc)})
                failed_slot_ids.add(p.slot_id)
                logger.warning(
                    "slot.proposal.rejected slot_id=%s reason=%s proposed_by=%s",
                    p.slot_id,
                    exc,
                    proposed_by,
                )

    # Step 2: downgrade candidates whose proposed slot was rejected
    effective_candidates: list[CandidateArtifact] = []
    for c in candidates:
        if c.slot_id is not None and c.slot_id in failed_slot_ids:
            downgraded = c.model_copy(update={"slot_id": None})
            effective_candidates.append(downgraded)
            logger.info(
                "slot.proposal.candidate_downgrade slot_id=%s kind=%s",
                c.slot_id,
                c.kind.value,
            )
        else:
            effective_candidates.append(c)

    # Step 3: original candidate processing loop
    decisions: list[ResolveDecision] = []

    for candidate in effective_candidates:
        subject_id = await resolve_subject(
            candidate.scope,
            session_id=session_id,
            agent_type=agent_type,
        )
        try:
            slot_registry.validate_candidate(candidate)
        except InvalidCandidateError as e:
            decision = ResolveDecision(
                decision=MemoryDecisionType.DISCARD,
                reason=f"validate: {e}",
                old_memory_ids=[],
                new_memory=None,
                candidate=candidate,
                subject_id=subject_id,
                scope=candidate.scope,
                slot_id=candidate.slot_id,
            )
            await decision_logger.append(
                decision,
                worker=worker_id,
                model=model_name,
                rule_version=rule_version,
                input_source=input_source,
            )
            decisions.append(decision)
            continue

        decision = await resolve_candidate(
            candidate,
            subject_id=subject_id,
            profile_store=profile_store,
            slot_registry=slot_registry,
            episode_store=episode_store,
        )

        if decision.decision != MemoryDecisionType.DISCARD and decision.new_memory is not None:
            await persist_decision(
                decision,
                session=db_session,
                profile_store=profile_store,
                episode_store=episode_store,
                entity_registry=entity_registry,
            )

        await decision_logger.append(
            decision,
            worker=worker_id,
            model=model_name,
            rule_version=rule_version,
            input_source=input_source,
        )
        decisions.append(decision)

    return PipelineResult(
        decisions=decisions,
        proposed_slots_registered=registered,
        proposed_slots_rejected=rejected,
    )

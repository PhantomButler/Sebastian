from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sebastian.memory.contracts.retrieval import (
    ExplicitMemorySearchRequest,
    ExplicitMemorySearchResult,
    PromptMemoryRequest,
    PromptMemoryResult,
)
from sebastian.memory.retrieval import RetrievalContext, RetrievalPlan, _keep_record
from sebastian.memory.retrieval import retrieve_memory_section

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MemoryRetrievalService:
    async def retrieve_for_prompt(
        self,
        request: PromptMemoryRequest,
        *,
        db_session: AsyncSession,
    ) -> PromptMemoryResult:
        context = RetrievalContext(
            session_id=request.session_id,
            agent_type=request.agent_type,
            user_message=request.user_message,
            subject_id=request.subject_id,
            access_purpose="context_injection",
            active_project_or_agent_context=request.active_project_or_agent_context,
            resident_record_ids=request.resident_record_ids,
            resident_dedupe_keys=request.resident_dedupe_keys,
            resident_canonical_bullets=request.resident_canonical_bullets,
        )
        section = await retrieve_memory_section(context, db_session=db_session)
        return PromptMemoryResult(section=section)

    async def search(
        self,
        request: ExplicitMemorySearchRequest,
        *,
        db_session: AsyncSession,
    ) -> ExplicitMemorySearchResult:
        from sebastian.memory.entity_registry import EntityRegistry
        from sebastian.memory.episode_store import EpisodeMemoryStore
        from sebastian.memory.profile_store import ProfileMemoryStore
        from sebastian.memory.types import MemorySource

        retrieval_ctx = RetrievalContext(
            subject_id=request.subject_id,
            session_id=request.session_id,
            agent_type=request.agent_type,
            user_message=request.query,
            access_purpose="tool_search",
        )

        plan = RetrievalPlan(
            profile_lane=True,
            context_lane=True,
            episode_lane=True,
            relation_lane=True,
        )

        active_lanes: list[tuple[str, int]] = []
        if plan.profile_lane:
            active_lanes.append(("profile", plan.profile_limit))
        if plan.context_lane:
            active_lanes.append(("context", plan.context_limit))
        if plan.episode_lane:
            active_lanes.append(("episode", plan.episode_limit))
        if plan.relation_lane:
            active_lanes.append(("relation", plan.relation_limit))

        requested_limit = max(1, request.limit)
        n_active = len(active_lanes)
        effective_limit = max(requested_limit, n_active) if n_active else requested_limit
        base = effective_limit // n_active if n_active else effective_limit
        remainder = effective_limit % n_active if n_active else 0

        lane_budgets: dict[str, int] = {}
        for idx, (lane_name, plan_limit) in enumerate(active_lanes):
            extra = 1 if idx < remainder else 0
            lane_budgets[lane_name] = min(plan_limit, base + extra)

        profile_store = ProfileMemoryStore(db_session)
        episode_store = EpisodeMemoryStore(db_session)
        entity_registry = EntityRegistry(db_session)

        profile_records = (
            await profile_store.search_active(
                subject_id=request.subject_id,
                limit=lane_budgets["profile"],
            )
            if plan.profile_lane
            else []
        )

        context_records = (
            await profile_store.search_recent_context(
                subject_id=request.subject_id,
                query=request.query,
                limit=lane_budgets["context"],
            )
            if plan.context_lane
            else []
        )

        episode_records: list[Any] = []
        if plan.episode_lane:
            ep_budget = lane_budgets["episode"]
            summary_records = await episode_store.search_summaries_by_query(
                subject_id=request.subject_id,
                query=request.query,
                limit=ep_budget,
            )
            if len(summary_records) >= ep_budget:
                episode_records = summary_records
            else:
                detail_records = await episode_store.search_episodes_only(
                    subject_id=request.subject_id,
                    query=request.query,
                    limit=ep_budget - len(summary_records),
                )
                episode_records = [*summary_records, *detail_records]

        relation_records: list[Any] = (
            await entity_registry.list_relations(
                subject_id=request.subject_id,
                limit=lane_budgets["relation"],
            )
            if plan.relation_lane
            else []
        )

        profile_records = [r for r in profile_records if _keep_record(r, context=retrieval_ctx)]
        context_records = [r for r in context_records if _keep_record(r, context=retrieval_ctx)]
        episode_records = [r for r in episode_records if _keep_record(r, context=retrieval_ctx)]
        relation_records = [r for r in relation_records if _keep_record(r, context=retrieval_ctx)]

        seen_ids: set[str] = set()

        def _dedup(records: list[Any]) -> list[Any]:
            out: list[Any] = []
            for r in records:
                rid = getattr(r, "id", None)
                if rid is None:
                    out.append(r)
                    continue
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                out.append(r)
            return out

        profile_records = _dedup(profile_records)
        context_records = _dedup(context_records)
        episode_records = _dedup(episode_records)
        relation_records = _dedup(relation_records)

        items: list[dict[str, Any]] = []
        for record in profile_records:
            items.append(
                {
                    "lane": "profile",
                    "kind": record.kind,
                    "content": record.content,
                    "source": record.source,
                    "confidence": record.confidence if record.confidence is not None else 1.0,
                    "citation_type": "current_truth",
                    "is_current": True,
                }
            )
        for record in context_records:
            items.append(
                {
                    "lane": "context",
                    "kind": str(getattr(record.kind, "value", record.kind)),
                    "content": record.content,
                    "source": record.source,
                    "confidence": record.confidence if record.confidence is not None else 1.0,
                    "citation_type": "current_truth",
                    "is_current": True,
                }
            )
        for record in episode_records:
            citation_type = "historical_summary" if record.kind == "summary" else "historical_evidence"
            items.append(
                {
                    "lane": "episode",
                    "kind": record.kind,
                    "content": record.content,
                    "source": record.source,
                    "confidence": record.confidence if record.confidence is not None else 1.0,
                    "citation_type": citation_type,
                    "is_current": False,
                }
            )
        for record in relation_records:
            items.append(
                {
                    "lane": "relation",
                    "kind": "relation",
                    "content": record.content,
                    "source": getattr(record, "source", MemorySource.SYSTEM_DERIVED.value),
                    "confidence": record.confidence if record.confidence is not None else 1.0,
                    "citation_type": "current_truth",
                    "is_current": True,
                }
            )

        return ExplicitMemorySearchResult(items=items)

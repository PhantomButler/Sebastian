from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import jieba  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from sebastian.memory.resident_dedupe import (
    canonical_bullet as _canonical_bullet,
)
from sebastian.memory.resident_dedupe import (
    slot_value_dedupe_key as _slot_value_dedupe_key,
)
from sebastian.memory.retrieval_lexicon import (
    CONTEXT_LANE_WORDS,
    EPISODE_LANE_WORDS,
    PROFILE_LANE_WORDS,
    RELATION_LANE_STATIC_WORDS,
    SMALL_TALK_WORDS,
)
from sebastian.memory.trace import record_ref, trace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.entity_registry import EntityRegistry

DO_NOT_AUTO_INJECT_TAG = "do_not_auto_inject"

# 硬过滤线：任何路径丢 confidence < 0.3 的记录（spec §6 / artifact-model.md §9.3）
MIN_CONFIDENCE_HARD: float = 0.3

# 自动注入门槛：仅 context_injection 路径额外要求 confidence >= 0.5
MIN_CONFIDENCE_AUTO_INJECT: float = 0.5


def _keep_record(
    record: Any,
    *,
    context: RetrievalContext,
    min_confidence: float = MIN_CONFIDENCE_HARD,
) -> bool:
    """Return True if *record* should be included in retrieval results.

    **Hard-line only — NOT for context_injection path.**

    This function applies only the hard confidence floor
    (``MIN_CONFIDENCE_HARD = 0.3``).  It does **not** apply the
    auto-inject gate (``MIN_CONFIDENCE_AUTO_INJECT = 0.5``), so records
    in the mid-band ``[0.3, 0.5)`` will pass here.

    This is intentional: ``_keep_record`` is used by the ``memory_search``
    tool (``access_purpose="tool_search"``), which must see mid-band records.
    For context_injection filtering — where the 0.5 gate must be enforced —
    use :meth:`MemorySectionAssembler.assemble` instead.

    The ``do_not_auto_inject`` tag is only a blocker when
    ``context.access_purpose == "context_injection"``; explicit tool-search
    calls (``access_purpose="tool_search"``) still receive those records.
    """
    now = datetime.now(UTC)
    policy_tags = getattr(record, "policy_tags", None) or []

    if context.access_purpose == "context_injection" and DO_NOT_AUTO_INJECT_TAG in policy_tags:
        return False

    for tag in policy_tags:
        if tag.startswith("access:"):
            _, allowed_purpose = tag.split(":", 1)
            if allowed_purpose != context.access_purpose:
                return False
        if tag.startswith("agent:"):
            _, allowed_agent = tag.split(":", 1)
            if allowed_agent != context.agent_type:
                return False

    confidence = getattr(record, "confidence", 1.0)
    if confidence is not None and float(confidence) < min_confidence:
        return False

    valid_until = getattr(record, "valid_until", None)
    if valid_until is not None:
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=UTC)
        if valid_until <= now:
            return False

    status = getattr(record, "status", None)
    if status is not None and status != "active":
        return False

    record_subject = getattr(record, "subject_id", None)
    if record_subject is not None and context.subject_id and record_subject != context.subject_id:
        return False

    valid_from = getattr(record, "valid_from", None)
    if valid_from is not None:
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=UTC)
        if valid_from > now:
            return False

    return True


class RetrievalContext(BaseModel):
    subject_id: str
    session_id: str
    agent_type: str
    user_message: str
    access_purpose: str = "context_injection"
    active_project_or_agent_context: dict[str, Any] | None = None
    # Resident memory dedup sets — populated by the resident snapshot injector so that
    # MemorySectionAssembler can skip records already present in the system prompt.
    resident_record_ids: set[str] = Field(default_factory=set)
    resident_dedupe_keys: set[str] = Field(default_factory=set)
    resident_canonical_bullets: set[str] = Field(default_factory=set)


class RetrievalPlan(BaseModel):
    profile_lane: bool = True
    context_lane: bool = False
    episode_lane: bool = False
    relation_lane: bool = False
    profile_limit: int = 5
    context_limit: int = 3
    episode_limit: int = 3
    relation_limit: int = 3


class MemoryRetrievalPlanner:
    """Intent-based lane activator using jieba precise tokenization + set intersection.

    Relation lane's trigger set is dynamic: `bootstrap_entity_triggers()` merges
    all canonical entity names + aliases from EntityRegistry at startup; each
    EntityRegistry.upsert_entity() call invokes `reload_entity_triggers()` to
    keep the cache in sync. See spec §7.6 / §7.7.
    """

    def __init__(self) -> None:
        self._relation_trigger_set: frozenset[str] = RELATION_LANE_STATIC_WORDS

    async def bootstrap_entity_triggers(self, registry: EntityRegistry) -> None:
        """启动期调用：把 Entity Registry 全量 name/aliases 合并进 relation 触发词。

        同时向 jieba 注册自定义词，确保分词时实体名不被拆散。
        """
        from sebastian.memory.segmentation import add_entity_terms

        entity_names = await registry.list_all_names_and_aliases()
        add_entity_terms(entity_names)
        self._relation_trigger_set = RELATION_LANE_STATIC_WORDS | frozenset(entity_names)

    async def reload_entity_triggers(self, registry: EntityRegistry) -> None:
        """Entity 写入末尾调用，刷新触发词缓存。与 bootstrap_entity_triggers 行为相同，
        命名区分是为了调用场景语义清晰（写入触发 vs 启动初始化）。
        当前实现全量重扫 DB；实体数量增大后可优化为增量合并。
        """
        await self.bootstrap_entity_triggers(registry)

    def plan(self, context: RetrievalContext) -> RetrievalPlan:
        msg = context.user_message.lower().strip()
        if not msg:
            plan = RetrievalPlan(
                profile_lane=False,
                context_lane=False,
                episode_lane=False,
                relation_lane=False,
            )
        else:
            tokens: set[str] = set(jieba.lcut(msg))

            # Small-talk 短路（短消息 + 问候/致谢词）
            if tokens & SMALL_TALK_WORDS and len(tokens) <= 3:
                plan = RetrievalPlan(
                    profile_lane=False,
                    context_lane=False,
                    episode_lane=False,
                    relation_lane=False,
                )
            else:
                plan = RetrievalPlan(
                    profile_lane=bool(tokens & PROFILE_LANE_WORDS),
                    context_lane=bool(tokens & CONTEXT_LANE_WORDS),
                    episode_lane=bool(tokens & EPISODE_LANE_WORDS),
                    relation_lane=bool(tokens & self._relation_trigger_set),
                )
        trace(
            "retrieval.plan",
            session_id=context.session_id,
            agent_type=context.agent_type,
            subject_id=context.subject_id,
            profile_lane=plan.profile_lane,
            context_lane=plan.context_lane,
            episode_lane=plan.episode_lane,
            relation_lane=plan.relation_lane,
            profile_limit=plan.profile_limit,
            context_limit=plan.context_limit,
            episode_limit=plan.episode_limit,
            relation_limit=plan.relation_limit,
        )
        return plan


# Module-level singleton — gateway bootstrap 写入，retrieve_memory_section 读取
DEFAULT_RETRIEVAL_PLANNER: MemoryRetrievalPlanner = MemoryRetrievalPlanner()


class MemorySectionAssembler:
    def assemble(
        self,
        *,
        profile_records: list[Any],
        context_records: list[Any],
        episode_records: list[Any],
        relation_records: list[Any],
        plan: RetrievalPlan,
        context: RetrievalContext | None = None,
        min_confidence: float = MIN_CONFIDENCE_HARD,
    ) -> str:
        """Build memory context string with 4 sections for system prompt injection.

        Applies spec retrieval.md §6 filters:
          1. Drop records tagged ``do_not_auto_inject``.
          2. Drop records with ``confidence < min_confidence``.
          3. Drop records with ``valid_until`` <= now.

        Then applies per-lane limits and renders in order:
        profiles (current facts) → contexts (current context) →
        relations (important relationships) → episodes (historical evidence).
        """
        now = datetime.now(UTC)
        effective_context = context or RetrievalContext(
            subject_id="",
            session_id="",
            agent_type="",
            user_message="",
        )

        filter_counts: dict[str, int] = {
            "do_not_auto_inject": 0,
            "access_policy": 0,
            "agent_policy": 0,
            "confidence": 0,
            "valid_until": 0,
            "valid_from": 0,
        }

        def _keep(record: Any) -> bool:
            policy_tags = getattr(record, "policy_tags", None) or []
            if (
                effective_context.access_purpose == "context_injection"
                and DO_NOT_AUTO_INJECT_TAG in policy_tags
            ):
                filter_counts["do_not_auto_inject"] += 1
                return False
            for tag in policy_tags:
                if tag.startswith("access:"):
                    _, allowed_purpose = tag.split(":", 1)
                    if allowed_purpose != effective_context.access_purpose:
                        filter_counts["access_policy"] += 1
                        return False
                if tag.startswith("agent:"):
                    _, allowed_agent = tag.split(":", 1)
                    if allowed_agent != effective_context.agent_type:
                        filter_counts["agent_policy"] += 1
                        return False
            confidence = getattr(record, "confidence", 1.0)

            # 硬线（任何路径都丢）
            if confidence is not None and confidence < min_confidence:
                filter_counts["confidence"] += 1
                return False

            # 自动注入门槛（仅 context_injection 应用）
            if (
                effective_context.access_purpose == "context_injection"
                and confidence is not None
                and confidence < MIN_CONFIDENCE_AUTO_INJECT
            ):
                filter_counts["confidence"] += 1
                return False

            valid_until = getattr(record, "valid_until", None)
            if valid_until is not None:
                # Treat naive datetimes as UTC to stay compatible with sqlite storage.
                if valid_until.tzinfo is None:
                    valid_until = valid_until.replace(tzinfo=UTC)
                if valid_until <= now:
                    filter_counts["valid_until"] += 1
                    return False

            status = getattr(record, "status", None)
            if status is not None and status != "active":
                return False

            record_subject = getattr(record, "subject_id", None)
            if (
                record_subject is not None
                and effective_context.subject_id
                and record_subject != effective_context.subject_id
            ):
                return False

            valid_from = getattr(record, "valid_from", None)
            if valid_from is not None:
                if valid_from.tzinfo is None:
                    valid_from = valid_from.replace(tzinfo=UTC)
                if valid_from > now:
                    filter_counts["valid_from"] += 1
                    return False

            return True

        def _not_resident_duplicate(record: Any) -> bool:
            """Return False if *record* is already injected by resident memory snapshot.

            Dedup order per spec §11: record id → canonical bullet → slot_value key.
            """
            record_id = getattr(record, "id", None)
            if record_id and record_id in effective_context.resident_record_ids:
                return False
            # canonical bullet check comes before slot_value per spec §11
            bullet = _canonical_bullet(getattr(record, "content", "") or "")
            if bullet and bullet in effective_context.resident_canonical_bullets:
                return False
            key = _slot_value_dedupe_key(
                subject_id=getattr(record, "subject_id", None) or effective_context.subject_id,
                slot_id=getattr(record, "slot_id", None),
                structured_payload=getattr(record, "structured_payload", None) or {},
            )
            if key and key in effective_context.resident_dedupe_keys:
                return False
            return True

        profiles = [r for r in profile_records if _keep(r) and _not_resident_duplicate(r)][
            : plan.profile_limit
        ]
        contexts = [r for r in context_records if _keep(r)][: plan.context_limit]
        relations = [r for r in relation_records if _keep(r)][: plan.relation_limit]
        episodes = [r for r in episode_records if _keep(r)][: plan.episode_limit]

        trace(
            "retrieval.filter",
            session_id=effective_context.session_id,
            agent_type=effective_context.agent_type,
            subject_id=effective_context.subject_id,
            **filter_counts,
        )

        sections: list[str] = []

        if profiles:
            lines = "\n".join(f"- [{r.kind}] {r.content}" for r in profiles)
            sections.append(f"## Current facts about user\n{lines}")

        if contexts:
            lines = "\n".join(f"- [{_record_kind(r, 'fact')}] {r.content}" for r in contexts)
            sections.append(f"## Current context\n{lines}")

        if relations:
            lines = "\n".join(f"- [relation] {_render_relation(r)}" for r in relations)
            sections.append(f"## Important relationships\n{lines}")

        if episodes:
            lines = "\n".join(f"- [{_record_kind(r, 'episode')}] {r.content}" for r in episodes)
            sections.append(f"## Historical evidence (may be outdated)\n{lines}")

        trace(
            "retrieval.assemble",
            session_id=effective_context.session_id,
            agent_type=effective_context.agent_type,
            subject_id=effective_context.subject_id,
            profile_count=len(profiles),
            context_count=len(contexts),
            relation_count=len(relations),
            episode_count=len(episodes),
            items=[record_ref(r) for r in [*profiles, *contexts, *relations, *episodes]],
        )
        return "\n\n".join(sections)


def _record_kind(record: Any, fallback: str) -> str:
    """Return the kind label for a record as a plain string.

    Handles both string kinds and enum-valued kinds (via ``.value``).
    Falls back to *fallback* when the attribute is absent or None.
    """
    kind = getattr(record, "kind", None)
    if kind is None:
        return fallback
    value = getattr(kind, "value", kind)
    return str(value)


def _render_relation(record: Any) -> str:
    """Render a relation record as ``subject_id predicate object_ref``.

    ``RelationCandidateRecord`` has no ``object_ref`` column; prefer
    ``target_entity_id`` and fall back to ``content`` when both IDs are unset.
    """
    subject_id = getattr(record, "source_entity_id", None) or getattr(record, "subject_id", "")
    predicate = getattr(record, "predicate", "")
    object_ref = (
        getattr(record, "target_entity_id", None)
        or getattr(record, "object_ref", None)
        or getattr(record, "content", "")
    )
    return f"{subject_id} {predicate} {object_ref}".strip()


async def retrieve_memory_section(
    context: RetrievalContext,
    *,
    db_session: AsyncSession,
) -> str:
    """Full retrieval pipeline: plan → fetch → assemble → return string."""
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore

    planner = DEFAULT_RETRIEVAL_PLANNER
    plan = planner.plan(context)

    profile_store = ProfileMemoryStore(db_session)
    episode_store = EpisodeMemoryStore(db_session)

    profile_records: list[Any] = []
    if plan.profile_lane:
        profile_records = await profile_store.search_active(
            subject_id=context.subject_id,
            limit=plan.profile_limit,
        )
    trace(
        "retrieval.fetch",
        session_id=context.session_id,
        subject_id=context.subject_id,
        lane="profile",
        count=len(profile_records),
        items=[record_ref(r) for r in profile_records],
    )

    context_records: list[Any] = []
    if plan.context_lane:
        context_records = await profile_store.search_recent_context(
            subject_id=context.subject_id,
            query=context.user_message,
            limit=plan.context_limit,
        )
    trace(
        "retrieval.fetch",
        session_id=context.session_id,
        subject_id=context.subject_id,
        lane="context",
        count=len(context_records),
        items=[record_ref(r) for r in context_records],
    )

    episode_records: list[Any] = []
    if plan.episode_lane:
        summary_records = await episode_store.search_summaries_by_query(
            subject_id=context.subject_id,
            query=context.user_message,
            limit=plan.episode_limit,
        )
        if len(summary_records) >= plan.episode_limit:
            episode_records = summary_records
        else:
            remaining = plan.episode_limit - len(summary_records)
            detail_records = await episode_store.search_episodes_only(
                subject_id=context.subject_id,
                query=context.user_message,
                limit=remaining,
            )
            episode_records = [*summary_records, *detail_records]
    trace(
        "retrieval.fetch",
        session_id=context.session_id,
        subject_id=context.subject_id,
        lane="episode",
        count=len(episode_records),
        items=[record_ref(r) for r in episode_records],
    )

    relation_records: list[Any] = []
    if plan.relation_lane:
        from sebastian.memory.entity_registry import EntityRegistry

        relation_registry = EntityRegistry(db_session)
        relation_records = await relation_registry.list_relations(
            subject_id=context.subject_id,
            limit=plan.relation_limit,
        )
    trace(
        "retrieval.fetch",
        session_id=context.session_id,
        subject_id=context.subject_id,
        lane="relation",
        count=len(relation_records),
        items=[record_ref(r) for r in relation_records],
    )

    assembler = MemorySectionAssembler()
    return assembler.assemble(
        profile_records=profile_records,
        context_records=context_records,
        episode_records=episode_records,
        relation_records=relation_records,
        plan=plan,
        context=context,
    )

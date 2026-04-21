from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.retrieval import (
    MemoryRetrievalPlanner,
    MemorySectionAssembler,
    RetrievalContext,
    RetrievalPlan,
    retrieve_memory_section,
)
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base

# ---------------------------------------------------------------------------
# Minimal fake records (no DB required)
# ---------------------------------------------------------------------------


@dataclass
class FakeProfileRecord:
    kind: str
    content: str
    id: str = "profile-1"
    slot_id: str | None = "slot-1"
    subject_id: str | None = None
    status: str = "active"
    policy_tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    valid_until: datetime | None = None
    valid_from: datetime | None = None


@dataclass
class FakeContextRecord:
    content: str
    id: str = "context-1"
    kind: str = "fact"
    slot_id: str | None = "slot-context"
    subject_id: str | None = None
    status: str = "active"
    policy_tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    valid_until: datetime | None = None
    valid_from: datetime | None = None


@dataclass
class FakeEpisodeRecord:
    content: str
    id: str = "episode-1"
    kind: str = "episode"
    slot_id: str | None = None
    subject_id: str | None = None
    status: str = "active"
    policy_tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    valid_until: datetime | None = None
    valid_from: datetime | None = None


@dataclass
class FakeRelationRecord:
    source_entity_id: str
    predicate: str
    target_entity_id: str | None = None
    id: str = "relation-1"
    kind: str = "relation"
    slot_id: str | None = None
    subject_id: str | None = None
    status: str = "active"
    content: str = ""
    policy_tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    valid_until: datetime | None = None
    valid_from: datetime | None = None


def _ctx(msg: str = "你好") -> RetrievalContext:
    return RetrievalContext(
        subject_id="user-1",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message=msg,
    )


def _plan(**kw: Any) -> RetrievalPlan:
    defaults = {
        "profile_lane": True,
        "context_lane": True,
        "episode_lane": True,
        "relation_lane": True,
    }
    defaults.update(kw)
    return RetrievalPlan(**defaults)


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------


class TestMemoryRetrievalPlanner:
    def test_profile_lane_always_enabled(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("普通打招呼"))
        assert plan.profile_lane is True

    def test_episode_lane_disabled_for_normal_turn(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("帮我设个提醒"))
        assert plan.episode_lane is False

    def test_episode_lane_enabled_for_shanggci(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("上次我们聊的那件事"))
        assert plan.episode_lane is True

    def test_episode_lane_enabled_for_taolun(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("关于那个讨论，你还记得吗"))
        assert plan.episode_lane is True

    def test_episode_lane_enabled_for_english_keywords(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("do you remember what we discussed last time?"))
        assert plan.episode_lane is True

    def test_plan_returns_retrieval_plan_instance(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx())
        assert isinstance(plan, RetrievalPlan)

    def test_retrieval_plan_has_four_lanes(self) -> None:
        plan = RetrievalPlan()
        assert hasattr(plan, "context_lane")
        assert hasattr(plan, "episode_lane")
        assert hasattr(plan, "relation_lane")
        assert plan.profile_limit > 0
        assert plan.context_limit > 0
        assert plan.episode_limit > 0
        assert plan.relation_limit > 0

    def test_planner_keeps_profile_lane_for_small_talk(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("hi"))
        assert plan.profile_lane is True
        assert plan.context_lane is False
        assert plan.episode_lane is False
        assert plan.relation_lane is False

    def test_planner_activates_episode_lane_on_keyword(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("上次我们讨论的事"))
        assert plan.episode_lane is True
        assert plan.profile_lane is True

    def test_planner_activates_context_lane_on_keyword(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("今天的安排"))
        assert plan.context_lane is True

    def test_planner_activates_relation_lane_on_keyword(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("老婆喜欢什么"))
        assert plan.relation_lane is True


# ---------------------------------------------------------------------------
# Assembler tests
# ---------------------------------------------------------------------------


class TestMemorySectionAssembler:
    def test_filters_do_not_auto_inject_from_profile(self) -> None:
        records = [
            FakeProfileRecord(kind="preference", content="喜欢深色模式"),
            FakeProfileRecord(
                kind="preference", content="敏感数据", policy_tags=["do_not_auto_inject"]
            ),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "敏感数据" not in result
        assert "喜欢深色模式" in result

    def test_filters_do_not_auto_inject_from_episodes(self) -> None:
        episodes = [
            FakeEpisodeRecord(content="上次聊了旅行计划"),
            FakeEpisodeRecord(content="隐私内容", policy_tags=["do_not_auto_inject"]),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=episodes,
            relation_records=[],
            plan=_plan(),
        )
        assert "隐私内容" not in result
        assert "上次聊了旅行计划" in result

    def test_profile_records_appear_under_correct_section(self) -> None:
        records = [FakeProfileRecord(kind="preference", content="喜欢简短回答")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "## Current facts about user" in result
        assert "喜欢简短回答" in result

    def test_episode_records_appear_under_correct_section(self) -> None:
        episodes = [FakeEpisodeRecord(content="讨论了健身计划")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=episodes,
            relation_records=[],
            plan=_plan(),
        )
        assert "## Historical evidence (may be outdated)" in result
        assert "讨论了健身计划" in result

    def test_empty_profile_section_omitted(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[FakeEpisodeRecord(content="某段记忆")],
            relation_records=[],
            plan=_plan(),
        )
        assert "## Current facts about user" not in result

    def test_empty_episode_section_omitted(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[FakeProfileRecord(kind="trait", content="外向")],
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "## Historical evidence" not in result

    def test_returns_empty_when_no_records(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert result == ""

    def test_returns_empty_when_all_filtered(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[
                FakeProfileRecord(kind="pref", content="x", policy_tags=["do_not_auto_inject"])
            ],
            context_records=[],
            episode_records=[FakeEpisodeRecord(content="y", policy_tags=["do_not_auto_inject"])],
            relation_records=[],
            plan=_plan(),
        )
        assert result == ""

    def test_profile_kind_included_in_output(self) -> None:
        records = [FakeProfileRecord(kind="preference", content="喜欢音乐")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "[preference]" in result

    def test_assembler_filters_low_confidence_records(self) -> None:
        records = [
            FakeProfileRecord(kind="pref", content="high-conf", confidence=0.9),
            FakeProfileRecord(kind="pref", content="low-conf", confidence=0.2),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "high-conf" in result
        assert "low-conf" not in result

    def test_assembler_filters_expired_records(self) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        future = datetime.now(UTC) + timedelta(days=1)
        records = [
            FakeProfileRecord(kind="pref", content="still-valid", valid_until=future),
            FakeProfileRecord(kind="pref", content="expired", valid_until=past),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "still-valid" in result
        assert "expired" not in result

    def test_assembler_filters_do_not_auto_inject_tag(self) -> None:
        records = [
            FakeProfileRecord(kind="pref", content="keep"),
            FakeProfileRecord(kind="pref", content="drop", policy_tags=["do_not_auto_inject"]),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "keep" in result
        assert "drop" not in result

    def test_assembler_keeps_do_not_auto_inject_for_tool_search(self) -> None:
        records = [
            FakeProfileRecord(
                kind="pref",
                content="search-only-visible",
                policy_tags=["do_not_auto_inject"],
            )
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx("tool query").model_copy(update={"access_purpose": "tool_search"}),
        )
        assert "search-only-visible" in result

    def test_assembler_filters_access_policy_tags_by_purpose(self) -> None:
        records = [
            FakeProfileRecord(
                kind="pref",
                content="tool-only",
                policy_tags=["access:tool_search"],
            ),
            FakeProfileRecord(kind="pref", content="general"),
        ]
        assembler = MemorySectionAssembler()
        injection_result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx("inject"),
        )
        tool_result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx("search").model_copy(update={"access_purpose": "tool_search"}),
        )

        assert "tool-only" not in injection_result
        assert "general" in injection_result
        assert "tool-only" in tool_result
        assert "general" in tool_result

    def test_assembler_filters_agent_policy_tags_by_reader_agent(self) -> None:
        records = [
            FakeProfileRecord(kind="pref", content="forge-only", policy_tags=["agent:forge"]),
            FakeProfileRecord(kind="pref", content="general"),
        ]
        assembler = MemorySectionAssembler()
        sebas_result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx("inject"),
        )
        forge_result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx("inject").model_copy(update={"agent_type": "forge"}),
        )

        assert "forge-only" not in sebas_result
        assert "general" in sebas_result
        assert "forge-only" in forge_result
        assert "general" in forge_result

    def test_assembler_renders_all_four_sections(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[FakeProfileRecord(kind="pref", content="P1")],
            context_records=[FakeContextRecord(content="C1")],
            episode_records=[FakeEpisodeRecord(content="E1")],
            relation_records=[
                FakeRelationRecord(
                    source_entity_id="user",
                    predicate="has_spouse",
                    target_entity_id="alice",
                )
            ],
            plan=_plan(),
        )
        # All four headers present
        assert "## Current facts about user" in result
        assert "## Current context" in result
        assert "## Important relationships" in result
        assert "## Historical evidence (may be outdated)" in result
        # Order: profile → context → relation → episode
        idx_profile = result.index("## Current facts about user")
        idx_context = result.index("## Current context")
        idx_relation = result.index("## Important relationships")
        idx_episode = result.index("## Historical evidence")
        assert idx_profile < idx_context < idx_relation < idx_episode

    def test_assembler_renders_historical_warning(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[FakeEpisodeRecord(content="old")],
            relation_records=[],
            plan=_plan(),
        )
        assert "may be outdated" in result

    def test_assembler_returns_empty_when_no_records(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert result == ""

    def test_assembler_respects_per_lane_limits(self) -> None:
        records = [FakeProfileRecord(kind="pref", content=f"profile-{i}") for i in range(5)]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(profile_limit=2),
        )
        bullets = [line for line in result.splitlines() if line.startswith("- ")]
        assert len(bullets) == 2
        assert "profile-0" in result
        assert "profile-1" in result
        assert "profile-2" not in result

    def test_assembler_renders_relation_with_target_entity(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[],
            relation_records=[
                FakeRelationRecord(
                    source_entity_id="user",
                    predicate="has_spouse",
                    target_entity_id="alice",
                )
            ],
            plan=_plan(),
        )
        assert "user has_spouse alice" in result

    def test_assembler_renders_relation_fallback_to_content(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[],
            relation_records=[
                FakeRelationRecord(
                    source_entity_id="user",
                    predicate="prefers",
                    target_entity_id=None,
                    content="dark mode",
                )
            ],
            plan=_plan(),
        )
        assert "user prefers dark mode" in result

    def test_assembler_logs_filter_counts_and_injected_items(self, caplog) -> None:
        caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
        records = [
            FakeProfileRecord(kind="pref", content="keep", id="keep-1"),
            FakeProfileRecord(
                kind="pref",
                content="do-not-log-full",
                id="drop-auto",
                policy_tags=["do_not_auto_inject"],
            ),
            FakeProfileRecord(
                kind="pref",
                content="tool-only",
                id="drop-access",
                policy_tags=["access:tool_search"],
            ),
            FakeProfileRecord(
                kind="pref",
                content="forge-only",
                id="drop-agent",
                policy_tags=["agent:forge"],
            ),
            FakeProfileRecord(kind="pref", content="low", id="drop-conf", confidence=0.1),
            FakeProfileRecord(
                kind="pref",
                content="expired",
                id="drop-expired",
                valid_until=datetime.now(UTC) - timedelta(days=1),
            ),
            FakeProfileRecord(
                kind="pref",
                content="not-yet",
                id="drop-valid-from",
                valid_from=datetime.now(UTC) + timedelta(days=1),
            ),
        ]

        result = MemorySectionAssembler().assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx("inject"),
        )

        assert "keep" in result
        assert "MEMORY_TRACE retrieval.filter" in caplog.text
        assert "do_not_auto_inject=1" in caplog.text
        assert "access_policy=1" in caplog.text
        assert "agent_policy=1" in caplog.text
        assert "confidence=1" in caplog.text
        assert "valid_until=1" in caplog.text
        assert "valid_from=1" in caplog.text
        assert "MEMORY_TRACE retrieval.assemble" in caplog.text
        assert "keep-1" in caplog.text

    def test_assembler_filters_valid_from_future(self) -> None:
        """Records with valid_from in the future must not be injected."""
        future = datetime.now(UTC) + timedelta(days=1)
        records = [
            FakeProfileRecord(kind="pref", content="now-active", valid_from=None),
            FakeProfileRecord(kind="pref", content="not-yet-active", valid_from=future),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx(),
        )
        assert "now-active" in result
        assert "not-yet-active" not in result

    def test_assembler_filters_non_active_status(self) -> None:
        """Records with status != 'active' must not be injected."""
        records = [
            FakeProfileRecord(kind="pref", content="is-active", status="active"),
            FakeProfileRecord(kind="pref", content="is-superseded", status="superseded"),
            FakeProfileRecord(kind="pref", content="is-expired", status="expired"),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx(),
        )
        assert "is-active" in result
        assert "is-superseded" not in result
        assert "is-expired" not in result

    def test_assembler_filters_wrong_subject_id(self) -> None:
        """Records with subject_id not matching context.subject_id must not be injected."""
        records = [
            FakeProfileRecord(kind="pref", content="correct-subject", subject_id="user-1"),
            FakeProfileRecord(kind="pref", content="no-subject", subject_id=None),
            FakeProfileRecord(kind="pref", content="wrong-subject", subject_id="other-user"),
        ]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            context_records=[],
            episode_records=[],
            relation_records=[],
            plan=_plan(),
            context=_ctx(),
        )
        assert "correct-subject" in result
        assert "no-subject" in result
        assert "wrong-subject" not in result

    def test_context_lane_includes_kind_label(self) -> None:
        """Context lane must render [kind] label before content."""
        records = [FakeContextRecord(content="当前项目是 Sebastian", kind="fact")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=records,
            episode_records=[],
            relation_records=[],
            plan=_plan(),
        )
        assert "- [fact] 当前项目是 Sebastian" in result

    def test_episode_lane_includes_kind_label_summary(self) -> None:
        """Episode lane must render [kind] label for summary records."""
        records = [FakeEpisodeRecord(content="上次讨论了记忆模块", kind="summary")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=records,
            relation_records=[],
            plan=_plan(),
        )
        assert "- [summary] 上次讨论了记忆模块" in result

    def test_episode_lane_includes_kind_label_episode(self) -> None:
        """Episode lane must render [kind] label for episode records."""
        records = [FakeEpisodeRecord(content="用户确认了方案", kind="episode")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=records,
            relation_records=[],
            plan=_plan(),
        )
        assert "- [episode] 用户确认了方案" in result

    def test_relation_lane_includes_relation_kind_prefix(self) -> None:
        """Relation lane must render [relation] prefix before the rendered triple."""
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            context_records=[],
            episode_records=[],
            relation_records=[
                FakeRelationRecord(
                    source_entity_id="user",
                    predicate="has_spouse",
                    target_entity_id="alice",
                )
            ],
            plan=_plan(),
        )
        assert "- [relation] user has_spouse alice" in result


# ---------------------------------------------------------------------------
# retrieve_memory_section — integration with context lane
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_retrieve_memory_section_calls_context_lane(db_session, caplog) -> None:
    """When planner activates context_lane, search_recent_context must be invoked."""
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="今天有什么安排",
    )
    with patch(
        "sebastian.memory.profile_store.ProfileMemoryStore.search_recent_context",
        new=AsyncMock(return_value=[]),
    ) as spy:
        await retrieve_memory_section(context, db_session=db_session)
        spy.assert_awaited_once()
        kwargs = spy.await_args.kwargs
        assert kwargs["subject_id"] == "owner"
        assert kwargs["limit"] == 3
    assert "MEMORY_TRACE retrieval.plan" in caplog.text
    assert "context_lane=True" in caplog.text
    assert "MEMORY_TRACE retrieval.fetch" in caplog.text
    assert "lane=context" in caplog.text


async def test_retrieve_memory_section_skips_context_lane_when_inactive(db_session) -> None:
    """When planner does not activate context_lane, search_recent_context must NOT be invoked."""
    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="帮我设个提醒",
    )
    with patch(
        "sebastian.memory.profile_store.ProfileMemoryStore.search_recent_context",
        new=AsyncMock(return_value=[]),
    ) as spy:
        await retrieve_memory_section(context, db_session=db_session)
        spy.assert_not_awaited()


async def test_retrieve_memory_section_calls_relation_lane(db_session) -> None:
    """When planner activates relation_lane, list_relations must be invoked."""
    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="老婆喜欢什么",
    )
    with patch(
        "sebastian.memory.entity_registry.EntityRegistry.list_relations",
        new=AsyncMock(return_value=[]),
    ) as spy:
        await retrieve_memory_section(context, db_session=db_session)
        spy.assert_awaited_once()
        kwargs = spy.await_args.kwargs
        assert kwargs["subject_id"] == "owner"
        assert kwargs["limit"] == 3


async def test_retrieve_memory_section_skips_relation_lane_when_inactive(db_session) -> None:
    """When planner does not activate relation_lane, list_relations must NOT be invoked."""
    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="帮我设个提醒",
    )
    with patch(
        "sebastian.memory.entity_registry.EntityRegistry.list_relations",
        new=AsyncMock(return_value=[]),
    ) as spy:
        await retrieve_memory_section(context, db_session=db_session)
        spy.assert_not_awaited()


# ---------------------------------------------------------------------------
# retrieve_memory_section — episode lane summary-first behaviour
# ---------------------------------------------------------------------------


async def test_episode_lane_uses_only_summaries_when_budget_filled(db_session) -> None:
    """When search_summaries_by_query returns >= episode_limit records, no detail search."""
    summary_records = [FakeEpisodeRecord(content=f"摘要{i}", kind="summary") for i in range(3)]

    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="上次讨论的健身计划",
    )
    with (
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_summaries_by_query",
            new=AsyncMock(return_value=summary_records),
        ) as summary_spy,
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_episodes_only",
            new=AsyncMock(return_value=[]),
        ) as detail_spy,
    ):
        result = await retrieve_memory_section(context, db_session=db_session)

    summary_spy.assert_awaited_once()
    detail_spy.assert_not_awaited()
    for i in range(3):
        assert f"摘要{i}" in result


async def test_episode_lane_supplements_with_detail_when_summaries_insufficient(
    db_session,
) -> None:
    """When summaries < episode_limit, episode detail fills remaining budget."""
    summary_records = [FakeEpisodeRecord(content="摘要0", kind="summary")]
    detail_records = [
        FakeEpisodeRecord(content="经历细节0"),
        FakeEpisodeRecord(content="经历细节1"),
    ]

    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="上次讨论的健身计划",
    )
    with (
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_summaries_by_query",
            new=AsyncMock(return_value=summary_records),
        ) as summary_spy,
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_episodes_only",
            new=AsyncMock(return_value=detail_records),
        ) as detail_spy,
    ):
        result = await retrieve_memory_section(context, db_session=db_session)

    summary_spy.assert_awaited_once()
    detail_spy.assert_awaited_once()
    # remaining = episode_limit(3) - 1 summary = 2
    detail_kwargs = detail_spy.await_args.kwargs
    assert detail_kwargs["limit"] == 2
    assert "摘要0" in result
    assert "经历细节0" in result
    assert "经历细节1" in result


def test_retrieval_context_accepts_active_project_or_agent_context() -> None:
    ctx = RetrievalContext(
        subject_id="user:owner",
        session_id="sess-1",
        agent_type="sebastian",
        user_message="现在项目做什么",
        active_project_or_agent_context={"agent_type": "sebastian", "project": "Sebastian"},
    )
    assert ctx.active_project_or_agent_context == {
        "agent_type": "sebastian",
        "project": "Sebastian",
    }


async def test_episode_lane_irrelevant_summaries_do_not_enter_results(db_session) -> None:
    """Summaries not matching the query must not appear (query-aware, not recency-only)."""
    context = RetrievalContext(
        subject_id="owner",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message="上次讨论的健身计划",
    )
    with (
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_summaries_by_query",
            new=AsyncMock(return_value=[]),  # no matching summaries
        ),
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_episodes_only",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "sebastian.memory.episode_store.EpisodeMemoryStore.search_summaries",
            new=AsyncMock(return_value=[FakeEpisodeRecord(content="不相关的最近摘要")]),
        ) as recency_spy,
    ):
        result = await retrieve_memory_section(context, db_session=db_session)

    # search_summaries (recency-only) must NOT be called for the episode lane
    recency_spy.assert_not_awaited()
    assert "不相关的最近摘要" not in result

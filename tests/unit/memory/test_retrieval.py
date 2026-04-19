from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sebastian.memory.retrieval import (
    MemoryRetrievalPlanner,
    MemorySectionAssembler,
    RetrievalContext,
    RetrievalPlan,
)

# ---------------------------------------------------------------------------
# Minimal fake records (no DB required)
# ---------------------------------------------------------------------------


@dataclass
class FakeProfileRecord:
    kind: str
    content: str
    policy_tags: list[str] = field(default_factory=list)


@dataclass
class FakeEpisodeRecord:
    content: str
    policy_tags: list[str] = field(default_factory=list)


def _ctx(msg: str = "你好") -> RetrievalContext:
    return RetrievalContext(
        subject_id="user-1",
        session_id="sess-1",
        agent_type="orchestrator",
        user_message=msg,
    )


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

    def test_planner_skips_all_lanes_for_small_talk(self) -> None:
        planner = MemoryRetrievalPlanner()
        plan = planner.plan(_ctx("hi"))
        assert plan.profile_lane is False
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
    def _plan(self, **kw: Any) -> RetrievalPlan:
        return RetrievalPlan(profile_lane=True, episode_lane=True, **kw)

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
            episode_records=[],
            plan=self._plan(),
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
            episode_records=episodes,
            plan=self._plan(),
        )
        assert "隐私内容" not in result
        assert "上次聊了旅行计划" in result

    def test_profile_records_appear_under_correct_section(self) -> None:
        records = [FakeProfileRecord(kind="preference", content="喜欢简短回答")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            episode_records=[],
            plan=self._plan(),
        )
        assert "## What I know about the user" in result
        assert "喜欢简短回答" in result

    def test_episode_records_appear_under_correct_section(self) -> None:
        episodes = [FakeEpisodeRecord(content="讨论了健身计划")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            episode_records=episodes,
            plan=self._plan(),
        )
        assert "## Relevant past episodes" in result
        assert "讨论了健身计划" in result

    def test_empty_profile_section_omitted(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            episode_records=[FakeEpisodeRecord(content="某段记忆")],
            plan=self._plan(),
        )
        assert "## What I know about the user" not in result

    def test_empty_episode_section_omitted(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[FakeProfileRecord(kind="trait", content="外向")],
            episode_records=[],
            plan=self._plan(),
        )
        assert "## Relevant past episodes" not in result

    def test_returns_empty_string_when_no_records(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[],
            episode_records=[],
            plan=self._plan(),
        )
        assert result == ""

    def test_returns_empty_string_when_all_filtered(self) -> None:
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=[
                FakeProfileRecord(kind="pref", content="x", policy_tags=["do_not_auto_inject"])
            ],
            episode_records=[
                FakeEpisodeRecord(content="y", policy_tags=["do_not_auto_inject"])
            ],
            plan=self._plan(),
        )
        assert result == ""

    def test_respects_max_total_items(self) -> None:
        # Feed 10 profile records + 3 episode records → total must not exceed 8
        profiles = [
            FakeProfileRecord(kind="pref", content=f"profile-{i}") for i in range(10)
        ]
        episodes = [FakeEpisodeRecord(content=f"episode-{i}") for i in range(3)]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=profiles,
            episode_records=episodes,
            plan=RetrievalPlan(
                profile_lane=True,
                episode_lane=True,
                profile_limit=10,
                episode_limit=3,
            ),
        )
        # Count bullet points
        bullets = [line for line in result.splitlines() if line.startswith("- ")]
        assert len(bullets) <= 8

    def test_profile_kind_included_in_output(self) -> None:
        records = [FakeProfileRecord(kind="preference", content="喜欢音乐")]
        assembler = MemorySectionAssembler()
        result = assembler.assemble(
            profile_records=records,
            episode_records=[],
            plan=self._plan(),
        )
        assert "[preference]" in result

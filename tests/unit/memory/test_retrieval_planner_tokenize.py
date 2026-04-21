from __future__ import annotations

import pytest

from sebastian.memory.retrieval import (
    MemoryRetrievalPlanner,
    RetrievalContext,
)


def _ctx(msg: str) -> RetrievalContext:
    return RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="sebastian",
        user_message=msg,
    )


@pytest.mark.parametrize(
    "msg",
    ["我需要一封推荐信", "帮我写推荐信", "这是一封推荐信"],
)
def test_recommendation_letter_does_not_trigger_profile(msg: str) -> None:
    """'推荐信' 作为长词不应被拆出 '推荐' 误触发 Profile Lane。"""
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx(msg))
    assert plan.profile_lane is False


def test_recommend_verb_triggers_profile() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("给我推荐一个餐厅"))
    assert plan.profile_lane is True


def test_remember_triggers_episode() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("你还记得我说过的项目吗"))
    assert plan.episode_lane is True


def test_recent_triggers_context() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("最近进展怎么样"))
    assert plan.context_lane is True


def test_relation_static_word_triggers_relation() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx("我老婆今天做了饭"))
    assert plan.relation_lane is True


@pytest.mark.parametrize("msg", ["hi", "你好", "thanks", "ok"])
def test_small_talk_short_circuits_all_lanes(msg: str) -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx(msg))
    assert plan.profile_lane is False
    assert plan.context_lane is False
    assert plan.episode_lane is False
    assert plan.relation_lane is False


def test_empty_message_no_activation() -> None:
    planner = MemoryRetrievalPlanner()
    plan = planner.plan(_ctx(""))
    assert plan.profile_lane is False
    assert plan.context_lane is False
    assert plan.episode_lane is False
    assert plan.relation_lane is False


def test_default_planner_singleton_is_module_level() -> None:
    """retrieve_memory_section 内部必须用同一实例，否则 bootstrap 状态丢失。"""
    from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER

    assert isinstance(DEFAULT_RETRIEVAL_PLANNER, MemoryRetrievalPlanner)

from __future__ import annotations

import pytest

from sebastian.memory.retrieval.retrieval import (
    MemoryRetrievalPlanner,
    RetrievalContext,
)
from sebastian.memory.retrieval.retrieval_lexicon import RELATION_LANE_STATIC_WORDS


def _ctx(msg: str) -> RetrievalContext:
    return RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="sebastian",
        user_message=msg,
    )


class _FakeRegistry:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def list_all_names_and_aliases(self) -> list[str]:
        return list(self._names)


@pytest.mark.asyncio
async def test_bootstrap_merges_entity_names() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美", "豆豆"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    assert "小美" in planner._relation_trigger_set
    assert "豆豆" in planner._relation_trigger_set
    assert "老婆" in planner._relation_trigger_set  # 静态词仍在


@pytest.mark.asyncio
async def test_bootstrap_merges_aliases() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美", "美美", "小美同学"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    for term in ("小美", "美美", "小美同学"):
        assert term in planner._relation_trigger_set


@pytest.mark.asyncio
async def test_entity_name_activates_relation_lane() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    plan = planner.plan(_ctx("小美今天做了饭"))
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_alias_activates_relation_lane() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美", "美美"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    plan = planner.plan(_ctx("美美来了"))
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_reload_reflects_new_entity() -> None:
    planner = MemoryRetrievalPlanner()
    registry = _FakeRegistry(["小美"])
    await planner.bootstrap_entity_triggers(registry)  # type: ignore[arg-type]
    assert "王总" not in planner._relation_trigger_set

    registry._names.append("王总")
    await planner.reload_entity_triggers(registry)  # type: ignore[arg-type]
    assert "王总" in planner._relation_trigger_set
    plan = planner.plan(_ctx("王总来找我"))
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_bootstrap_not_called_static_only() -> None:
    planner = MemoryRetrievalPlanner()
    assert planner._relation_trigger_set == RELATION_LANE_STATIC_WORDS

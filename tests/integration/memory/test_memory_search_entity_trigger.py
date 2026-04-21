from __future__ import annotations

import pytest

from sebastian.memory.entity_registry import EntityRegistry
from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER, RetrievalContext
from sebastian.memory.retrieval_lexicon import RELATION_LANE_STATIC_WORDS


@pytest.mark.asyncio
async def test_default_planner_activates_relation_lane_for_registered_entities(
    tmp_memory_env,
) -> None:
    """DEFAULT_RETRIEVAL_PLANNER (used by the context_injection / auto-inject path)
    should activate relation_lane when the query mentions an entity registered via
    EntityRegistry. Note: memory_search tool bypasses the planner and always probes
    all four lanes — this test covers the planner itself, not the tool."""
    # Reset planner to baseline (no custom entities)
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS

    # Seed a private entity not in static words
    async with tmp_memory_env() as session:
        registry = EntityRegistry(session, planner=DEFAULT_RETRIEVAL_PLANNER)
        await registry.upsert_entity(
            canonical_name="王总", entity_type="person", aliases=["王先生"]
        )
        await session.commit()

    # Verify entity is now in DEFAULT_RETRIEVAL_PLANNER
    assert "王总" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set

    # Check that the planner activates relation_lane for a query containing the entity name
    ctx = RetrievalContext(
        subject_id="user:eric",
        session_id="s1",
        agent_type="memory_search_tool",
        user_message="王总来找我",
        access_purpose="tool_search",
    )
    plan = DEFAULT_RETRIEVAL_PLANNER.plan(ctx)
    assert plan.relation_lane is True, (
        "DEFAULT_RETRIEVAL_PLANNER should activate relation_lane for entity name '王总'"
    )

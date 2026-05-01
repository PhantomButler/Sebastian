from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.memory.consolidation.consolidation import (
    ConsolidationResult,
    ConsolidatorInput,
    MemoryConsolidator,
)


def test_consolidation_result_has_proposed_slots() -> None:
    result = ConsolidationResult()
    assert result.proposed_slots == []


@pytest.mark.asyncio
async def test_consolidate_parses_proposed_slots() -> None:
    raw = """{
      "summaries": [],
      "proposed_artifacts": [],
      "proposed_actions": [],
      "proposed_slots": [{
        "slot_id": "user.profile.hobby",
        "scope": "user",
        "subject_kind": "user",
        "cardinality": "multi",
        "resolution_policy": "append_only",
        "kind_constraints": ["preference"],
        "description": "爱好"
      }]
    }"""
    from sebastian.core.stream_events import TextDelta

    async def fake_stream(**kwargs):
        yield TextDelta(block_id="b0", delta=raw)

    provider = MagicMock()
    provider.stream = fake_stream

    registry = MagicMock()
    registry.get_provider = AsyncMock(return_value=MagicMock(provider=provider, model="fake"))

    consolidator = MemoryConsolidator(registry)
    result = await consolidator.consolidate(
        ConsolidatorInput(
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
    )
    assert len(result.proposed_slots) == 1
    assert result.proposed_slots[0].slot_id == "user.profile.hobby"


@pytest.mark.asyncio
async def test_consolidate_uses_build_consolidator_prompt() -> None:
    """确认 system prompt 包含 build_consolidator_prompt 的关键片段。"""
    captured_kwargs: dict = {}

    async def capturing_stream(**kwargs):
        captured_kwargs.update(kwargs)
        from sebastian.core.stream_events import TextDelta

        payload = (
            '{"summaries": [], "proposed_artifacts": [], '
            '"proposed_actions": [], "proposed_slots": []}'
        )
        yield TextDelta(block_id="b0", delta=payload)

    provider = MagicMock()
    provider.stream = capturing_stream

    registry = MagicMock()
    registry.get_provider = AsyncMock(return_value=MagicMock(provider=provider, model="fake"))

    consolidator = MemoryConsolidator(registry)
    await consolidator.consolidate(
        ConsolidatorInput(
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
    )
    system = captured_kwargs.get("system", "")
    assert "Consolidator 额外任务" in system
    assert "proposed_slots" in system
    assert "CandidateArtifact 字段" in system


@pytest.mark.asyncio
async def test_consolidate_failure_returns_empty_proposed_slots() -> None:
    """LLM 失败时返回 ConsolidationResult() 空结构，proposed_slots 为 []。"""

    async def bad_stream(**kwargs):
        from sebastian.core.stream_events import TextDelta

        yield TextDelta(block_id="b0", delta="not valid json {{{")

    provider = MagicMock()
    provider.stream = bad_stream

    registry = MagicMock()
    registry.get_provider = AsyncMock(return_value=MagicMock(provider=provider, model="fake"))

    consolidator = MemoryConsolidator(registry, max_retries=0)
    result = await consolidator.consolidate(
        ConsolidatorInput(
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
    )
    assert result.proposed_slots == []

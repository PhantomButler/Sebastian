from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.memory.extraction import (
    ExtractorInput,
    ExtractorOutput,
    MemoryExtractor,
)


def test_extractor_output_has_proposed_slots() -> None:
    out = ExtractorOutput(artifacts=[], proposed_slots=[])
    assert out.proposed_slots == []


def test_extractor_output_parses_full_example() -> None:
    raw = """\
    {
      "artifacts": [],
      "proposed_slots": [
        {
          "slot_id": "user.profile.location",
          "scope": "user",
          "subject_kind": "user",
          "cardinality": "single",
          "resolution_policy": "supersede",
          "kind_constraints": ["fact"],
          "description": "用户居住地"
        }
      ]
    }"""
    out = ExtractorOutput.model_validate_json(raw)
    assert len(out.proposed_slots) == 1
    assert out.proposed_slots[0].slot_id == "user.profile.location"


@pytest.mark.asyncio
async def test_extract_returns_extractor_output() -> None:
    mock_provider = MagicMock()

    async def fake_stream(**kwargs):
        from sebastian.core.stream_events import TextDelta

        yield TextDelta(delta='{"artifacts": [], "proposed_slots": []}')

    mock_provider.stream = fake_stream

    mock_registry = MagicMock()
    resolved = MagicMock(provider=mock_provider, model="fake-model")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry)
    result = await extractor.extract(
        ExtractorInput(
            subject_context={"subject_id": "u1", "agent_type": "default"},
            conversation_window=[{"role": "user", "content": "hi"}],
            known_slots=[],
        )
    )
    assert isinstance(result, ExtractorOutput)
    assert result.artifacts == []
    assert result.proposed_slots == []


@pytest.mark.asyncio
async def test_extract_failure_returns_empty_extractor_output() -> None:
    """extract() 失败时返回 ExtractorOutput(artifacts=[], proposed_slots=[])，不抛异常。"""
    mock_provider = MagicMock()

    async def bad_stream(**kwargs):
        from sebastian.core.stream_events import TextDelta

        yield TextDelta(delta="not valid json {{{{")

    mock_provider.stream = bad_stream

    mock_registry = MagicMock()
    resolved = MagicMock(provider=mock_provider, model="fake-model")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry, max_retries=0)
    result = await extractor.extract(
        ExtractorInput(
            subject_context={},
            conversation_window=[],
            known_slots=[],
        )
    )
    assert isinstance(result, ExtractorOutput)
    assert result.artifacts == []
    assert result.proposed_slots == []

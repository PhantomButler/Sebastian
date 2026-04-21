from __future__ import annotations

from collections import deque
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


# ---------------------------------------------------------------------------
# Task 10: extract_with_slot_retry() 测试
# ---------------------------------------------------------------------------


class _SeqProvider:
    """按顺序返回预设 payload 的假 provider。"""

    def __init__(self, payloads: list[str]) -> None:
        self._payloads: deque[str] = deque(payloads)
        self.call_count = 0
        self.last_messages: list[dict] | None = None

    async def stream(self, *, system, messages, tools, model, max_tokens):
        from sebastian.core.stream_events import TextDelta

        self.call_count += 1
        self.last_messages = messages
        payload = self._payloads.popleft()
        yield TextDelta(block_id="b0", delta=payload)


@pytest.mark.asyncio
async def test_slot_retry_succeeds_second_attempt() -> None:
    """第一次 LLM 返回被拒 slot，回调返回被拒 id → 重试一次，第二次 slot 合规 → 最终返回好结果。"""
    bad = (
        '{"artifacts": [], "proposed_slots": [{"slot_id": "BAD", '
        '"scope": "user", "subject_kind": "user", "cardinality": "single", '
        '"resolution_policy": "supersede", "kind_constraints": ["fact"], "description": "x"}]}'
    )
    good = (
        '{"artifacts": [], "proposed_slots": [{"slot_id": "user.profile.hobby", '
        '"scope": "user", "subject_kind": "user", "cardinality": "multi", '
        '"resolution_policy": "append_only", "kind_constraints": ["preference"], '
        '"description": "爱好"}]}'
    )
    provider = _SeqProvider([bad, good])

    mock_registry = MagicMock()
    resolved = MagicMock(provider=provider, model="fake")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry, max_retries=0)

    async def attempt_register(output: ExtractorOutput) -> list[tuple[str, str]]:
        # 把 slot_id == "BAD" 的视为被拒
        reason = "命名不符合三段式规范"
        return [(p.slot_id, reason) for p in output.proposed_slots if p.slot_id == "BAD"]

    result = await extractor.extract_with_slot_retry(
        ExtractorInput(
            subject_context={},
            conversation_window=[],
            known_slots=[],
        ),
        attempt_register=attempt_register,
    )
    assert provider.call_count == 2
    assert len(result.proposed_slots) == 1
    assert result.proposed_slots[0].slot_id == "user.profile.hobby"


@pytest.mark.asyncio
async def test_slot_retry_gives_up_after_one_retry() -> None:
    """两次都有被拒 slot → 第二次结束后不再重试，直接返回最后输出。"""
    bad = (
        '{"artifacts": [], "proposed_slots": [{"slot_id": "BAD", '
        '"scope": "user", "subject_kind": "user", "cardinality": "single", '
        '"resolution_policy": "supersede", "kind_constraints": ["fact"], "description": "x"}]}'
    )
    provider = _SeqProvider([bad, bad])

    mock_registry = MagicMock()
    resolved = MagicMock(provider=provider, model="fake")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry, max_retries=0)

    async def attempt_register(output: ExtractorOutput) -> list[tuple[str, str]]:
        reason = "命名不符合三段式规范"
        return [(p.slot_id, reason) for p in output.proposed_slots if p.slot_id == "BAD"]

    result = await extractor.extract_with_slot_retry(
        ExtractorInput(
            subject_context={},
            conversation_window=[],
            known_slots=[],
        ),
        attempt_register=attempt_register,
    )
    # 只重试一次（共 2 次调用），不无限循环
    assert provider.call_count == 2
    # 返回最后一次输出（仍含被拒 slot，由外层决定如何处理）
    assert isinstance(result, ExtractorOutput)
    assert len(result.proposed_slots) > 0


@pytest.mark.asyncio
async def test_slot_retry_no_rejected_slots_calls_llm_once() -> None:
    """第一次就没有被拒 slot → 不重试，只调用 1 次 LLM。"""
    good = '{"artifacts": [], "proposed_slots": []}'
    provider = _SeqProvider([good])

    mock_registry = MagicMock()
    resolved = MagicMock(provider=provider, model="fake")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry, max_retries=0)

    async def attempt_register(output: ExtractorOutput) -> list[tuple[str, str]]:
        return []  # 无被拒

    result = await extractor.extract_with_slot_retry(
        ExtractorInput(subject_context={}, conversation_window=[], known_slots=[]),
        attempt_register=attempt_register,
    )
    assert provider.call_count == 1
    assert result.proposed_slots == []

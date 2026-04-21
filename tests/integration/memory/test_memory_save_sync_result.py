from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from sebastian.capabilities.tools.memory_save import memory_save
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryKind,
    MemoryScope,
    MemorySource,
)


def _preference_candidate() -> CandidateArtifact:
    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="我喜欢咖啡",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


@pytest.mark.asyncio
async def test_success_returns_structured_result(tmp_memory_env) -> None:
    """成功路径：返回 ok=True，output 含 saved_count >= 1 且 summary 含 '已记住'。"""
    from sebastian.memory.extraction import ExtractorOutput

    fake_output = ExtractorOutput(
        artifacts=[_preference_candidate()],
        proposed_slots=[],
    )

    with patch(
        "sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
        new_callable=AsyncMock,
        return_value=fake_output,
    ):
        result = await memory_save(content="帮我记住我喜欢咖啡")

    assert result.ok is True
    assert result.output["saved_count"] >= 1
    assert "summary" in result.output
    assert "已记住" in result.output["summary"]


@pytest.mark.asyncio
async def test_timeout_returns_ok_false(tmp_memory_env) -> None:
    """超时路径：返回 ok=False，error 含 '超时'。"""

    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(20)

    with patch(
        "sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
        side_effect=slow_extract,
    ):
        with patch("sebastian.capabilities.tools.memory_save.MEMORY_SAVE_TIMEOUT_SECONDS", 0.1):
            result = await memory_save(content="x")

    assert result.ok is False
    assert "超时" in (result.error or "")


@pytest.mark.asyncio
async def test_extractor_empty_returns_empty_summary(tmp_memory_env) -> None:
    """extractor 返回空时：ok=True，saved_count == 0，summary 含 '暂无可保存'。"""
    from sebastian.memory.extraction import ExtractorOutput

    fake_output = ExtractorOutput(artifacts=[], proposed_slots=[])

    with patch(
        "sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
        new_callable=AsyncMock,
        return_value=fake_output,
    ):
        result = await memory_save(content="今天天气怎么样？")

    assert result.ok is True
    assert result.output["saved_count"] == 0
    assert "暂无可保存" in result.output["summary"]

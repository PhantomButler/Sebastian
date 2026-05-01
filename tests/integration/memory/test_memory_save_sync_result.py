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
    from sebastian.memory.consolidation.extraction import ExtractorOutput

    fake_output = ExtractorOutput(
        artifacts=[_preference_candidate()],
        proposed_slots=[],
    )

    with patch(
        "sebastian.memory.consolidation.extraction.MemoryExtractor.extract_with_slot_retry",
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
    """超时路径：返回 ok=False，error 给出“稍后再试”类可重试提示。

    历史：memory_save 早期会把技术词“超时”直接抛给 agent，430500c 统一为
    不暴露内部细节的用户可见文案，但保留与其它异常的语义区分——timeout 的
    文案包含“稍后再试”，generic exception 的文案指向“排查后台日志”。本测试
    断言这条可观测语义，不再绑死在“超时”这个技术词上。
    """

    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(20)

    with patch(
        "sebastian.memory.consolidation.extraction.MemoryExtractor.extract_with_slot_retry",
        side_effect=slow_extract,
    ):
        with patch("sebastian.capabilities.tools.memory_save.MEMORY_SAVE_TIMEOUT_SECONDS", 0.1):
            result = await memory_save(content="x")

    assert result.ok is False
    assert "稍后再试" in (result.error or "")


@pytest.mark.asyncio
async def test_extractor_empty_returns_empty_summary(tmp_memory_env) -> None:
    """extractor 返回空时：ok=True，saved_count == 0，summary 含 '暂无可保存'。"""
    from sebastian.memory.consolidation.extraction import ExtractorOutput

    fake_output = ExtractorOutput(artifacts=[], proposed_slots=[])

    with patch(
        "sebastian.memory.consolidation.extraction.MemoryExtractor.extract_with_slot_retry",
        new_callable=AsyncMock,
        return_value=fake_output,
    ):
        result = await memory_save(content="今天天气怎么样？")

    assert result.ok is True
    assert result.output["saved_count"] == 0
    assert "暂无可保存" in result.output["summary"]

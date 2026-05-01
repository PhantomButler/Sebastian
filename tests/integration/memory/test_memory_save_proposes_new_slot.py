from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sebastian.capabilities.tools.memory_save import memory_save
from sebastian.memory.extraction import ExtractorOutput
from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ProposedSlot,
    ResolutionPolicy,
)

_NEW_SLOT_ID = "user.profile.favorite_food"


def _make_proposed_slot() -> ProposedSlot:
    return ProposedSlot(
        slot_id=_NEW_SLOT_ID,
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="喜欢的食物",
    )


def _make_artifact(content: str) -> CandidateArtifact:
    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content=content,
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=_NEW_SLOT_ID,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.EXPLICIT,
        evidence=[{"quote": content}],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


@pytest.mark.asyncio
async def test_memory_save_proposes_slot_and_reuses_on_second_call(
    tmp_memory_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第一次调用：Extractor 提议新 slot → slot 注册到 DB + 内存 registry → artifact 落库
    第二次调用：known_slots 已含该 slot → 仅落 artifact，不再提议"""

    # --- 确保 DEFAULT_SLOT_REGISTRY 不带测试 slot 开始 ---
    assert DEFAULT_SLOT_REGISTRY.get(_NEW_SLOT_ID) is None, (
        f"slot {_NEW_SLOT_ID!r} should not exist in registry before test"
    )

    # 测试结束后清理 DEFAULT_SLOT_REGISTRY，避免污染其他测试
    original_slots = dict(DEFAULT_SLOT_REGISTRY._slots)
    monkeypatch.setattr(DEFAULT_SLOT_REGISTRY, "_slots", original_slots, raising=True)

    factory = tmp_memory_env

    # === 第一次调用：Extractor 提议新 slot ===
    first_output = ExtractorOutput(
        artifacts=[_make_artifact("喜欢火锅")],
        proposed_slots=[_make_proposed_slot()],
    )

    with patch(
        "sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
        new_callable=AsyncMock,
        return_value=first_output,
    ):
        r1 = await memory_save(content="我喜欢吃火锅")

    assert r1.ok is True, f"memory_save failed: {r1.error}"
    assert _NEW_SLOT_ID in r1.output["proposed_slots_registered"], (
        f"expected {_NEW_SLOT_ID!r} in proposed_slots_registered, got: {r1.output}"
    )

    # 断言内存 registry 已注册
    assert DEFAULT_SLOT_REGISTRY.get(_NEW_SLOT_ID) is not None, (
        "slot should be in DEFAULT_SLOT_REGISTRY after first call"
    )

    # 断言 DB 里有该行
    from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore

    async with factory() as verify_session:
        store = SlotDefinitionStore(verify_session)
        db_record = await store.get(_NEW_SLOT_ID)
    assert db_record is not None, f"slot {_NEW_SLOT_ID!r} should be persisted in memory_slots table"
    assert db_record.is_builtin is False
    assert db_record.proposed_by == "extractor"

    # === 第二次调用：slot 已在 registry，不应再提议 ===
    second_output = ExtractorOutput(
        artifacts=[_make_artifact("也喜欢烤肉")],
        proposed_slots=[],
    )

    with patch(
        "sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
        new_callable=AsyncMock,
        return_value=second_output,
    ):
        r2 = await memory_save(content="也喜欢烤肉")

    assert r2.ok is True, f"second memory_save failed: {r2.error}"
    assert r2.output["proposed_slots_registered"] == [], (
        f"second call should register no new slots, got: {r2.output['proposed_slots_registered']}"
    )
    assert r2.output["saved_count"] >= 1, (
        f"second call should save artifact, got saved_count={r2.output['saved_count']}"
    )

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.memory.consolidation import (
    ConsolidationResult,
    MemoryConsolidator,
    MemorySummary,
    SessionConsolidationWorker,
)
from sebastian.memory.extraction import ExtractorOutput, MemoryExtractor
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ProposedSlot,
    ResolutionPolicy,
)


def _make_proposed_slot(slot_id: str) -> ProposedSlot:
    return ProposedSlot(
        slot_id=slot_id,
        scope=MemoryScope.USER,
        subject_kind="owner",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description=f"test slot {slot_id}",
    )


def _make_candidate(slot_id: str | None = None) -> CandidateArtifact:
    return CandidateArtifact(
        kind=MemoryKind.FACT,
        content="test fact",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id=slot_id,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.INFERRED,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


@pytest.mark.asyncio
async def test_worker_merges_extractor_and_consolidator_proposed_slots(
    tmp_memory_env,
) -> None:
    """Worker 应把 Extractor + Consolidator 的 proposed_slots 合并后传给 process_candidates。

    断言：process_candidates 被调用时 proposed_slots 参数包含两处提议（共 2 个 slot）。
    """
    factory = tmp_memory_env

    extractor_slot = _make_proposed_slot("user.hobby.gaming")
    consolidator_slot = _make_proposed_slot("user.health.sleep_hours")

    fake_extractor_output = ExtractorOutput(
        artifacts=[_make_candidate()],
        proposed_slots=[extractor_slot],
    )
    fake_consolidation_result = ConsolidationResult(
        summaries=[
            MemorySummary(content="test summary", subject_id="owner", session_id="test-session")
        ],
        proposed_artifacts=[],
        proposed_actions=[],
        proposed_slots=[consolidator_slot],
    )

    mock_extractor = MagicMock(spec=MemoryExtractor)
    mock_extractor.extract_with_slot_retry = AsyncMock(return_value=fake_extractor_output)

    mock_consolidator = MagicMock(spec=MemoryConsolidator)
    mock_consolidator.consolidate = AsyncMock(return_value=fake_consolidation_result)
    mock_consolidator.last_resolved = None

    mock_session_store = MagicMock()
    mock_session_store.get_messages = AsyncMock(return_value=[{"role": "user", "content": "hi"}])

    worker = SessionConsolidationWorker(
        db_factory=factory,
        consolidator=mock_consolidator,
        extractor=mock_extractor,
        session_store=mock_session_store,
        memory_settings_fn=lambda: True,
    )

    captured_proposed_slots: list[ProposedSlot] = []

    async def capturing_process_candidates(
        candidates,
        proposed_slots=None,
        **kwargs,
    ):
        nonlocal captured_proposed_slots
        captured_proposed_slots = list(proposed_slots or [])
        # 返回最小 PipelineResult，避免后续代码崩溃
        from sebastian.memory.pipeline import PipelineResult

        return PipelineResult()

    with patch(
        "sebastian.memory.pipeline.process_candidates",
        side_effect=capturing_process_candidates,
    ):
        await worker.consolidate_session("test-session", "default")

    slot_ids = {s.slot_id for s in captured_proposed_slots}
    assert "user.hobby.gaming" in slot_ids, f"extractor proposed slot missing; got: {slot_ids}"
    assert "user.health.sleep_hours" in slot_ids, (
        f"consolidator proposed slot missing; got: {slot_ids}"
    )
    assert len(captured_proposed_slots) == 2


@pytest.mark.asyncio
async def test_worker_passes_slot_proposal_handler_to_process_candidates(
    tmp_memory_env,
) -> None:
    """Worker 应向 process_candidates 传入非 None 的 slot_proposal_handler。"""
    factory = tmp_memory_env

    fake_extractor_output = ExtractorOutput(artifacts=[], proposed_slots=[])
    fake_consolidation_result = ConsolidationResult()

    mock_extractor = MagicMock(spec=MemoryExtractor)
    mock_extractor.extract_with_slot_retry = AsyncMock(return_value=fake_extractor_output)

    mock_consolidator = MagicMock(spec=MemoryConsolidator)
    mock_consolidator.consolidate = AsyncMock(return_value=fake_consolidation_result)
    mock_consolidator.last_resolved = None

    mock_session_store = MagicMock()
    mock_session_store.get_messages = AsyncMock(return_value=[])

    worker = SessionConsolidationWorker(
        db_factory=factory,
        consolidator=mock_consolidator,
        extractor=mock_extractor,
        session_store=mock_session_store,
        memory_settings_fn=lambda: True,
    )

    captured_kwargs: dict = {}

    async def capturing_process_candidates(candidates, proposed_slots=None, **kwargs):
        captured_kwargs.update(kwargs)
        from sebastian.memory.pipeline import PipelineResult

        return PipelineResult()

    with patch(
        "sebastian.memory.pipeline.process_candidates",
        side_effect=capturing_process_candidates,
    ):
        await worker.consolidate_session("test-session-2", "default")

    from sebastian.memory.slot_proposals import SlotProposalHandler

    assert "slot_proposal_handler" in captured_kwargs
    assert isinstance(captured_kwargs["slot_proposal_handler"], SlotProposalHandler), (
        f"expected SlotProposalHandler, got {type(captured_kwargs['slot_proposal_handler'])}"
    )


@pytest.mark.asyncio
async def test_worker_proposed_by_is_consolidator(
    tmp_memory_env,
) -> None:
    """Worker 向 process_candidates 传 proposed_by='consolidator'。"""
    factory = tmp_memory_env

    fake_extractor_output = ExtractorOutput(artifacts=[], proposed_slots=[])
    fake_consolidation_result = ConsolidationResult()

    mock_extractor = MagicMock(spec=MemoryExtractor)
    mock_extractor.extract_with_slot_retry = AsyncMock(return_value=fake_extractor_output)

    mock_consolidator = MagicMock(spec=MemoryConsolidator)
    mock_consolidator.consolidate = AsyncMock(return_value=fake_consolidation_result)
    mock_consolidator.last_resolved = None

    mock_session_store = MagicMock()
    mock_session_store.get_messages = AsyncMock(return_value=[])

    worker = SessionConsolidationWorker(
        db_factory=factory,
        consolidator=mock_consolidator,
        extractor=mock_extractor,
        session_store=mock_session_store,
        memory_settings_fn=lambda: True,
    )

    captured_kwargs: dict = {}

    async def capturing_process_candidates(candidates, proposed_slots=None, **kwargs):
        captured_kwargs.update(kwargs)
        from sebastian.memory.pipeline import PipelineResult

        return PipelineResult()

    with patch(
        "sebastian.memory.pipeline.process_candidates",
        side_effect=capturing_process_candidates,
    ):
        await worker.consolidate_session("test-session-3", "default")

    assert captured_kwargs.get("proposed_by") == "consolidator"

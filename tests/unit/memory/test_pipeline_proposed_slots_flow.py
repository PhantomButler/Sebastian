from __future__ import annotations

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store import models  # noqa: F401 – registers ORM models
from sebastian.store.database import Base


async def _make_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_proposed_slot(slot_id: str = "user.profile.hobby"):
    from sebastian.memory.types import (
        Cardinality,
        MemoryKind,
        MemoryScope,
        ProposedSlot,
        ResolutionPolicy,
    )

    return ProposedSlot(
        slot_id=slot_id,
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="爱好",
    )


def _make_candidate(slot_id: str):
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )

    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="喜欢音乐",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id=slot_id,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.EXPLICIT,
        evidence=[{"quote": "x"}],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


async def _run_with_proposed(
    candidates,
    proposed_slots,
    *,
    session_id: str = "s1",
    registry=None,
    factory=None,
):
    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slot_definition_store import SlotDefinitionStore
    from sebastian.memory.slot_proposals import SlotProposalHandler
    from sebastian.memory.slots import SlotRegistry

    if factory is None:
        factory = await _make_db_factory()

    if registry is None:
        registry = SlotRegistry(slots=[])

    async with factory() as db_session:
        store = SlotDefinitionStore(db_session)
        handler = SlotProposalHandler(store=store, registry=registry)

        result = await process_candidates(
            candidates,
            proposed_slots=proposed_slots,
            session_id=session_id,
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=registry,
            slot_proposal_handler=handler,
            worker_id="test",
            model_name=None,
            rule_version="test_v1",
            input_source={"type": "test", "session_id": session_id},
            proposed_by="extractor",
        )
        await db_session.commit()

    return result, factory, registry


@pytest.mark.asyncio
async def test_proposed_slot_registered_before_candidate() -> None:
    """proposed_slot 先注册成功，随后 candidate 可通过 slot 验证被保存。"""

    proposed = _make_proposed_slot("user.profile.hobby")
    candidate = _make_candidate("user.profile.hobby")

    result, _, registry = await _run_with_proposed([candidate], [proposed])

    assert "user.profile.hobby" in result.proposed_slots_registered
    assert result.proposed_slots_rejected == []
    # slot 已注册进内存 registry
    assert registry.get("user.profile.hobby") is not None
    # candidate 通过了 slot 验证，不是 DISCARD
    assert result.saved_count >= 1


@pytest.mark.asyncio
async def test_invalid_slot_triggers_candidate_downgrade() -> None:
    """命名违规的 proposed slot → 进 rejected；对应 candidate slot_id 降级为 None → DISCARD。"""
    from sebastian.memory.types import (
        Cardinality,
        MemoryKind,
        MemoryScope,
        ProposedSlot,
        ResolutionPolicy,
    )

    # BAD.ID 违反命名规则（首字母大写）
    bad_slot = ProposedSlot(
        slot_id="user.profile.BADHOBBY",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="invalid",
    )
    candidate = _make_candidate("user.profile.BADHOBBY")

    result, _, _ = await _run_with_proposed([candidate], [bad_slot])

    assert len(result.proposed_slots_rejected) == 1
    assert result.proposed_slots_rejected[0]["slot_id"] == "user.profile.BADHOBBY"
    # candidate slot_id 降级 → 无法通过 validate → DISCARD
    assert result.saved_count == 0


@pytest.mark.asyncio
async def test_no_proposed_slots_backward_compatible() -> None:
    """空 proposed_slots 时，行为与原有 process_candidates 一致（内置 slot 可用）。"""
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )

    candidate = CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="简洁回答",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )

    result, _, _ = await _run_with_proposed([candidate], [], registry=DEFAULT_SLOT_REGISTRY)

    assert result.proposed_slots_registered == []
    assert result.proposed_slots_rejected == []
    assert result.saved_count >= 1


@pytest.mark.asyncio
async def test_pipeline_result_has_new_fields() -> None:
    """PipelineResult 包含 proposed_slots_registered / proposed_slots_rejected /
    saved_count / discarded_count。"""
    result, _, _ = await _run_with_proposed([], [])

    assert hasattr(result, "proposed_slots_registered")
    assert hasattr(result, "proposed_slots_rejected")
    assert hasattr(result, "saved_count")
    assert hasattr(result, "discarded_count")

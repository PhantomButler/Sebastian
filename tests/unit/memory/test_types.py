from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    ResolutionPolicy,
    ResolveDecision,
    SlotDefinition,
)

# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------


def test_memory_kind_values() -> None:
    assert MemoryKind.FACT == "fact"
    assert MemoryKind.PREFERENCE == "preference"
    assert MemoryKind.EPISODE == "episode"
    assert MemoryKind.SUMMARY == "summary"
    assert MemoryKind.ENTITY == "entity"
    assert MemoryKind.RELATION == "relation"


def test_memory_scope_values() -> None:
    assert MemoryScope.USER == "user"
    assert MemoryScope.SESSION == "session"
    assert MemoryScope.PROJECT == "project"
    assert MemoryScope.AGENT == "agent"


def test_memory_source_values() -> None:
    assert MemorySource.EXPLICIT == "explicit"
    assert MemorySource.INFERRED == "inferred"
    assert MemorySource.OBSERVED == "observed"
    assert MemorySource.IMPORTED == "imported"
    assert MemorySource.SYSTEM_DERIVED == "system_derived"


def test_memory_status_values() -> None:
    assert MemoryStatus.ACTIVE == "active"
    assert MemoryStatus.SUPERSEDED == "superseded"
    assert MemoryStatus.EXPIRED == "expired"
    assert MemoryStatus.DELETED == "deleted"


def test_memory_decision_type_values() -> None:
    assert MemoryDecisionType.ADD == "ADD"
    assert MemoryDecisionType.SUPERSEDE == "SUPERSEDE"
    assert MemoryDecisionType.MERGE == "MERGE"
    assert MemoryDecisionType.EXPIRE == "EXPIRE"
    assert MemoryDecisionType.DISCARD == "DISCARD"


def test_cardinality_values() -> None:
    assert Cardinality.SINGLE == "single"
    assert Cardinality.MULTI == "multi"


def test_resolution_policy_values() -> None:
    assert ResolutionPolicy.SUPERSEDE == "supersede"
    assert ResolutionPolicy.MERGE == "merge"
    assert ResolutionPolicy.APPEND_ONLY == "append_only"
    assert ResolutionPolicy.TIME_BOUND == "time_bound"


# ---------------------------------------------------------------------------
# CandidateArtifact
# ---------------------------------------------------------------------------


def test_candidate_artifact_accepts_required_fields() -> None:
    artifact = CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="用户偏好简洁中文回复",
        structured_payload={"language": "zh-CN", "style": "concise"},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality="single",
        resolution_policy="supersede",
        confidence=0.96,
        source=MemorySource.EXPLICIT,
        evidence=[{"type": "message_span", "message_id": "msg_1", "text": "以后简洁中文"}],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    assert artifact.kind is MemoryKind.PREFERENCE
    assert artifact.confidence == 0.96


def test_candidate_artifact_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        CandidateArtifact(
            kind=MemoryKind.FACT,
            content="bad",
            structured_payload={},
            subject_hint=None,
            scope=MemoryScope.USER,
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=1.5,
            source=MemorySource.INFERRED,
            evidence=[],
            valid_from=None,
            valid_until=None,
            policy_tags=[],
            needs_review=True,
        )


def test_candidate_artifact_confidence_boundary_zero() -> None:
    artifact = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="some fact",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.0,
        source=MemorySource.INFERRED,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    assert artifact.confidence == 0.0


def test_candidate_artifact_confidence_boundary_one() -> None:
    artifact = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="certain fact",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=1.0,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    assert artifact.confidence == 1.0


def test_candidate_artifact_rejects_negative_confidence() -> None:
    with pytest.raises(ValidationError):
        CandidateArtifact(
            kind=MemoryKind.FACT,
            content="bad",
            structured_payload={},
            subject_hint=None,
            scope=MemoryScope.USER,
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=-0.1,
            source=MemorySource.INFERRED,
            evidence=[],
            valid_from=None,
            valid_until=None,
            policy_tags=[],
            needs_review=True,
        )


def test_candidate_artifact_with_valid_from_until() -> None:
    now = datetime.now(UTC)
    artifact = CandidateArtifact(
        kind=MemoryKind.EPISODE,
        content="meeting with Alice",
        structured_payload={"participant": "Alice"},
        subject_hint="owner",
        scope=MemoryScope.SESSION,
        slot_id=None,
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        confidence=0.85,
        source=MemorySource.OBSERVED,
        evidence=[],
        valid_from=now,
        valid_until=None,
        policy_tags=["work"],
        needs_review=False,
    )
    assert artifact.valid_from == now
    assert artifact.policy_tags == ["work"]


def test_candidate_artifact_rejects_invalid_scope() -> None:
    with pytest.raises(ValidationError):
        CandidateArtifact(
            kind=MemoryKind.FACT,
            content="some fact",
            structured_payload={},
            subject_hint=None,
            scope="totally_invalid",
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=0.5,
            source=MemorySource.INFERRED,
            evidence=[],
            valid_from=None,
            valid_until=None,
            policy_tags=[],
            needs_review=False,
        )


# ---------------------------------------------------------------------------
# SlotDefinition
# ---------------------------------------------------------------------------


def test_slot_definition_construction() -> None:
    slot = SlotDefinition(
        slot_id="user.preference.language",
        scope=MemoryScope.USER,
        subject_kind="owner",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="User preferred language for replies",
    )
    assert slot.slot_id == "user.preference.language"
    assert slot.cardinality is Cardinality.SINGLE
    assert MemoryKind.PREFERENCE in slot.kind_constraints


def test_slot_definition_multi_kind_constraints() -> None:
    slot = SlotDefinition(
        slot_id="user.general.facts",
        scope=MemoryScope.USER,
        subject_kind="owner",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        kind_constraints=[MemoryKind.FACT, MemoryKind.ENTITY],
        description="General facts about the user",
    )
    assert len(slot.kind_constraints) == 2


# ---------------------------------------------------------------------------
# MemoryArtifact
# ---------------------------------------------------------------------------


def _make_memory_artifact(**overrides: object) -> MemoryArtifact:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": "mem_abc123",
        "kind": MemoryKind.FACT,
        "scope": MemoryScope.USER,
        "subject_id": "owner",
        "slot_id": None,
        "cardinality": None,
        "resolution_policy": None,
        "content": "Eric likes coffee",
        "structured_payload": {"beverage": "coffee"},
        "source": MemorySource.EXPLICIT,
        "confidence": 0.9,
        "status": MemoryStatus.ACTIVE,
        "valid_from": None,
        "valid_until": None,
        "recorded_at": now,
        "last_accessed_at": None,
        "access_count": 0,
        "provenance": {"session_id": "sess_1"},
        "links": [],
        "embedding_ref": None,
        "dedupe_key": None,
        "policy_tags": [],
    }
    defaults.update(overrides)
    return MemoryArtifact(**defaults)  # type: ignore[arg-type]


def test_memory_artifact_construction() -> None:
    artifact = _make_memory_artifact()
    assert artifact.id == "mem_abc123"
    assert artifact.status is MemoryStatus.ACTIVE
    assert artifact.access_count == 0


def test_memory_artifact_with_all_optional_fields() -> None:
    now = datetime.now(UTC)
    artifact = _make_memory_artifact(
        slot_id="user.preference.beverage",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        valid_from=now,
        valid_until=now,
        last_accessed_at=now,
        access_count=5,
        links=["mem_xyz"],
        embedding_ref="emb_001",
        dedupe_key="dk_coffee",
        policy_tags=["personal"],
    )
    assert artifact.embedding_ref == "emb_001"
    assert artifact.dedupe_key == "dk_coffee"
    assert artifact.access_count == 5


def test_memory_artifact_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        _make_memory_artifact(confidence=2.0)


def test_memory_artifact_confidence_boundaries() -> None:
    a_zero = _make_memory_artifact(confidence=0.0)
    a_one = _make_memory_artifact(confidence=1.0)
    assert a_zero.confidence == 0.0
    assert a_one.confidence == 1.0


# ---------------------------------------------------------------------------
# ResolveDecision
# ---------------------------------------------------------------------------


def _make_candidate() -> CandidateArtifact:
    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="prefers dark mode",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.ui_theme",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        confidence=0.88,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def test_resolve_decision_add() -> None:
    new_mem = _make_memory_artifact()
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="No existing memory for this slot",
        old_memory_ids=[],
        new_memory=new_mem,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.ui_theme",
    )
    assert decision.decision is MemoryDecisionType.ADD
    assert decision.new_memory is not None


def test_resolve_decision_discard_no_new_memory() -> None:
    decision = ResolveDecision(
        decision=MemoryDecisionType.DISCARD,
        reason="Confidence too low",
        old_memory_ids=["mem_old"],
        new_memory=None,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id=None,
    )
    assert decision.decision is MemoryDecisionType.DISCARD
    assert decision.new_memory is None


def test_resolve_decision_supersede() -> None:
    new_mem = _make_memory_artifact(status=MemoryStatus.ACTIVE)
    decision = ResolveDecision(
        decision=MemoryDecisionType.SUPERSEDE,
        reason="Newer explicit signal overrides old inferred value",
        old_memory_ids=["mem_old_1", "mem_old_2"],
        new_memory=new_mem,
        candidate=_make_candidate(),
        subject_id="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.ui_theme",
    )
    assert decision.decision is MemoryDecisionType.SUPERSEDE
    assert len(decision.old_memory_ids) == 2


def test_candidate_artifact_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CandidateArtifact(
            kind=MemoryKind.FACT,
            content="x",
            structured_payload={},
            subject_hint=None,
            scope=MemoryScope.USER,
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=0.5,
            source=MemorySource.EXPLICIT,
            evidence=[],
            valid_from=None,
            valid_until=None,
            policy_tags=[],
            needs_review=False,
            bogus_field="nope",  # type: ignore[call-arg]
        )


def test_resolve_decision_add_requires_new_memory() -> None:
    candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.5,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    with pytest.raises(ValidationError):
        ResolveDecision(
            decision=MemoryDecisionType.ADD,
            reason="r",
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id="owner",
            scope=MemoryScope.USER,
            slot_id=None,
        )


def test_resolve_decision_expire_requires_old_memory_ids() -> None:
    candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.5,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    with pytest.raises(ValidationError):
        ResolveDecision(
            decision=MemoryDecisionType.EXPIRE,
            reason="r",
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id="owner",
            scope=MemoryScope.USER,
            slot_id=None,
        )


def test_resolve_decision_supersede_requires_old_memory_ids() -> None:
    from uuid import uuid4

    candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.5,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    new_memory = MemoryArtifact(
        id=str(uuid4()),
        kind=MemoryKind.FACT,
        scope=MemoryScope.USER,
        subject_id="owner",
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        content="x",
        structured_payload={},
        source=MemorySource.EXPLICIT,
        confidence=0.5,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=datetime.now(UTC),
        last_accessed_at=None,
        access_count=0,
        provenance={},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )
    with pytest.raises(ValidationError):
        ResolveDecision(
            decision=MemoryDecisionType.SUPERSEDE,
            reason="r",
            old_memory_ids=[],
            new_memory=new_memory,
            candidate=candidate,
            subject_id="owner",
            scope=MemoryScope.USER,
            slot_id=None,
        )


def test_resolve_decision_discard_rejects_new_memory() -> None:
    from uuid import uuid4

    candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.5,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    new_memory = MemoryArtifact(
        id=str(uuid4()),
        kind=MemoryKind.FACT,
        scope=MemoryScope.USER,
        subject_id="owner",
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        content="x",
        structured_payload={},
        source=MemorySource.EXPLICIT,
        confidence=0.5,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=datetime.now(UTC),
        last_accessed_at=None,
        access_count=0,
        provenance={},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )
    with pytest.raises(ValidationError):
        ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason="r",
            old_memory_ids=[],
            new_memory=new_memory,
            candidate=candidate,
            subject_id="owner",
            scope=MemoryScope.USER,
            slot_id=None,
        )

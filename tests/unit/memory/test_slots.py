from __future__ import annotations

import pytest

from sebastian.memory.errors import InvalidCandidateError, UnknownSlotError
from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY, SlotRegistry
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ResolutionPolicy,
    SlotDefinition,
)


def _make_candidate(
    kind: MemoryKind,
    slot_id: str | None = None,
) -> CandidateArtifact:
    return CandidateArtifact(
        kind=kind,
        content="test content",
        structured_payload={},
        subject_hint=None,
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


class TestBuiltinSlots:
    def test_response_style_slot_exists(self) -> None:
        registry = SlotRegistry()
        slot = registry.get("user.preference.response_style")
        assert slot is not None
        assert slot.slot_id == "user.preference.response_style"

    def test_response_style_is_single_supersede(self) -> None:
        registry = SlotRegistry()
        slot = registry.require("user.preference.response_style")
        assert slot.cardinality == Cardinality.SINGLE
        assert slot.resolution_policy == ResolutionPolicy.SUPERSEDE

    def test_all_nine_builtin_slots_exist(self) -> None:
        registry = SlotRegistry()
        expected = [
            "user.preference.response_style",
            "user.preference.language",
            "user.current_project_focus",
            "user.profile.timezone",
            "project.current_phase",
            "agent.current_assignment",
            "user.profile.name",
            "user.profile.location",
            "user.profile.occupation",
        ]
        for slot_id in expected:
            assert registry.get(slot_id) is not None, f"Missing slot: {slot_id}"

    def test_builtin_addressing_slot_exists(self) -> None:
        registry = SlotRegistry()
        slot = registry.get("user.preference.addressing")
        assert slot is not None
        assert slot.scope == MemoryScope.USER
        assert slot.cardinality == Cardinality.SINGLE
        assert slot.resolution_policy == ResolutionPolicy.SUPERSEDE
        assert MemoryKind.PREFERENCE in slot.kind_constraints


class TestRegistryLookup:
    def test_get_unknown_returns_none(self) -> None:
        registry = SlotRegistry()
        assert registry.get("unknown.slot.id") is None

    def test_require_unknown_raises_unknown_slot_error(self) -> None:
        registry = SlotRegistry()
        with pytest.raises(UnknownSlotError, match="unknown.slot.id"):
            registry.require("unknown.slot.id")

    def test_custom_slots_only_when_explicit(self) -> None:
        custom_slot = SlotDefinition(
            slot_id="custom.test.slot",
            scope=MemoryScope.USER,
            subject_kind="user",
            cardinality=Cardinality.SINGLE,
            resolution_policy=ResolutionPolicy.SUPERSEDE,
            kind_constraints=[MemoryKind.FACT],
            description="custom test slot",
        )
        registry = SlotRegistry(slots=[custom_slot])
        assert registry.get("custom.test.slot") is not None
        # Built-ins should NOT be present when explicit slots are given
        assert registry.get("user.preference.response_style") is None


class TestListAll:
    def test_list_all_returns_all_registered_slots(self) -> None:
        registry = SlotRegistry()
        slots = registry.list_all()
        assert len(slots) == 10
        slot_ids = {s.slot_id for s in slots}
        assert slot_ids == {
            "user.preference.response_style",
            "user.preference.language",
            "user.preference.addressing",
            "user.current_project_focus",
            "user.profile.timezone",
            "project.current_phase",
            "agent.current_assignment",
            "user.profile.name",
            "user.profile.location",
            "user.profile.occupation",
        }

    def test_list_all_returns_slot_definitions(self) -> None:
        registry = SlotRegistry()
        slots = registry.list_all()
        assert all(isinstance(s, SlotDefinition) for s in slots)

    def test_list_all_on_custom_registry(self) -> None:
        custom = SlotDefinition(
            slot_id="custom.one",
            scope=MemoryScope.USER,
            subject_kind="user",
            cardinality=Cardinality.SINGLE,
            resolution_policy=ResolutionPolicy.SUPERSEDE,
            kind_constraints=[MemoryKind.FACT],
            description="custom",
        )
        registry = SlotRegistry(slots=[custom])
        slots = registry.list_all()
        assert len(slots) == 1
        assert slots[0].slot_id == "custom.one"


class TestValidateCandidate:
    def test_fact_without_slot_is_invalid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.FACT, slot_id=None)
        with pytest.raises(InvalidCandidateError):
            registry.validate_candidate(candidate)

    def test_preference_without_slot_is_invalid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.PREFERENCE, slot_id=None)
        with pytest.raises(InvalidCandidateError):
            registry.validate_candidate(candidate)

    def test_fact_with_unknown_slot_is_invalid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.FACT, slot_id="nonexistent.slot")
        with pytest.raises(InvalidCandidateError):
            registry.validate_candidate(candidate)

    def test_preference_with_unknown_slot_is_invalid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.PREFERENCE, slot_id="nonexistent.slot")
        with pytest.raises(InvalidCandidateError):
            registry.validate_candidate(candidate)

    def test_fact_with_valid_slot_is_valid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.FACT, slot_id="user.current_project_focus")
        registry.validate_candidate(candidate)  # must not raise

    def test_preference_with_valid_slot_is_valid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.PREFERENCE, slot_id="user.preference.language")
        registry.validate_candidate(candidate)  # must not raise

    def test_episode_without_slot_is_valid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.EPISODE, slot_id=None)
        registry.validate_candidate(candidate)  # must not raise

    def test_entity_without_slot_is_valid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.ENTITY, slot_id=None)
        registry.validate_candidate(candidate)  # must not raise

    def test_relation_without_slot_is_valid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.RELATION, slot_id=None)
        registry.validate_candidate(candidate)  # must not raise

    def test_summary_without_slot_is_valid(self) -> None:
        registry = SlotRegistry()
        candidate = _make_candidate(MemoryKind.SUMMARY, slot_id=None)
        registry.validate_candidate(candidate)  # must not raise

    def test_validate_candidate_rejects_mismatched_kind(self) -> None:
        """FACT candidate in a PREFERENCE-only slot should be invalid."""
        registry = DEFAULT_SLOT_REGISTRY
        candidate = _make_candidate(
            kind=MemoryKind.FACT,
            slot_id="user.preference.response_style",  # kind_constraints=[PREFERENCE]
        )
        with pytest.raises(InvalidCandidateError, match="user.preference.response_style"):
            registry.validate_candidate(candidate)


def test_validate_candidate_unknown_slot_raises_invalid_candidate_error() -> None:
    from sebastian.memory.errors import InvalidCandidateError
    from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )

    candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id="no.such.slot",
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
    with pytest.raises(InvalidCandidateError):
        DEFAULT_SLOT_REGISTRY.validate_candidate(candidate)

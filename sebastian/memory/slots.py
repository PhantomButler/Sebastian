from __future__ import annotations

from collections.abc import Iterable

from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)

# Kinds that MUST be bound to a registered slot.
_SLOT_REQUIRED_KINDS: frozenset[MemoryKind] = frozenset(
    [MemoryKind.FACT, MemoryKind.PREFERENCE]
)

_BUILTIN_SLOTS: list[SlotDefinition] = [
    SlotDefinition(
        slot_id="user.preference.response_style",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="用户偏好的回复风格（简洁/详细/技术风格等）",
    ),
    SlotDefinition(
        slot_id="user.preference.language",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="用户偏好的交流语言",
    ),
    SlotDefinition(
        slot_id="user.current_project_focus",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户当前主要关注的项目",
    ),
    SlotDefinition(
        slot_id="user.profile.timezone",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户所在时区",
    ),
    SlotDefinition(
        slot_id="project.current_phase",
        scope=MemoryScope.PROJECT,
        subject_kind="project",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="项目当前所处阶段",
    ),
    SlotDefinition(
        slot_id="agent.current_assignment",
        scope=MemoryScope.AGENT,
        subject_kind="agent",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="Agent 当前被分配的任务",
    ),
]


class SlotRegistry:
    """Thin dict-backed registry of :class:`SlotDefinition` objects.

    When constructed with ``slots=None`` the 6 built-in Phase-A slots are
    loaded automatically.  Pass an explicit iterable to override (useful in
    tests).
    """

    def __init__(self, slots: Iterable[SlotDefinition] | None = None) -> None:
        source = _BUILTIN_SLOTS if slots is None else list(slots)
        self._slots: dict[str, SlotDefinition] = {s.slot_id: s for s in source}

    def get(self, slot_id: str) -> SlotDefinition | None:
        """Return the :class:`SlotDefinition` for *slot_id*, or ``None``."""
        return self._slots.get(slot_id)

    def require(self, slot_id: str) -> SlotDefinition:
        """Return the :class:`SlotDefinition` for *slot_id*.

        Raises:
            UnknownSlotError: if *slot_id* is not registered.
        """
        slot = self._slots.get(slot_id)
        if slot is None:
            from sebastian.memory.errors import UnknownSlotError

            raise UnknownSlotError(f"slot_id '{slot_id}' not registered")
        return slot

    def validate_candidate(self, candidate: CandidateArtifact) -> list[str]:
        """Validate *candidate* against this registry.

        Returns a list of error strings; an empty list means the candidate is
        valid.

        Rules enforced here:
        - ``fact`` and ``preference`` candidates must have a non-None
          ``slot_id`` that is registered in this registry.
        - All other kinds (``episode``, ``entity``, ``relation``, ``summary``)
          may have ``slot_id=None``.
        """
        if candidate.kind not in _SLOT_REQUIRED_KINDS:
            return []

        errors: list[str] = []
        if candidate.slot_id is None:
            errors.append(
                f"Candidate of kind '{candidate.kind}' must have a slot_id"
                " (fact/preference require a registered slot)."
            )
        elif candidate.slot_id not in self._slots:
            errors.append(
                f"slot_id '{candidate.slot_id}' is not registered in this SlotRegistry."
            )
        else:
            slot = self._slots[candidate.slot_id]
            if candidate.kind not in slot.kind_constraints:
                errors.append(
                    f"Candidate kind '{candidate.kind}' is not allowed"
                    f" for slot '{candidate.slot_id}'"
                    f" (allowed: {[k.value for k in slot.kind_constraints]})."
                )
        return errors


DEFAULT_SLOT_REGISTRY: SlotRegistry = SlotRegistry()

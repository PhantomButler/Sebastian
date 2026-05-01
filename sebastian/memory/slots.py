from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sebastian.memory.errors import InvalidCandidateError, UnknownSlotError
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)

if TYPE_CHECKING:
    from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore

# Kinds that MUST be bound to a registered slot.
_SLOT_REQUIRED_KINDS: frozenset[MemoryKind] = frozenset([MemoryKind.FACT, MemoryKind.PREFERENCE])

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
        slot_id="user.preference.addressing",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="用户偏好的称呼方式",
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
    SlotDefinition(
        slot_id="user.profile.name",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户姓名",
    ),
    SlotDefinition(
        slot_id="user.profile.location",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户所在地",
    ),
    SlotDefinition(
        slot_id="user.profile.occupation",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户职业",
    ),
]


class SlotRegistry:
    """Thin dict-backed registry of :class:`SlotDefinition` objects.

    When constructed with ``slots=None`` the 9 built-in Phase-A slots are
    loaded automatically.  Pass an explicit iterable to override (useful in
    tests).
    """

    def __init__(self, slots: Iterable[SlotDefinition] | None = None) -> None:
        source = _BUILTIN_SLOTS if slots is None else list(slots)
        self._slots: dict[str, SlotDefinition] = {s.slot_id: s for s in source}

    def list_all(self) -> list[SlotDefinition]:
        """Return every registered :class:`SlotDefinition` in insertion order."""
        return list(self._slots.values())

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
            raise UnknownSlotError(f"slot_id '{slot_id}' not registered")
        return slot

    def validate_candidate(self, candidate: CandidateArtifact) -> None:
        """Validate *candidate* against this registry.

        Rules enforced here:
        - ``fact`` and ``preference`` candidates must have a non-None
          ``slot_id`` that is registered in this registry.
        - The candidate kind must match the slot's ``kind_constraints``.
        - All other kinds (``episode``, ``entity``, ``relation``, ``summary``)
          may have ``slot_id=None``.

        Raises:
            InvalidCandidateError: if the candidate fails any rule above.
        """
        if candidate.kind not in _SLOT_REQUIRED_KINDS:
            return

        if candidate.slot_id is None:
            raise InvalidCandidateError(
                f"Candidate of kind '{candidate.kind}' must have a slot_id"
                " (fact/preference require a registered slot)."
            )
        if candidate.slot_id not in self._slots:
            raise InvalidCandidateError(
                f"slot_id '{candidate.slot_id}' is not registered in this SlotRegistry."
            )
        slot = self._slots[candidate.slot_id]
        if candidate.kind not in slot.kind_constraints:
            raise InvalidCandidateError(
                f"Candidate kind '{candidate.kind}' is not allowed"
                f" for slot '{candidate.slot_id}'"
                f" (allowed: {[k.value for k in slot.kind_constraints]})."
            )

    def register(self, schema: SlotDefinition) -> None:
        """运行时注册 / 覆盖 slot。被 SlotProposalHandler 调用。"""
        self._slots[schema.slot_id] = schema

    async def bootstrap_from_db(self, store: SlotDefinitionStore) -> None:
        """服务启动时调用一次，把 DB 所有 slot 灌入内存。"""
        schemas = await store.list_all()
        for s in schemas:
            self._slots[s.slot_id] = s


DEFAULT_SLOT_REGISTRY: SlotRegistry = SlotRegistry()

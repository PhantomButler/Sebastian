from __future__ import annotations

import re

from sebastian.memory.errors import InvalidSlotProposalError
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
)

_SLOT_ID_PATTERN = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*\.[a-z][a-z_]*$")
_VALID_SCOPE_PREFIXES: frozenset[str] = frozenset(s.value for s in MemoryScope)
_MAX_SLOT_ID_LEN = 64


def validate_proposed_slot(proposed: ProposedSlot) -> None:
    """校验 ProposedSlot 的命名与字段组合。失败抛 InvalidSlotProposalError。"""
    _validate_naming(proposed.slot_id)
    _validate_scope_prefix(proposed.slot_id, proposed.scope)
    _validate_field_combination(proposed)


def _validate_naming(slot_id: str) -> None:
    if len(slot_id) > _MAX_SLOT_ID_LEN:
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 不符合命名规则：总长不得超过 {_MAX_SLOT_ID_LEN}"
        )
    if not _SLOT_ID_PATTERN.match(slot_id):
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 不符合命名规则：需三段 {{scope}}.{{category}}.{{attribute}}，"
            "纯小写 + 下划线"
        )
    first_segment = slot_id.split(".", 1)[0]
    if first_segment not in _VALID_SCOPE_PREFIXES:
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 不符合命名规则：首段 '{first_segment}' 必须 ∈ "
            f"{sorted(_VALID_SCOPE_PREFIXES)}"
        )


def _validate_scope_prefix(slot_id: str, scope: MemoryScope) -> None:
    first_segment = slot_id.split(".", 1)[0]
    if first_segment != scope.value:
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 首段 '{first_segment}' 与 scope '{scope.value}' 不一致"
        )


def _validate_field_combination(proposed: ProposedSlot) -> None:
    if not proposed.kind_constraints:
        raise InvalidSlotProposalError("kind_constraints 不得为空，至少 1 项")
    if (
        proposed.cardinality == Cardinality.SINGLE
        and proposed.resolution_policy == ResolutionPolicy.APPEND_ONLY
    ):
        raise InvalidSlotProposalError(
            "组合非法：cardinality=single + resolution_policy=append_only 矛盾"
        )
    if proposed.resolution_policy == ResolutionPolicy.TIME_BOUND:
        allowed = {MemoryKind.FACT, MemoryKind.PREFERENCE}
        if not set(proposed.kind_constraints) & allowed:
            raise InvalidSlotProposalError(
                "resolution_policy=time_bound 要求 kind_constraints 至少含 fact 或 preference"
            )

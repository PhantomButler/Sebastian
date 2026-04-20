from __future__ import annotations

import pytest

from sebastian.memory.errors import InvalidSlotProposalError
from sebastian.memory.slot_proposals import validate_proposed_slot
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
)

_SENTINEL: list[MemoryKind] = []


def _make(
    *,
    slot_id: str = "user.profile.hobby",
    scope: MemoryScope = MemoryScope.USER,
    cardinality: Cardinality = Cardinality.MULTI,
    resolution_policy: ResolutionPolicy = ResolutionPolicy.APPEND_ONLY,
    kind_constraints: list[MemoryKind] | None = None,
) -> ProposedSlot:
    # kind_constraints=None → 默认 [PREFERENCE]；kind_constraints=[] → 真正空列表
    if kind_constraints is None:
        resolved_constraints = [MemoryKind.PREFERENCE]
    else:
        resolved_constraints = kind_constraints
    return ProposedSlot(
        slot_id=slot_id,
        scope=scope,
        subject_kind="user",
        cardinality=cardinality,
        resolution_policy=resolution_policy,
        kind_constraints=resolved_constraints,
        description="x",
    )


def test_valid_slot_passes() -> None:
    validate_proposed_slot(_make())


@pytest.mark.parametrize(
    "bad_id",
    [
        "user.profile",  # 段数不对
        "user.profile.like.book",  # 段数太多
        "User.profile.hobby",  # 大写
        "user.profile.like-book",  # 连字符
        "other.profile.hobby",  # 首段非合法 scope
        "a" * 70 + ".x.y",  # 超长
        ".profile.hobby",  # 空段
        "user..hobby",  # 空段
        "user.profile.",  # 尾空
    ],
)
def test_invalid_naming_rejected(bad_id: str) -> None:
    with pytest.raises(InvalidSlotProposalError, match="命名规则"):
        validate_proposed_slot(_make(slot_id=bad_id))


def test_scope_prefix_must_match_slot_id() -> None:
    with pytest.raises(InvalidSlotProposalError, match="scope"):
        validate_proposed_slot(_make(slot_id="user.profile.hobby", scope=MemoryScope.PROJECT))


def test_single_with_append_only_rejected() -> None:
    with pytest.raises(InvalidSlotProposalError, match="组合"):
        validate_proposed_slot(
            _make(cardinality=Cardinality.SINGLE, resolution_policy=ResolutionPolicy.APPEND_ONLY)
        )


def test_time_bound_requires_fact_or_preference() -> None:
    with pytest.raises(InvalidSlotProposalError, match="time_bound"):
        validate_proposed_slot(
            _make(
                resolution_policy=ResolutionPolicy.TIME_BOUND,
                kind_constraints=[MemoryKind.EPISODE],
            )
        )


def test_empty_kind_constraints_rejected() -> None:
    # Pydantic 允许 list 为空，校验器要把关
    with pytest.raises(InvalidSlotProposalError, match="kind_constraints"):
        validate_proposed_slot(_make(kind_constraints=[]))

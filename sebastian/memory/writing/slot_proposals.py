from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy.exc import IntegrityError

from sebastian.memory.errors import InvalidSlotProposalError
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
    SlotDefinition,
)

if TYPE_CHECKING:
    from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore
    from sebastian.memory.writing.slots import SlotRegistry

logger = logging.getLogger(__name__)

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


class SlotProposalHandler:
    """共享组件：把 ProposedSlot 注册到系统（DB + in-memory registry）。

    不含 LLM 调用 / 不含重试循环 —— 重试策略由调用方（Extractor / Consolidator）掌控。
    """

    def __init__(self, store: SlotDefinitionStore, registry: SlotRegistry) -> None:
        self._store = store
        self._registry = registry

    async def register_or_reuse(
        self,
        proposed: ProposedSlot,
        *,
        proposed_by: Literal["extractor", "consolidator"],
        proposed_in_session: str | None,
    ) -> SlotDefinition:
        """校验 proposed，写入 DB + 内存 registry，或在冲突时复用已有赢家。

        1. validate_proposed_slot 校验（失败直接透传 InvalidSlotProposalError）
        2. 若内存 registry 已有同 slot_id → 直接返回（快路径）
        3. 用 session.begin_nested() savepoint 隔离 INSERT
        4. IntegrityError → 读赢家 → 同步内存 registry → 返回赢家
        """
        validate_proposed_slot(proposed)

        # 快路径：内存已有，直接复用
        existing = self._registry.get(proposed.slot_id)
        if existing is not None:
            return existing

        schema = SlotDefinition(
            slot_id=proposed.slot_id,
            scope=proposed.scope,
            subject_kind=proposed.subject_kind,
            cardinality=proposed.cardinality,
            resolution_policy=proposed.resolution_policy,
            kind_constraints=list(proposed.kind_constraints),
            description=proposed.description,
        )

        session = self._store.session
        try:
            async with session.begin_nested():
                await self._store.insert(
                    schema,
                    is_builtin=False,
                    proposed_by=proposed_by,
                    proposed_in_session=proposed_in_session,
                    created_at=datetime.now(UTC),
                )
        except IntegrityError:
            # 并发 race：另一个 session 已写入，读赢家
            winner_record = await self._store.get(proposed.slot_id)
            if winner_record is None:
                # 理论不可能：IntegrityError 说明冲突已存在
                raise
            winner_schema = _record_to_slot_definition(winner_record)
            self._registry.register(winner_schema)
            logger.info(
                "slot.proposal.concurrent_lost slot_id=%s proposed_by=%s",
                proposed.slot_id,
                proposed_by,
            )
            return winner_schema

        self._registry.register(schema)
        logger.info(
            "slot.proposal.accepted slot_id=%s proposed_by=%s session=%s",
            proposed.slot_id,
            proposed_by,
            proposed_in_session,
        )
        return schema


def _record_to_slot_definition(record: object) -> SlotDefinition:
    """将 MemorySlotRecord ORM 对象转成 SlotDefinition（避免循环 import，在本文件复刻最小映射）。"""
    return SlotDefinition(
        slot_id=record.slot_id,  # type: ignore[attr-defined]
        scope=MemoryScope(record.scope),  # type: ignore[attr-defined]
        subject_kind=record.subject_kind,  # type: ignore[attr-defined]
        cardinality=Cardinality(record.cardinality),  # type: ignore[attr-defined]
        resolution_policy=ResolutionPolicy(record.resolution_policy),  # type: ignore[attr-defined]
        kind_constraints=[MemoryKind(k) for k in record.kind_constraints],  # type: ignore[attr-defined]
        description=record.description,  # type: ignore[attr-defined]
    )

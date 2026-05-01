from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)
from sebastian.store.models import MemorySlotRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SlotDefinitionStore:
    """memory_slots 表的 CRUD 封装。纯 DB 层，不含业务逻辑。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def insert(
        self,
        schema: SlotDefinition,
        *,
        is_builtin: bool,
        proposed_by: str | None,
        proposed_in_session: str | None,
        created_at: datetime,
    ) -> None:
        """INSERT 一行。slot_id 已存在时抛 sqlalchemy.exc.IntegrityError。"""
        record = MemorySlotRecord(
            slot_id=schema.slot_id,
            scope=schema.scope.value,
            subject_kind=schema.subject_kind,
            cardinality=schema.cardinality.value,
            resolution_policy=schema.resolution_policy.value,
            kind_constraints=[k.value for k in schema.kind_constraints],
            description=schema.description,
            is_builtin=is_builtin,
            proposed_by=proposed_by,
            proposed_in_session=proposed_in_session,
            created_at=created_at,
            updated_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()

    async def get(self, slot_id: str) -> MemorySlotRecord | None:
        """按 slot_id 查询，不存在返回 None。"""
        result = await self._session.execute(
            select(MemorySlotRecord).where(MemorySlotRecord.slot_id == slot_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[SlotDefinition]:
        """返回所有 slot 定义（转成 SlotDefinition schema）。"""
        result = await self._session.execute(select(MemorySlotRecord))
        return [_record_to_schema(row) for row in result.scalars().all()]


def _record_to_schema(record: MemorySlotRecord) -> SlotDefinition:
    return SlotDefinition(
        slot_id=record.slot_id,
        scope=MemoryScope(record.scope),
        subject_kind=record.subject_kind,
        cardinality=Cardinality(record.cardinality),
        resolution_policy=ResolutionPolicy(record.resolution_policy),
        kind_constraints=[MemoryKind(k) for k in record.kind_constraints],
        description=record.description,
    )

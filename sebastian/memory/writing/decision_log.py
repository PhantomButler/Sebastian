from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sebastian.memory.trace import trace
from sebastian.memory.types import ResolveDecision
from sebastian.store.models import MemoryDecisionLogRecord


class MemoryDecisionLogger:
    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def append(
        self,
        decision: ResolveDecision,
        *,
        worker: str,
        model: str | None,
        rule_version: str,
        input_source: dict[str, Any] | None = None,
    ) -> MemoryDecisionLogRecord:
        # session_id 解析顺序：
        # 1. decision.new_memory.provenance["session_id"]
        # 2. input_source["session_id"]（如果 input_source 不为 None 且含此键）
        # 3. None
        session_id: str | None = None
        if decision.new_memory is not None:
            provenance = decision.new_memory.provenance or {}
            session_id_val = provenance.get("session_id")
            if isinstance(session_id_val, str):
                session_id = session_id_val
        if session_id is None and input_source is not None:
            fallback = input_source.get("session_id")
            if isinstance(fallback, str):
                session_id = fallback

        record = MemoryDecisionLogRecord(
            id=str(uuid4()),
            decision=decision.decision.value,
            subject_id=decision.subject_id,
            scope=decision.scope.value,
            slot_id=decision.slot_id,
            candidate=decision.candidate.model_dump(mode="json"),
            conflicts=list(decision.old_memory_ids),
            reason=decision.reason,
            old_memory_ids=list(decision.old_memory_ids),
            new_memory_id=decision.new_memory.id if decision.new_memory is not None else None,
            worker=worker,
            model=model,
            session_id=session_id,
            rule_version=rule_version,
            input_source=input_source,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.flush()
        trace(
            "decision_log.append",
            id=record.id,
            decision=decision.decision,
            worker=worker,
            model=model,
            subject_id=decision.subject_id,
            scope=decision.scope,
            slot_id=decision.slot_id,
            new_memory_id=record.new_memory_id,
            old_count=len(decision.old_memory_ids),
        )
        return record

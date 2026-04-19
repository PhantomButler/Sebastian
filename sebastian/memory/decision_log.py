from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> MemoryDecisionLogRecord:
        session_id: str | None = None
        if decision.new_memory is not None:
            provenance = decision.new_memory.provenance or {}
            session_id_val = provenance.get("session_id")
            if isinstance(session_id_val, str):
                session_id = session_id_val

        record = MemoryDecisionLogRecord(
            id=str(uuid4()),
            decision=decision.decision.value,
            subject_id=decision.subject_id,
            scope=decision.scope.value,
            slot_id=decision.slot_id,
            candidate=decision.candidate.model_dump(mode="json"),
            conflicts=[],
            reason=decision.reason,
            old_memory_ids=list(decision.old_memory_ids),
            new_memory_id=decision.new_memory.id if decision.new_memory is not None else None,
            worker=worker,
            model=model,
            session_id=session_id,
            rule_version=rule_version,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.flush()
        return record

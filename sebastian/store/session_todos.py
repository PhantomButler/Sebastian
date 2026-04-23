from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.core.types import TodoItem
from sebastian.store.models import SessionTodoRecord


class SessionTodoStore:
    """per-session todo 的 SQLite 读写。"""

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db = db_factory

    async def read(self, agent_type: str, session_id: str) -> list[TodoItem]:
        async with self._db() as db:
            result = await db.execute(
                select(SessionTodoRecord).where(
                    SessionTodoRecord.agent_type == agent_type,
                    SessionTodoRecord.session_id == session_id,
                )
            )
            record = result.scalar_one_or_none()
        if record is None:
            return []
        return [TodoItem(**item) for item in record.todos]

    async def read_updated_at(self, agent_type: str, session_id: str) -> datetime | None:
        async with self._db() as db:
            result = await db.execute(
                select(SessionTodoRecord).where(
                    SessionTodoRecord.agent_type == agent_type,
                    SessionTodoRecord.session_id == session_id,
                )
            )
            record = result.scalar_one_or_none()
        if record is None:
            return None
        return record.updated_at

    async def write(
        self,
        agent_type: str,
        session_id: str,
        todos: list[TodoItem],
    ) -> None:
        async with self._db() as db:
            result = await db.execute(
                select(SessionTodoRecord).where(
                    SessionTodoRecord.agent_type == agent_type,
                    SessionTodoRecord.session_id == session_id,
                )
            )
            record = result.scalar_one_or_none()
            now = datetime.now(UTC)
            payload = [item.model_dump(mode="json", by_alias=True) for item in todos]
            if record is None:
                record = SessionTodoRecord(
                    session_id=session_id,
                    agent_type=agent_type,
                    todos=payload,
                    updated_at=now,
                )
                db.add(record)
            else:
                record.todos = payload
                record.updated_at = now
            await db.commit()

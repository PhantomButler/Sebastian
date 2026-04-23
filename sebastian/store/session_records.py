from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.core.types import Session, SessionStatus
from sebastian.store.models import SessionRecord


class SessionRecordsStore:
    """Session 元数据的 SQLite CRUD、列表查询、active children、activity 更新。"""

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db = db_factory

    async def create(self, session: Session) -> Session:
        async with self._db() as db:
            record = _to_record(session)
            db.add(record)
            await db.commit()
        return session

    async def get(self, session_id: str, agent_type: str) -> Session | None:
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord).where(
                    SessionRecord.id == session_id,
                    SessionRecord.agent_type == agent_type,
                )
            )
            record = result.scalar_one_or_none()
        return _to_session(record) if record else None

    async def update(self, session: Session) -> None:
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord).where(
                    SessionRecord.id == session.id,
                    SessionRecord.agent_type == session.agent_type,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(
                    f"Session not found: session_id={session.id}, agent_type={session.agent_type}"
                )
            _apply_session_to_record(session, record)
            await db.commit()

    async def delete(self, session: Session) -> None:
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord).where(
                    SessionRecord.id == session.id,
                    SessionRecord.agent_type == session.agent_type,
                )
            )
            record = result.scalar_one_or_none()
            if record:
                await db.delete(record)
                await db.commit()

    async def list_all(self) -> list[dict[str, Any]]:
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord).order_by(SessionRecord.last_activity_at.desc())
            )
            return [_record_to_dict(r) for r in result.scalars()]

    async def list_by_agent_type(self, agent_type: str) -> list[dict[str, Any]]:
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord)
                .where(SessionRecord.agent_type == agent_type)
                .order_by(SessionRecord.last_activity_at.desc())
            )
            return [_record_to_dict(r) for r in result.scalars()]

    async def list_active_children(
        self,
        agent_type: str,
        parent_session_id: str,
    ) -> list[dict[str, Any]]:
        active_statuses = (
            SessionStatus.ACTIVE.value,
            SessionStatus.STALLED.value,
            SessionStatus.WAITING.value,
        )
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord).where(
                    SessionRecord.agent_type == agent_type,
                    SessionRecord.parent_session_id == parent_session_id,
                    SessionRecord.status.in_(active_statuses),
                )
            )
            return [_record_to_dict(r) for r in result.scalars()]

    async def update_activity(self, session_id: str, agent_type: str) -> None:
        now = datetime.now(UTC)
        async with self._db() as db:
            result = await db.execute(
                select(SessionRecord).where(
                    SessionRecord.id == session_id,
                    SessionRecord.agent_type == agent_type,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                return
            record.last_activity_at = now
            record.updated_at = now
            if record.status == SessionStatus.STALLED.value:
                record.status = SessionStatus.ACTIVE.value
            await db.commit()


def _to_record(session: Session) -> SessionRecord:
    return SessionRecord(
        id=session.id,
        agent_type=session.agent_type,
        title=session.title,
        goal=session.goal,
        status=(
            session.status.value if isinstance(session.status, SessionStatus) else session.status
        ),
        depth=session.depth,
        parent_session_id=session.parent_session_id,
        last_activity_at=session.last_activity_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
        task_count=session.task_count,
        active_task_count=session.active_task_count,
        next_item_seq=1,
    )


def _apply_session_to_record(session: Session, record: SessionRecord) -> None:
    record.title = session.title
    record.goal = session.goal
    record.status = (
        session.status.value if isinstance(session.status, SessionStatus) else session.status
    )
    record.depth = session.depth
    record.parent_session_id = session.parent_session_id
    record.last_activity_at = session.last_activity_at
    record.updated_at = datetime.now(UTC)
    record.task_count = session.task_count
    record.active_task_count = session.active_task_count


def _to_session(record: SessionRecord) -> Session:
    return Session(
        id=record.id,
        agent_type=record.agent_type,
        title=record.title,
        goal=record.goal,
        status=SessionStatus(record.status),
        depth=record.depth,
        parent_session_id=record.parent_session_id,
        last_activity_at=record.last_activity_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        task_count=record.task_count,
        active_task_count=record.active_task_count,
    )


def _record_to_dict(record: SessionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "agent_type": record.agent_type,
        "title": record.title,
        "goal": record.goal,
        "status": record.status,
        "depth": record.depth,
        "parent_session_id": record.parent_session_id,
        "last_activity_at": (
            record.last_activity_at.isoformat() if record.last_activity_at else None
        ),
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "task_count": record.task_count,
        "active_task_count": record.active_task_count,
    }

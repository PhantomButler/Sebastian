from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.core.types import Checkpoint, ResourceBudget, Task, TaskPlan, TaskStatus
from sebastian.store.models import CheckpointRecord, SessionRecord, TaskRecord

_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class SessionTaskStore:
    """SQLite-backed task and checkpoint CRUD, scoped by session and agent_type."""

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db = db_factory

    async def create(self, task: Task, agent_type: str) -> Task:
        """Persist a new task and refresh session task counts."""
        async with self._db() as db:
            record = TaskRecord(
                id=task.id,
                session_id=task.session_id,
                agent_type=agent_type,
                goal=task.goal,
                status=task.status.value,
                assigned_agent=task.assigned_agent,
                parent_task_id=task.parent_task_id,
                plan=task.plan.model_dump() if task.plan else None,
                resource_budget=task.resource_budget.model_dump(),
                created_at=task.created_at,
                updated_at=task.updated_at,
                completed_at=task.completed_at,
            )
            db.add(record)
            await db.flush()
            await _refresh_task_counts(db, task.session_id, agent_type)
            await db.commit()
        return task

    async def get(self, session_id: str, task_id: str, agent_type: str) -> Task | None:
        """Retrieve a task by session, task id, and agent_type."""
        async with self._db() as db:
            result = await db.execute(
                select(TaskRecord).where(
                    TaskRecord.id == task_id,
                    TaskRecord.session_id == session_id,
                    TaskRecord.agent_type == agent_type,
                )
            )
            record = result.scalar_one_or_none()
        return _to_task(record) if record else None

    async def list_tasks(self, session_id: str, agent_type: str) -> list[Task]:
        """List all tasks for a session, ordered by creation time."""
        async with self._db() as db:
            result = await db.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.session_id == session_id,
                    TaskRecord.agent_type == agent_type,
                )
                .order_by(TaskRecord.created_at)
            )
            return [_to_task(r) for r in result.scalars()]

    async def update_status(
        self,
        session_id: str,
        task_id: str,
        status: TaskStatus,
        agent_type: str,
    ) -> None:
        """Update task status; set completed_at for terminal statuses and refresh counts."""
        async with self._db() as db:
            result = await db.execute(
                select(TaskRecord).where(
                    TaskRecord.id == task_id,
                    TaskRecord.session_id == session_id,
                    TaskRecord.agent_type == agent_type,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(
                    f"Task not found: task_id={task_id},"
                    f" session_id={session_id}, agent_type={agent_type}"
                )
            record.status = status.value
            record.updated_at = datetime.now(UTC)
            if status in _TERMINAL_STATUSES:
                record.completed_at = datetime.now(UTC)
            await db.flush()
            await _refresh_task_counts(db, session_id, agent_type)
            await db.commit()

    async def append_checkpoint(
        self,
        session_id: str,
        checkpoint: Checkpoint,
        agent_type: str,
    ) -> None:
        """Persist a checkpoint record."""
        async with self._db() as db:
            record = CheckpointRecord(
                id=checkpoint.id,
                task_id=checkpoint.task_id,
                session_id=session_id,
                agent_type=agent_type,
                step=checkpoint.step,
                data=checkpoint.data,
                created_at=checkpoint.created_at,
            )
            db.add(record)
            await db.commit()

    async def get_checkpoints(
        self,
        session_id: str,
        task_id: str,
        agent_type: str,
    ) -> list[Checkpoint]:
        """Return all checkpoints for a task ordered by step."""
        async with self._db() as db:
            result = await db.execute(
                select(CheckpointRecord)
                .where(
                    CheckpointRecord.task_id == task_id,
                    CheckpointRecord.session_id == session_id,
                    CheckpointRecord.agent_type == agent_type,
                )
                .order_by(CheckpointRecord.step)
            )
            return [
                Checkpoint(
                    id=r.id,
                    task_id=r.task_id,
                    step=r.step,
                    data=r.data,
                    created_at=r.created_at,
                )
                for r in result.scalars()
            ]


async def _refresh_task_counts(
    db: AsyncSession,
    session_id: str,
    agent_type: str,
) -> None:
    """Recompute task_count and active_task_count on the sessions row.

    Must be called inside an open DB session before commit.
    """
    result = await db.execute(
        select(TaskRecord).where(
            TaskRecord.session_id == session_id,
            TaskRecord.agent_type == agent_type,
        )
    )
    tasks = list(result.scalars())
    total = len(tasks)
    active = sum(1 for t in tasks if TaskStatus(t.status) not in _TERMINAL_STATUSES)

    session_result = await db.execute(
        select(SessionRecord).where(
            SessionRecord.id == session_id,
            SessionRecord.agent_type == agent_type,
        )
    )
    session_record = session_result.scalar_one_or_none()
    if session_record is not None:
        session_record.task_count = total
        session_record.active_task_count = active
        session_record.updated_at = datetime.now(UTC)


def _to_task(r: TaskRecord) -> Task:
    return Task(
        id=r.id,
        session_id=r.session_id,
        goal=r.goal,
        status=TaskStatus(r.status),
        assigned_agent=r.assigned_agent,
        parent_task_id=r.parent_task_id,
        plan=TaskPlan(**r.plan) if r.plan else None,
        resource_budget=ResourceBudget(**r.resource_budget),
        created_at=r.created_at,
        updated_at=r.updated_at,
        completed_at=r.completed_at,
    )

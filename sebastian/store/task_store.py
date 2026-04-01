from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sebastian.core.types import Checkpoint, ResourceBudget, Task, TaskPlan, TaskStatus
from sebastian.store.models import CheckpointRecord, TaskRecord


class TaskStore:
    """Persistent storage for tasks and their checkpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        """Create and persist a task."""
        record = TaskRecord(
            id=task.id,
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
        self._session.add(record)
        await self._session.commit()
        return task

    async def get(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        result = await self._session.execute(
            select(TaskRecord).where(TaskRecord.id == task_id)
        )
        record = result.scalar_one_or_none()
        return self._to_task(record) if record else None

    async def list_tasks(self, status: str | None = None) -> list[Task]:
        """List all tasks, optionally filtered by status."""
        q = select(TaskRecord)
        if status:
            q = q.where(TaskRecord.status == status)
        q = q.order_by(TaskRecord.created_at.desc())
        result = await self._session.execute(q)
        return [self._to_task(r) for r in result.scalars()]

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        """Update task status and set completion time if applicable."""
        result = await self._session.execute(
            select(TaskRecord).where(TaskRecord.id == task_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return
        record.status = status.value
        record.updated_at = datetime.now(UTC)
        if status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            record.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def add_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Add a checkpoint to a task."""
        record = CheckpointRecord(
            id=checkpoint.id,
            task_id=checkpoint.task_id,
            step=checkpoint.step,
            data=checkpoint.data,
            created_at=checkpoint.created_at,
        )
        self._session.add(record)
        await self._session.commit()

    async def get_checkpoints(self, task_id: str) -> list[Checkpoint]:
        """Get all checkpoints for a task, ordered by step."""
        result = await self._session.execute(
            select(CheckpointRecord)
            .where(CheckpointRecord.task_id == task_id)
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

    def _to_task(self, r: TaskRecord) -> Task:
        """Convert a TaskRecord to a Task domain object."""
        return Task(
            id=r.id,
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

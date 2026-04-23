from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sebastian.core.types import InvalidTaskTransitionError, Task, TaskStatus
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType
from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)

TaskFn = Callable[[Task], Awaitable[None]]

_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.PLANNING},
    TaskStatus.PLANNING: {TaskStatus.RUNNING, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}

_STATUS_TO_EVENT: dict[TaskStatus, EventType] = {
    TaskStatus.PLANNING: EventType.TASK_PLANNING_STARTED,
    TaskStatus.RUNNING: EventType.TASK_STARTED,
    TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
    TaskStatus.FAILED: EventType.TASK_FAILED,
    TaskStatus.CANCELLED: EventType.TASK_CANCELLED,
}


class TaskManager:
    """Submits tasks for async background execution. Persists to SessionStore."""

    def __init__(
        self,
        session_store: SessionStore,
        event_bus: EventBus,
    ) -> None:
        self._store = session_store
        self._bus = event_bus
        self._running: dict[str, asyncio.Task[None]] = {}
        self._tasks: dict[str, Task] = {}

    async def submit(self, task: Task, fn: TaskFn) -> None:
        await self._store.create_task(task, task.assigned_agent)
        self._tasks[task.id] = task
        await self._bus.publish(
            Event(
                type=EventType.TASK_CREATED,
                data={
                    "task_id": task.id,
                    "session_id": task.session_id,
                    "goal": task.goal,
                    "assigned_agent": task.assigned_agent,
                },
            )
        )

        async def _run() -> None:
            try:
                await self._transition(task, TaskStatus.PLANNING)
                await self._transition(task, TaskStatus.RUNNING)
                await fn(task)
                await self._transition(task, TaskStatus.COMPLETED)
            except asyncio.CancelledError:
                if TaskStatus.CANCELLED in _VALID_TRANSITIONS.get(task.status, set()):
                    await self._transition(task, TaskStatus.CANCELLED)
                    return
                raise
            except Exception as exc:
                logger.exception("Task %s failed", task.id)
                await self._transition(task, TaskStatus.FAILED, error=str(exc))
            finally:
                self._running.pop(task.id, None)
                self._tasks.pop(task.id, None)

        self._running[task.id] = asyncio.create_task(_run())

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        t = self._running.get(task_id)
        if task is None or t is None or task.status is not TaskStatus.RUNNING:
            return False
        t.cancel()
        return True

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running

    async def _transition(
        self,
        task: Task,
        new_status: TaskStatus,
        error: str | None = None,
    ) -> None:
        allowed = _VALID_TRANSITIONS.get(task.status, set())
        if new_status not in allowed:
            raise InvalidTaskTransitionError(
                f"Cannot transition task {task.id} from {task.status} to {new_status}"
            )

        # Update in-memory state first; roll back if the store write fails (M4).
        old_status = task.status
        old_updated_at = task.updated_at
        old_completed_at = task.completed_at

        now = datetime.now(UTC)
        task.status = new_status
        task.updated_at = now
        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = now

        try:
            await self._store.update_task_status(
                task.session_id,
                task.id,
                new_status,
                task.assigned_agent,
            )
        except Exception:
            # Roll back in-memory state so callers see consistent data (M4).
            task.status = old_status
            task.updated_at = old_updated_at
            task.completed_at = old_completed_at
            raise

        event_type = _STATUS_TO_EVENT.get(new_status)
        if event_type is None:
            return

        data: dict[str, str] = {
            "session_id": task.session_id,
            "task_id": task.id,
        }
        if error is not None:
            data["error"] = error
        await self._bus.publish(Event(type=event_type, data=data))

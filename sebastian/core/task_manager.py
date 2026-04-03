from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from sebastian.core.types import InvalidTaskTransitionError, Task, TaskStatus
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType
from sebastian.store.index_store import IndexStore
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
        index_store: IndexStore | None = None,
    ) -> None:
        self._store = session_store
        self._bus = event_bus
        self._index = index_store
        self._running: dict[str, asyncio.Task[None]] = {}
        self._tasks: dict[str, Task] = {}

    async def submit(self, task: Task, fn: TaskFn) -> None:
        agent_type, agent_id = self._resolve_agent_path(task.assigned_agent)
        await self._store.create_task(task, agent_type, agent_id)
        await self._sync_index(task.session_id, task.assigned_agent)
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

        agent_type, agent_id = self._resolve_agent_path(task.assigned_agent)
        await self._store.update_task_status(
            task.session_id,
            task.id,
            new_status,
            agent_type,
            agent_id,
        )
        persisted_task = await self._store.get_task(
            task.session_id,
            task.id,
            agent_type,
            agent_id,
        )
        if persisted_task is not None:
            task.status = persisted_task.status
            task.updated_at = persisted_task.updated_at
            task.completed_at = persisted_task.completed_at
        await self._sync_index(task.session_id, task.assigned_agent)

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

    def _resolve_agent_path(self, assigned_agent: str) -> tuple[str, str]:
        agent_type, separator, suffix = assigned_agent.rpartition("_")
        if separator and suffix.isdigit():
            return agent_type, assigned_agent
        return assigned_agent, f"{assigned_agent}_01"

    async def _sync_index(self, session_id: str, agent: str) -> None:
        if self._index is None:
            return
        agent_type, agent_id = self._resolve_agent_path(agent)
        session = await self._store.get_session(session_id, agent_type, agent_id)
        if session is not None:
            await self._index.upsert(session)

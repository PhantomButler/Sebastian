from __future__ import annotations
import asyncio
import logging
from typing import Any, Awaitable, Callable

from sebastian.core.types import Task, TaskStatus
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

TaskFn = Callable[[Task], Awaitable[None]]


class TaskManager:
    """Submits tasks for async background execution. Each task runs as an
    asyncio coroutine and publishes lifecycle events to the EventBus."""

    def __init__(self, session_factory: Any, event_bus: EventBus) -> None:
        self._session_factory = session_factory
        self._bus = event_bus
        self._running: dict[str, asyncio.Task] = {}

    async def submit(self, task: Task, fn: TaskFn) -> None:
        """Persist the task, then start execution in the background."""
        from sebastian.store.task_store import TaskStore

        async with self._session_factory() as session:
            store = TaskStore(session)
            await store.create(task)

        await self._bus.publish(Event(
            type=EventType.TASK_CREATED,
            data={
                "task_id": task.id,
                "goal": task.goal,
                "assigned_agent": task.assigned_agent,
            },
        ))

        async def _run() -> None:
            async with self._session_factory() as session:
                store = TaskStore(session)
                await store.update_status(task.id, TaskStatus.RUNNING)

            await self._bus.publish(Event(
                type=EventType.TASK_STARTED,
                data={"task_id": task.id},
            ))
            try:
                await fn(task)
                async with self._session_factory() as session:
                    store = TaskStore(session)
                    await store.update_status(task.id, TaskStatus.COMPLETED)
                await self._bus.publish(Event(
                    type=EventType.TASK_COMPLETED,
                    data={"task_id": task.id},
                ))
            except asyncio.CancelledError:
                async with self._session_factory() as session:
                    store = TaskStore(session)
                    await store.update_status(task.id, TaskStatus.CANCELLED)
                await self._bus.publish(Event(
                    type=EventType.TASK_CANCELLED,
                    data={"task_id": task.id},
                ))
            except Exception as exc:
                logger.exception("Task %s failed", task.id)
                async with self._session_factory() as session:
                    store = TaskStore(session)
                    await store.update_status(task.id, TaskStatus.FAILED)
                await self._bus.publish(Event(
                    type=EventType.TASK_FAILED,
                    data={"task_id": task.id, "error": str(exc)},
                ))
            finally:
                self._running.pop(task.id, None)

        asyncio_task = asyncio.create_task(_run())
        self._running[task.id] = asyncio_task

    async def cancel(self, task_id: str) -> bool:
        t = self._running.get(task_id)
        if t is None:
            return False
        t.cancel()
        return True

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running

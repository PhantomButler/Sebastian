from __future__ import annotations

import asyncio
import logging

from sebastian.protocol.a2a.types import DelegateTask, TaskResult

logger = logging.getLogger(__name__)


class A2ADispatcher:
    """Routes DelegateTask objects to per-agent-type queues and resolves results.

    Each agent type gets its own asyncio.Queue to prevent cross-type head-of-line
    blocking. Results are returned via per-task asyncio.Future objects.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[DelegateTask]] = {}
        self._futures: dict[str, asyncio.Future[TaskResult]] = {}

    def register_agent(self, agent_type: str) -> asyncio.Queue[DelegateTask]:
        """Create and store a queue for agent_type. Returns the queue."""
        queue: asyncio.Queue[DelegateTask] = asyncio.Queue()
        self._queues[agent_type] = queue
        return queue

    def get_queue(self, agent_type: str) -> asyncio.Queue[DelegateTask] | None:
        return self._queues.get(agent_type)

    async def delegate(self, agent_type: str, task: DelegateTask) -> TaskResult:
        """Put task in the agent's queue and await its result."""
        queue = self._queues.get(agent_type)
        if queue is None:
            return TaskResult(
                task_id=task.task_id,
                ok=False,
                error=f"No agent registered for type: {agent_type!r}",
            )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[TaskResult] = loop.create_future()
        self._futures[task.task_id] = future

        await queue.put(task)
        try:
            return await future
        finally:
            self._futures.pop(task.task_id, None)

    def resolve(self, result: TaskResult) -> None:
        """Called by worker loop when a task completes."""
        future = self._futures.get(result.task_id)
        if future is not None and not future.done():
            future.set_result(result)
        else:
            logger.debug(
                "resolve() called for unknown or already-done task_id=%s", result.task_id
            )

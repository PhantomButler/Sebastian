from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_dispatcher_delegate_resolves_when_worker_resolves() -> None:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask, TaskResult

    dispatcher = A2ADispatcher()
    queue = dispatcher.register_agent("code")

    task = DelegateTask(task_id="t1", goal="write hello.py")
    future_result = asyncio.create_task(dispatcher.delegate("code", task))

    received_task = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received_task.task_id == "t1"

    dispatcher.resolve(TaskResult(task_id="t1", ok=True, output={"summary": "done"}))

    result = await asyncio.wait_for(future_result, timeout=1.0)
    assert result.ok is True
    assert result.output["summary"] == "done"


@pytest.mark.asyncio
async def test_dispatcher_unknown_agent_returns_error() -> None:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask

    dispatcher = A2ADispatcher()
    task = DelegateTask(task_id="t2", goal="something")
    result = await dispatcher.delegate("nonexistent", task)
    assert result.ok is False
    assert "nonexistent" in (result.error or "")


@pytest.mark.asyncio
async def test_dispatcher_resolve_ignores_unknown_task_id() -> None:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import TaskResult

    dispatcher = A2ADispatcher()
    # Should not raise
    dispatcher.resolve(TaskResult(task_id="ghost", ok=True))

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sebastian.core.task_manager import TaskManager
from sebastian.core.types import InvalidTaskTransitionError, Session, Task, TaskStatus
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType
from sebastian.store.session_store import SessionStore


@pytest.fixture
def manager_context(
    tmp_path: Path,
) -> tuple[TaskManager, SessionStore, EventBus]:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    store = SessionStore(sessions_dir)
    bus = EventBus()
    return TaskManager(store, bus), store, bus


async def _await_background_task(manager: TaskManager, task_id: str) -> None:
    future = manager._running[task_id]
    await future


@pytest.mark.asyncio
async def test_transition_rejects_created_to_running(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    manager, store, _ = manager_context
    session = Session(agent_type="sebastian", title="test")
    await store.create_session(session)
    task = Task(session_id=session.id, goal="test transition", assigned_agent="sebastian")
    await store.create_task(task, "sebastian")

    with pytest.raises(InvalidTaskTransitionError):
        await manager._transition(task, TaskStatus.RUNNING)


@pytest.mark.asyncio
async def test_transition_rejects_completed_to_running(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    manager, store, _ = manager_context
    session = Session(agent_type="sebastian", title="test")
    await store.create_session(session)
    task = Task(
        session_id=session.id,
        goal="test transition",
        status=TaskStatus.COMPLETED,
        assigned_agent="sebastian",
    )
    await store.create_task(task, "sebastian")

    with pytest.raises(InvalidTaskTransitionError):
        await manager._transition(task, TaskStatus.RUNNING)


@pytest.mark.asyncio
async def test_transition_persists_and_publishes_events_in_order(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    manager, store, bus = manager_context
    session = Session(agent_type="sebastian", title="test")
    await store.create_session(session)

    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)

    task = Task(session_id=session.id, goal="complete task", assigned_agent="sebastian")
    await store.create_task(task, "sebastian")

    await manager._transition(task, TaskStatus.PLANNING)
    planning_updated_at = task.updated_at
    assert task.completed_at is None

    await manager._transition(task, TaskStatus.RUNNING)
    assert task.updated_at >= planning_updated_at
    assert task.completed_at is None

    await manager._transition(task, TaskStatus.COMPLETED)

    loaded = await store.get_task(session.id, task.id, "sebastian")
    assert loaded is not None
    assert loaded.status == TaskStatus.COMPLETED
    assert loaded.completed_at is not None
    assert loaded.updated_at >= planning_updated_at

    assert [event.type for event in received] == [
        EventType.TASK_PLANNING_STARTED,
        EventType.TASK_STARTED,
        EventType.TASK_COMPLETED,
    ]
    assert all(
        event.data["task_id"] == task.id and event.data["session_id"] == session.id
        for event in received
    )


@pytest.mark.asyncio
async def test_submit_runs_to_completion(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    manager, store, bus = manager_context
    session = Session(agent_type="stock", title="worker session")
    await store.create_session(session)

    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)

    seen_statuses: list[TaskStatus] = []

    async def fn(task: Task) -> None:
        seen_statuses.append(task.status)

    task = Task(session_id=session.id, goal="worker task", assigned_agent="stock")
    await manager.submit(task, fn)
    await _await_background_task(manager, task.id)

    loaded = await store.get_task(session.id, task.id, "stock")
    assert loaded is not None
    assert loaded.status == TaskStatus.COMPLETED
    assert loaded.completed_at is not None
    assert seen_statuses == [TaskStatus.RUNNING]

    assert [event.type for event in received] == [
        EventType.TASK_CREATED,
        EventType.TASK_PLANNING_STARTED,
        EventType.TASK_STARTED,
        EventType.TASK_COMPLETED,
    ]
    assert received[0].data["assigned_agent"] == "stock"


@pytest.mark.asyncio
async def test_cancel_returns_false_before_task_reaches_running(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    manager, store, _ = manager_context
    session = Session(agent_type="sebastian", title="test")
    await store.create_session(session)

    original_transition = manager._transition
    planning_done = asyncio.Event()
    allow_run_to_continue = asyncio.Event()

    async def gated_transition(
        task: Task,
        new_status: TaskStatus,
        error: str | None = None,
    ) -> None:
        await original_transition(task, new_status, error)
        if new_status == TaskStatus.PLANNING:
            planning_done.set()
            await allow_run_to_continue.wait()

    manager._transition = gated_transition  # type: ignore[method-assign]

    async def fn(task: Task) -> None:
        return None

    task = Task(session_id=session.id, goal="gated task", assigned_agent="sebastian")
    await manager.submit(task, fn)

    await planning_done.wait()
    assert task.status == TaskStatus.PLANNING
    assert await manager.cancel(task.id) is False

    allow_run_to_continue.set()
    await _await_background_task(manager, task.id)

    loaded = await store.get_task(session.id, task.id, "sebastian")
    assert loaded is not None
    assert loaded.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_submit_cancels_running_task_with_legal_transition(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    manager, store, bus = manager_context
    session = Session(agent_type="sebastian", title="test")
    await store.create_session(session)

    received: list[Event] = []
    started = asyncio.Event()

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)

    async def fn(task: Task) -> None:
        started.set()
        await asyncio.Future()

    task = Task(session_id=session.id, goal="cancel task", assigned_agent="sebastian")
    await manager.submit(task, fn)

    await started.wait()
    assert task.status == TaskStatus.RUNNING
    assert await manager.cancel(task.id) is True

    await _await_background_task(manager, task.id)

    loaded = await store.get_task(session.id, task.id, "sebastian")
    assert loaded is not None
    assert loaded.status == TaskStatus.CANCELLED
    assert loaded.completed_at is not None
    assert [event.type for event in received] == [
        EventType.TASK_CREATED,
        EventType.TASK_PLANNING_STARTED,
        EventType.TASK_STARTED,
        EventType.TASK_CANCELLED,
    ]


@pytest.mark.asyncio
async def test_task_manager_uses_agent_type_directly(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
) -> None:
    """assigned_agent 直接作为 agent_type，不剥离数字后缀。"""
    manager, store, _ = manager_context

    session = Session(agent_type="agent_v2", title="test")
    await store.create_session(session)

    async def fn(task: Task) -> None:
        pass

    task = Task(goal="test goal", session_id=session.id, assigned_agent="agent_v2")
    await manager.submit(task, fn)
    await _await_background_task(manager, task.id)

    loaded = await store.get_task(session.id, task.id, "agent_v2")
    assert loaded is not None, "Task should be stored under agent_type 'agent_v2', not 'agent_v'"
    assert loaded.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_transition_rolls_back_local_state_when_persist_fails(
    manager_context: tuple[TaskManager, SessionStore, EventBus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, store, _ = manager_context
    session = Session(agent_type="sebastian", title="test")
    await store.create_session(session)
    task = Task(session_id=session.id, goal="rollback task", assigned_agent="sebastian")
    await store.create_task(task, "sebastian")

    previous_status = task.status
    previous_updated_at = task.updated_at
    previous_completed_at = task.completed_at

    async def fail_update(*args: object, **kwargs: object) -> None:
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "update_task_status", fail_update)

    with pytest.raises(RuntimeError, match="store unavailable"):
        await manager._transition(task, TaskStatus.PLANNING)

    assert task.status == previous_status
    assert task.updated_at == previous_updated_at
    assert task.completed_at == previous_completed_at

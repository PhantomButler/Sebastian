from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.types import Checkpoint, Session, Task, TaskStatus
from sebastian.store.session_store import SessionStore


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    return SessionStore(sessions_dir)


@pytest.mark.asyncio
async def test_create_and_get_session(store: SessionStore) -> None:
    session = Session(agent="sebastian", title="Hello world")

    await store.create_session(session)

    loaded = await store.get_session(session.id)
    assert loaded is not None
    assert loaded.title == "Hello world"
    assert loaded.agent == "sebastian"


@pytest.mark.asyncio
async def test_append_and_get_messages(store: SessionStore) -> None:
    session = Session(agent="sebastian", title="Test")
    await store.create_session(session)

    await store.append_message(session.id, "user", "Hello")
    await store.append_message(session.id, "assistant", "Hi there")

    messages = await store.get_messages(session.id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_create_and_get_task(store: SessionStore) -> None:
    session = Session(agent="sebastian", title="Task test")
    await store.create_session(session)

    task = Task(session_id=session.id, goal="Research stocks")
    await store.create_task(task)

    loaded = await store.get_task(session.id, task.id)
    assert loaded is not None
    assert loaded.goal == "Research stocks"
    assert loaded.session_id == session.id


@pytest.mark.asyncio
async def test_update_task_status(store: SessionStore) -> None:
    session = Session(agent="sebastian", title="Status test")
    await store.create_session(session)
    task = Task(session_id=session.id, goal="Do thing")
    await store.create_task(task)

    await store.update_task_status(session.id, task.id, TaskStatus.RUNNING)

    loaded = await store.get_task(session.id, task.id)
    assert loaded is not None
    assert loaded.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_append_checkpoint(store: SessionStore) -> None:
    session = Session(agent="sebastian", title="Checkpoint test")
    await store.create_session(session)
    task = Task(session_id=session.id, goal="Step task")
    await store.create_task(task)
    checkpoint = Checkpoint(task_id=task.id, step=1, data={"result": "ok"})

    await store.append_checkpoint(session.id, checkpoint)

    checkpoints = await store.get_checkpoints(session.id, task.id)
    assert len(checkpoints) == 1
    assert checkpoints[0].step == 1


@pytest.mark.asyncio
async def test_list_tasks(store: SessionStore) -> None:
    session = Session(agent="sebastian", title="Multi task")
    await store.create_session(session)
    task_one = Task(session_id=session.id, goal="Task A")
    task_two = Task(session_id=session.id, goal="Task B")

    await store.create_task(task_one)
    await store.create_task(task_two)

    tasks = await store.list_tasks(session.id)
    assert len(tasks) == 2

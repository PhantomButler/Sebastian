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
    session = Session(
        agent_type="sebastian",
        title="Hello world",
    )

    await store.create_session(session)

    loaded = await store.get_session(session.id, "sebastian")
    assert loaded is not None
    assert loaded.title == "Hello world"
    assert loaded.agent_type == "sebastian"


@pytest.mark.asyncio
async def test_append_and_get_messages(store: SessionStore) -> None:
    session = Session(agent_type="sebastian", title="Test")
    await store.create_session(session)

    await store.append_message(session.id, "user", "Hello", "sebastian")
    await store.append_message(session.id, "assistant", "Hi there", "sebastian")

    messages = await store.get_messages(session.id, "sebastian")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_create_and_get_task(store: SessionStore) -> None:
    session = Session(
        agent_type="sebastian",
        title="Task test",
    )
    await store.create_session(session)

    task = Task(session_id=session.id, goal="Research stocks")
    await store.create_task(task, "sebastian")

    loaded = await store.get_task(session.id, task.id, "sebastian")
    assert loaded is not None
    assert loaded.goal == "Research stocks"
    assert loaded.session_id == session.id


@pytest.mark.asyncio
async def test_update_task_status(store: SessionStore) -> None:
    session = Session(
        agent_type="sebastian",
        title="Status test",
    )
    await store.create_session(session)
    task = Task(session_id=session.id, goal="Do thing")
    await store.create_task(task, "sebastian")

    await store.update_task_status(session.id, task.id, TaskStatus.RUNNING, "sebastian")

    loaded = await store.get_task(session.id, task.id, "sebastian")
    assert loaded is not None
    assert loaded.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_append_checkpoint(store: SessionStore) -> None:
    session = Session(
        agent_type="sebastian",
        title="Checkpoint test",
    )
    await store.create_session(session)
    task = Task(session_id=session.id, goal="Step task")
    await store.create_task(task, "sebastian")
    checkpoint = Checkpoint(task_id=task.id, step=1, data={"result": "ok"})

    await store.append_checkpoint(session.id, checkpoint, "sebastian")

    checkpoints = await store.get_checkpoints(session.id, task.id, "sebastian")
    assert len(checkpoints) == 1
    assert checkpoints[0].step == 1


@pytest.mark.asyncio
async def test_list_tasks(store: SessionStore) -> None:
    session = Session(
        agent_type="sebastian",
        title="Multi task",
    )
    await store.create_session(session)
    task_one = Task(session_id=session.id, goal="Task A")
    task_two = Task(session_id=session.id, goal="Task B")

    await store.create_task(task_one, "sebastian")
    await store.create_task(task_two, "sebastian")

    tasks = await store.list_tasks(session.id, "sebastian")
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_session_store_uses_agent_type(store: SessionStore) -> None:
    session = Session(agent_type="stock", title="test session")

    await store.create_session(session)
    await store.append_message(session.id, "user", "hello", agent_type="stock")

    retrieved = await store.get_session(session.id, agent_type="stock")
    messages = await store.get_messages(session.id, agent_type="stock")

    assert retrieved is not None
    assert retrieved.agent_type == "stock"
    assert messages[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_get_session_for_agent_type_resolves_session(
    store: SessionStore,
) -> None:
    session = Session(agent_type="stock", title="worker session")

    await store.create_session(session)

    resolved = await store.get_session_for_agent_type(session.id, "stock")

    assert resolved is not None
    assert resolved.agent_type == "stock"


@pytest.mark.asyncio
async def test_task_operations_use_agent_type_path(store: SessionStore) -> None:
    session = Session(agent_type="stock", title="worker tasks")
    await store.create_session(session)

    task = Task(session_id=session.id, goal="Research")
    await store.create_task(task, "stock")
    await store.update_task_status(session.id, task.id, TaskStatus.RUNNING, "stock")

    loaded = await store.get_task(session.id, task.id, "stock")
    tasks = await store.list_tasks(session.id, "stock")

    assert loaded is not None
    assert loaded.status == TaskStatus.RUNNING
    assert [item.id for item in tasks] == [task.id]

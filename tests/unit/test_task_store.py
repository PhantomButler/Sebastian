from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.types import Checkpoint, Task, TaskStatus
from sebastian.store.database import Base
from sebastian.store.task_store import TaskStore


@pytest_asyncio.fixture
async def session():
    """Create an in-memory SQLite session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_get_task(session) -> None:
    """Test creating and retrieving a task."""
    store = TaskStore(session)
    task = Task(goal="Write a haiku")
    created = await store.create(task)
    assert created.id == task.id

    fetched = await store.get(task.id)
    assert fetched is not None
    assert fetched.goal == "Write a haiku"


@pytest.mark.asyncio
async def test_list_tasks_empty(session) -> None:
    """Test listing tasks when none exist."""
    store = TaskStore(session)
    tasks = await store.list_tasks()
    assert tasks == []


@pytest.mark.asyncio
async def test_update_status(session) -> None:
    """Test updating task status."""
    store = TaskStore(session)
    task = Task(goal="Brew tea")
    await store.create(task)
    await store.update_status(task.id, TaskStatus.RUNNING)

    fetched = await store.get(task.id)
    assert fetched is not None
    assert fetched.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_add_and_get_checkpoints(session) -> None:
    """Test adding and retrieving checkpoints."""
    store = TaskStore(session)
    task = Task(goal="Analyze data")
    await store.create(task)

    cp = Checkpoint(task_id=task.id, step=1, data={"progress": 0.5})
    await store.add_checkpoint(cp)

    checkpoints = await store.get_checkpoints(task.id)
    assert len(checkpoints) == 1
    assert checkpoints[0].step == 1
    assert checkpoints[0].data["progress"] == 0.5

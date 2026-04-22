from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.types import Checkpoint, ResourceBudget, Session, Task, TaskStatus
from sebastian.store.session_store import SessionStore


@pytest.fixture
async def sqlite_session_factory():
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base, _apply_idempotent_migrations

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def store(sqlite_session_factory):
    return SessionStore(db_factory=sqlite_session_factory)


@pytest.fixture
async def session_in_db(store):
    s = Session(agent_type="sebastian", title="Test")
    await store.create_session(s)
    return s


def _make_task(session_id: str, agent_type: str = "sebastian") -> Task:
    return Task(
        session_id=session_id,
        goal="do something",
        status=TaskStatus.RUNNING,
        assigned_agent=agent_type,
        resource_budget=ResourceBudget(),
    )


@pytest.mark.asyncio
async def test_create_and_get_task(store, session_in_db):
    task = _make_task(session_in_db.id)
    await store.create_task(task, agent_type="sebastian")
    loaded = await store.get_task(session_in_db.id, task.id, "sebastian")
    assert loaded is not None
    assert loaded.id == task.id
    assert loaded.goal == "do something"
    assert loaded.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_list_tasks_session_scoped(store, session_in_db):
    t1 = _make_task(session_in_db.id)
    t2 = _make_task(session_in_db.id)
    await store.create_task(t1, agent_type="sebastian")
    await store.create_task(t2, agent_type="sebastian")
    tasks = await store.list_tasks(session_in_db.id, "sebastian")
    ids = {t.id for t in tasks}
    assert t1.id in ids
    assert t2.id in ids


@pytest.mark.asyncio
async def test_update_task_status_to_completed(store, session_in_db):
    task = _make_task(session_in_db.id)
    await store.create_task(task, agent_type="sebastian")
    await store.update_task_status(session_in_db.id, task.id, TaskStatus.COMPLETED, "sebastian")
    loaded = await store.get_task(session_in_db.id, task.id, "sebastian")
    assert loaded.status == TaskStatus.COMPLETED
    assert loaded.completed_at is not None


@pytest.mark.asyncio
async def test_task_count_refresh(store, session_in_db):
    t = _make_task(session_in_db.id)
    await store.create_task(t, agent_type="sebastian")
    session = await store.get_session(session_in_db.id, "sebastian")
    assert session.task_count == 1
    assert session.active_task_count == 1

    await store.update_task_status(session_in_db.id, t.id, TaskStatus.COMPLETED, "sebastian")
    session = await store.get_session(session_in_db.id, "sebastian")
    assert session.task_count == 1
    assert session.active_task_count == 0


@pytest.mark.asyncio
async def test_append_and_get_checkpoints(store, session_in_db):
    task = _make_task(session_in_db.id)
    await store.create_task(task, agent_type="sebastian")
    cp = Checkpoint(task_id=task.id, step=1, data={"progress": 50})
    await store.append_checkpoint(session_in_db.id, cp, "sebastian")
    checkpoints = await store.get_checkpoints(session_in_db.id, task.id, "sebastian")
    assert len(checkpoints) == 1
    assert checkpoints[0].step == 1
    assert checkpoints[0].data == {"progress": 50}


@pytest.mark.asyncio
async def test_update_status_nonexistent_task_raises(store, session_in_db):
    """update_task_status 传入不存在的 task_id 应抛出 ValueError。

    D2: 当前实现静默 return，CLAUDE.md 要求对可能失败的操作抛出具体异常。
    """
    with pytest.raises(ValueError, match="Task not found"):
        await store.update_task_status(
            session_in_db.id, "nonexistent_task_id", TaskStatus.COMPLETED, "sebastian"
        )

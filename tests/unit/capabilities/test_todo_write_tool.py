from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.tool_context import _current_tool_ctx
from sebastian.core.types import TodoStatus
from sebastian.permissions.types import ToolCallContext
from sebastian.store.todo_store import TodoStore


@pytest.fixture
async def db_factory():
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
def patched_state(db_factory):
    store = TodoStore(db_factory=db_factory)

    fake_state = MagicMock()
    fake_state.todo_store = store
    fake_state.event_bus = MagicMock()
    fake_state.event_bus.publish = AsyncMock()

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        yield fake_state, store


@pytest.fixture
def set_ctx():
    tokens = []

    def _set(session_id: str = "s1", agent_type: str = "sebastian") -> None:
        ctx = ToolCallContext(
            task_goal="t",
            session_id=session_id,
            task_id=None,
            agent_type=agent_type,
        )
        tokens.append(_current_tool_ctx.set(ctx))

    yield _set
    for tok in tokens:
        try:
            _current_tool_ctx.reset(tok)
        except ValueError:
            pass


@pytest.mark.asyncio
async def test_write_persists_todos(patched_state, set_ctx) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")

    from sebastian.capabilities.tools.todo_write import todo_write

    result = await todo_write(
        todos=[
            {"content": "a", "activeForm": "doing a", "status": "in_progress"},
            {"content": "b", "activeForm": "doing b", "status": "pending"},
        ],
    )

    assert result.ok is True
    loaded = await store.read("sebastian", "s1")
    assert len(loaded) == 2
    assert loaded[0].content == "a"
    assert loaded[0].status == TodoStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_write_overwrites(patched_state, set_ctx) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")
    from sebastian.capabilities.tools.todo_write import todo_write

    await todo_write(todos=[{"content": "old", "activeForm": "old", "status": "pending"}])
    result = await todo_write(
        todos=[
            {"content": "new1", "activeForm": "new1", "status": "in_progress"},
            {"content": "new2", "activeForm": "new2", "status": "pending"},
        ],
    )

    assert result.ok is True
    assert result.output["old_count"] == 1
    assert result.output["new_count"] == 2
    loaded = await store.read("sebastian", "s1")
    assert [i.content for i in loaded] == ["new1", "new2"]


@pytest.mark.asyncio
async def test_invalid_status_returns_error(patched_state, set_ctx) -> None:
    set_ctx()
    from sebastian.capabilities.tools.todo_write import todo_write

    result = await todo_write(
        todos=[{"content": "x", "activeForm": "x", "status": "not_a_status"}],
    )
    assert result.ok is False
    assert "status" in result.error.lower()


@pytest.mark.asyncio
async def test_empty_content_returns_error(patched_state, set_ctx) -> None:
    set_ctx()
    from sebastian.capabilities.tools.todo_write import todo_write

    result = await todo_write(
        todos=[{"content": "", "activeForm": "x", "status": "pending"}],
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_missing_context_returns_error(patched_state) -> None:
    from sebastian.capabilities.tools.todo_write import todo_write

    result = await todo_write(todos=[])
    assert result.ok is False
    assert "context" in result.error.lower()


@pytest.mark.asyncio
async def test_publishes_event(patched_state, set_ctx) -> None:
    fake_state, _ = patched_state
    set_ctx("s1", "sebastian")
    from sebastian.capabilities.tools.todo_write import todo_write

    await todo_write(
        todos=[{"content": "x", "activeForm": "x", "status": "pending"}],
    )

    assert fake_state.event_bus.publish.await_count == 1
    published = fake_state.event_bus.publish.await_args.args[0]
    assert published.type.value == "todo.updated"
    assert published.data["session_id"] == "s1"
    assert published.data["agent_type"] == "sebastian"
    assert published.data["count"] == 1

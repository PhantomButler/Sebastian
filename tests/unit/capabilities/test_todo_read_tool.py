from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.tool_context import _current_tool_ctx
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
async def test_todo_read_returns_current_todos(patched_state, set_ctx) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")

    from sebastian.capabilities.tools.todo_write import todo_write

    await todo_write(
        todos=[
            {"content": "first task", "activeForm": "doing first", "status": "in_progress"},
            {"content": "second task", "activeForm": "doing second", "status": "pending"},
        ],
    )

    from sebastian.capabilities.tools.todo_read import todo_read

    result = await todo_read()

    assert result.ok is True
    assert result.output["count"] == 2
    assert result.output["session_id"] == "s1"
    todos = result.output["todos"]
    assert len(todos) == 2
    assert todos[0]["content"] == "first task"
    assert "activeForm" in todos[0]
    assert "status" in todos[0]
    assert todos[1]["content"] == "second task"
    assert "first task" in result.display


@pytest.mark.asyncio
async def test_todo_read_empty_returns_empty_array(patched_state, set_ctx) -> None:
    set_ctx("s1", "sebastian")

    from sebastian.capabilities.tools.todo_read import todo_read

    result = await todo_read()

    assert result.ok is True
    assert result.output["todos"] == []
    assert result.output["count"] == 0
    assert "没有待办" in result.display


@pytest.mark.asyncio
async def test_todo_read_without_session_context_returns_error(patched_state) -> None:
    from sebastian.capabilities.tools.todo_read import todo_read

    result = await todo_read()

    assert result.ok is False
    assert "context" in result.error.lower()

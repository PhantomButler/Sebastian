from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.types import TodoItem, TodoStatus
from sebastian.store.todo_store import TodoStore


@pytest.fixture
def store(tmp_path: Path) -> TodoStore:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    return TodoStore(sessions_dir)


@pytest.mark.asyncio
async def test_read_missing_returns_empty(store: TodoStore) -> None:
    todos = await store.read("sebastian", "session-abc")
    assert todos == []


@pytest.mark.asyncio
async def test_write_then_read_roundtrip(store: TodoStore) -> None:
    items = [
        TodoItem(content="step 1", active_form="doing step 1", status=TodoStatus.IN_PROGRESS),
        TodoItem(content="step 2", active_form="doing step 2", status=TodoStatus.PENDING),
    ]
    await store.write("sebastian", "session-abc", items)

    loaded = await store.read("sebastian", "session-abc")
    assert len(loaded) == 2
    assert loaded[0].content == "step 1"
    assert loaded[0].status == TodoStatus.IN_PROGRESS
    assert loaded[1].content == "step 2"
    assert loaded[1].status == TodoStatus.PENDING


@pytest.mark.asyncio
async def test_write_overwrites_previous(store: TodoStore) -> None:
    first = [TodoItem(content="old", active_form="old", status=TodoStatus.PENDING)]
    await store.write("sebastian", "sess-1", first)

    second = [
        TodoItem(content="new a", active_form="new a", status=TodoStatus.IN_PROGRESS),
        TodoItem(content="new b", active_form="new b", status=TodoStatus.PENDING),
    ]
    await store.write("sebastian", "sess-1", second)

    loaded = await store.read("sebastian", "sess-1")
    assert [i.content for i in loaded] == ["new a", "new b"]


@pytest.mark.asyncio
async def test_agent_type_isolation(store: TodoStore) -> None:
    await store.write(
        "sebastian", "same-id",
        [TodoItem(content="main", active_form="main", status=TodoStatus.PENDING)],
    )
    await store.write(
        "code", "same-id",
        [TodoItem(content="sub", active_form="sub", status=TodoStatus.PENDING)],
    )

    main = await store.read("sebastian", "same-id")
    sub = await store.read("code", "same-id")
    assert main[0].content == "main"
    assert sub[0].content == "sub"


@pytest.mark.asyncio
async def test_write_creates_parent_directories(store: TodoStore, tmp_path: Path) -> None:
    await store.write(
        "sebastian", "brand-new-session",
        [TodoItem(content="x", active_form="x", status=TodoStatus.PENDING)],
    )
    expected = tmp_path / "sessions" / "sebastian" / "brand-new-session" / "todos.json"
    assert expected.exists()

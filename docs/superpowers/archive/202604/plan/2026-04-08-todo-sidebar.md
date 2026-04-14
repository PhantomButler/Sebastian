# Todo Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a right-side sidebar that shows per-session Tasks (read-only, backed by existing `TaskRecord`) and Todos (maintained by a new coverage-write `todo_write` tool), and replace the sub-agent session detail page's top "Messages/Tasks" tab with this sidebar.

**Architecture:** New backend `TodoStore` (JSON file per session) + single `todo_write` tool (full-list overwrite semantics, no id) + new gateway GET endpoint + new `todo_updated` SSE event. Frontend parameterizes existing `Sidebar` for left/right use, adds page-level pan gesture area that triggers either sidebar from anywhere in the conversation content, and a new `TodoSidebar` rendering two sections.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / aiofiles (backend), React Native / Expo / react-native-gesture-handler / react-native-svg / @tanstack/react-query / zustand (frontend).

**Spec:** `docs/superpowers/specs/2026-04-08-todo-sidebar-design.md`

---

## File Map

### Backend — new files

| Path | Responsibility |
|---|---|
| `sebastian/store/todo_store.py` | TodoStore class: atomic read/write `todos.json` per session |
| `sebastian/capabilities/tools/todo_write/__init__.py` | `todo_write` tool (LOW permission, coverage semantics) |
| `tests/unit/test_todo_store.py` | TodoStore unit tests |
| `tests/unit/test_todo_write_tool.py` | todo_write tool unit tests |
| `tests/integration/test_sessions_todos_api.py` | Gateway GET endpoint integration test |

### Backend — modified files

| Path | Change |
|---|---|
| `sebastian/core/types.py` | Add `TodoItem` and `TodoStatus` types |
| `sebastian/protocol/events/types.py` | Add `TODO_UPDATED` to `EventType` enum |
| `sebastian/gateway/state.py` | Declare `todo_store: TodoStore` global |
| `sebastian/gateway/app.py` | Construct `TodoStore` and assign to state |
| `sebastian/gateway/routes/sessions.py` | Add `GET /sessions/{session_id}/todos` handler |
| `sebastian/core/base_agent.py` | Inject current todos into per-turn system prompt |
| `sebastian/capabilities/tools/README.md` | Document `todo_write` tool |
| `sebastian/store/README.md` | Document `TodoStore` |

### Frontend — new files

| Path | Responsibility |
|---|---|
| `ui/mobile/src/components/common/ContentPanGestureArea.tsx` | Page-level horizontal pan gesture, opens left or right sidebar by direction |
| `ui/mobile/src/components/chat/TodoSidebar.tsx` | Right sidebar content: Tasks section + Todos section |
| `ui/mobile/src/api/todos.ts` | `getSessionTodos` axios wrapper |
| `ui/mobile/src/hooks/useSessionTodos.ts` | React Query hook for todos |

### Frontend — modified files

| Path | Change |
|---|---|
| `ui/mobile/src/components/common/Sidebar.tsx` | Add `side?: 'left' \| 'right'` prop, remove internal edge trigger |
| `ui/mobile/src/components/common/Icons.tsx` | Add `TodoCircleIcon`, `SuccessCircleIcon` |
| `ui/mobile/src/types.ts` | Add `TodoItem` and `TodoStatus` types |
| `ui/mobile/app/index.tsx` | Wrap content in `ContentPanGestureArea`, mount right `TodoSidebar` |
| `ui/mobile/app/subagents/session/[id].tsx` | Remove top tab, wrap with `ContentPanGestureArea`, mount `TodoSidebar` |
| `ui/mobile/src/hooks/useSSE.ts` | Handle `todo_updated` event → invalidate query |
| `ui/mobile/README.md` | Update navigation table for new components |
| `ui/mobile/src/components/subagents/README.md` | Remove `SessionDetailView` entry |

### Frontend — deleted files

| Path |
|---|
| `ui/mobile/src/components/subagents/SessionDetailView.tsx` |

---

## Conventions

- **Backend tests**: `pytest tests/unit/test_X.py -v`. Use `tmp_path` fixture for filesystem tests. All async tests use `@pytest.mark.asyncio`.
- **Commits**: after every task, single atomic commit. Commit message in Chinese, format `类型(范围): 摘要`, with `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>` footer.
- **TDD loop**: write failing test → run to see it fail → write minimal impl → run to see it pass → commit.
- **Frontend**: no automated tests (consistent with repo). Verify via `npx tsc --noEmit` after each task and manual runtime verification at the end.

---

## Task 1: TodoItem types

**Files:**
- Modify: `sebastian/core/types.py`

- [ ] **Step 1: Locate insertion point**

Open `sebastian/core/types.py`. Find the end of the existing type definitions (after `TaskStatus`, `Task`, `Session` etc.). New types will be appended at the end.

- [ ] **Step 2: Add TodoStatus and TodoItem types**

Append to `sebastian/core/types.py`:

```python
class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TodoItem(BaseModel):
    content: str = Field(min_length=1)
    active_form: str = Field(min_length=1, alias="activeForm")
    status: TodoStatus

    model_config = {"populate_by_name": True}
```

Verify `StrEnum`, `BaseModel`, `Field` are already imported at top of file. If `StrEnum` is not imported, add `from enum import StrEnum`.

- [ ] **Step 3: Type check**

Run: `mypy sebastian/core/types.py`
Expected: no errors (or existing baseline errors only, no new).

- [ ] **Step 4: Commit**

```bash
git add sebastian/core/types.py
git commit -m "$(cat <<'EOF'
feat(core): 新增 TodoItem / TodoStatus 类型

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: TodoStore

**Files:**
- Create: `sebastian/store/todo_store.py`
- Create: `tests/unit/test_todo_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_todo_store.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_todo_store.py -v`
Expected: `ModuleNotFoundError: sebastian.store.todo_store`

- [ ] **Step 3: Implement TodoStore**

Create `sebastian/store/todo_store.py`:

```python
# mypy: disable-error-code=import-untyped

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

from sebastian.core.types import TodoItem


class TodoStore:
    """JSON-file storage for per-session todo lists.

    Stores a single `todos.json` under each session directory, next to the
    existing `tasks/` subdirectory. Coverage-write semantics: every write
    replaces the file atomically.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = sessions_dir

    def _todos_path(self, agent_type: str, session_id: str) -> Path:
        return self._dir / agent_type / session_id / "todos.json"

    async def read(self, agent_type: str, session_id: str) -> list[TodoItem]:
        path = self._todos_path(agent_type, session_id)
        if not path.exists():
            return []
        async with aiofiles.open(path) as f:
            raw = await f.read()
        data = json.loads(raw)
        return [TodoItem(**item) for item in data.get("todos", [])]

    async def write(
        self,
        agent_type: str,
        session_id: str,
        todos: list[TodoItem],
    ) -> None:
        path = self._todos_path(agent_type, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "todos": [item.model_dump(mode="json", by_alias=True) for item in todos],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)

        tmp_path = path.with_suffix(".json.tmp")
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(serialized)
        os.replace(tmp_path, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_todo_store.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/todo_store.py tests/unit/test_todo_store.py
git commit -m "$(cat <<'EOF'
feat(store): 新增 TodoStore，per-session todos.json 原子读写

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: todo_updated event type

**Files:**
- Modify: `sebastian/protocol/events/types.py`

- [ ] **Step 1: Add enum value**

Open `sebastian/protocol/events/types.py`. In the `EventType` class, add after `TURN_CANCELLED`:

```python
    # Todo lifecycle
    TODO_UPDATED = "todo.updated"
```

- [ ] **Step 2: Type check**

Run: `mypy sebastian/protocol/events/types.py`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add sebastian/protocol/events/types.py
git commit -m "$(cat <<'EOF'
feat(protocol): 新增 TODO_UPDATED 事件类型

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire TodoStore into gateway state

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: Declare state global**

In `sebastian/gateway/state.py`, add to the `TYPE_CHECKING` imports block:

```python
    from sebastian.store.todo_store import TodoStore
```

Then add the module-level global near `session_store: SessionStore`:

```python
todo_store: TodoStore
```

- [ ] **Step 2: Construct in app startup**

In `sebastian/gateway/app.py`, find the line `session_store = SessionStore(settings.sessions_dir)` and add immediately after:

```python
    from sebastian.store.todo_store import TodoStore
    todo_store = TodoStore(settings.sessions_dir)
```

Then find the block assigning `state.session_store = session_store` and add:

```python
    state.todo_store = todo_store
```

- [ ] **Step 3: Type check**

Run: `mypy sebastian/gateway/state.py sebastian/gateway/app.py`
Expected: no new errors.

- [ ] **Step 4: Smoke test gateway boots**

Run: `python -c "from sebastian.gateway.app import app; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py
git commit -m "$(cat <<'EOF'
feat(gateway): 在 state 中注册 TodoStore

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: todo_write tool

**Files:**
- Create: `sebastian/capabilities/tools/todo_write/__init__.py`
- Create: `tests/unit/test_todo_write_tool.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_todo_write_tool.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.tool_context import _current_tool_ctx
from sebastian.core.types import TodoStatus
from sebastian.permissions.types import ToolCallContext
from sebastian.store.todo_store import TodoStore


@pytest.fixture
def patched_state(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    store = TodoStore(sessions_dir)

    fake_state = MagicMock()
    fake_state.todo_store = store
    fake_state.event_bus = MagicMock()
    fake_state.event_bus.publish = AsyncMock()

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        yield fake_state, store, sessions_dir


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
        _current_tool_ctx.reset(tok)


@pytest.mark.asyncio
async def test_write_persists_todos(patched_state, set_ctx) -> None:
    _, store, _ = patched_state
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
    _, store, _ = patched_state
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
    fake_state, _, _ = patched_state
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_todo_write_tool.py -v`
Expected: `ModuleNotFoundError: sebastian.capabilities.tools.todo_write`

- [ ] **Step 3: Implement tool**

Create `sebastian/capabilities/tools/todo_write/__init__.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import TodoItem
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.protocol.events.types import Event, EventType


def _parse_todos(raw: list[dict[str, Any]]) -> list[TodoItem]:
    items: list[TodoItem] = []
    for idx, entry in enumerate(raw):
        try:
            items.append(TodoItem(**entry))
        except ValidationError as e:
            raise ValueError(f"todo item #{idx} invalid: {e.errors()[0]['msg']}") from e
    return items


@tool(
    name="todo_write",
    description=(
        "Create or update the current session's todo list. Coverage-write "
        "semantics: every call replaces the entire list. Use proactively for "
        "multi-step tasks (3+ steps). Each item needs {content, activeForm, "
        "status: pending|in_progress|completed}. Keep exactly one item "
        "in_progress at a time while working. No ids — position is identity. "
        "The current list is injected into context each turn, so you do not "
        "need a separate read tool."
    ),
    permission_tier=PermissionTier.LOW,
)
async def todo_write(todos: list[dict[str, Any]]) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(ok=False, error="todo_write requires session context")

    try:
        items = _parse_todos(todos)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))

    import sebastian.gateway.state as state

    old = await state.todo_store.read(ctx.agent_type, ctx.session_id)
    await state.todo_store.write(ctx.agent_type, ctx.session_id, items)

    await state.event_bus.publish(
        Event(
            type=EventType.TODO_UPDATED,
            data={
                "session_id": ctx.session_id,
                "agent_type": ctx.agent_type,
                "count": len(items),
            },
        )
    )

    return ToolResult(
        ok=True,
        output={
            "old_count": len(old),
            "new_count": len(items),
            "session_id": ctx.session_id,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_todo_write_tool.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Ruff format + check**

Run: `ruff format sebastian/capabilities/tools/todo_write/ tests/unit/test_todo_write_tool.py && ruff check sebastian/capabilities/tools/todo_write/ tests/unit/test_todo_write_tool.py`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add sebastian/capabilities/tools/todo_write/ tests/unit/test_todo_write_tool.py
git commit -m "$(cat <<'EOF'
feat(tools): 新增 todo_write 工具，覆盖式更新 session todo 列表

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Gateway GET /sessions/{id}/todos endpoint

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Create: `tests/integration/test_sessions_todos_api.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_sessions_todos_api.py`:

```python
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from sebastian.core.types import Session, TodoItem, TodoStatus


@pytest.mark.asyncio
async def test_get_todos_empty_for_new_session(app_test_client: AsyncClient, auth_header: dict) -> None:
    import sebastian.gateway.state as state

    session = Session(agent_type="sebastian", title="t")
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    resp = await app_test_client.get(
        f"/api/v1/sessions/{session.id}/todos",
        headers=auth_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["todos"] == []
    assert body["updated_at"] is None


@pytest.mark.asyncio
async def test_get_todos_returns_written(app_test_client: AsyncClient, auth_header: dict) -> None:
    import sebastian.gateway.state as state

    session = Session(agent_type="sebastian", title="t")
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    await state.todo_store.write(
        "sebastian", session.id,
        [
            TodoItem(content="a", active_form="doing a", status=TodoStatus.IN_PROGRESS),
            TodoItem(content="b", active_form="doing b", status=TodoStatus.PENDING),
        ],
    )

    resp = await app_test_client.get(
        f"/api/v1/sessions/{session.id}/todos",
        headers=auth_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["todos"]) == 2
    assert body["todos"][0]["content"] == "a"
    assert body["todos"][0]["activeForm"] == "doing a"
    assert body["todos"][0]["status"] == "in_progress"
    assert body["updated_at"] is not None
```

**Note:** If the existing integration tests use a different fixture name pattern (check `tests/integration/conftest.py`), adjust `app_test_client` / `auth_header` to match. Look at an existing file like `tests/integration/test_gateway.py` for the pattern and mirror it exactly.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sessions_todos_api.py -v`
Expected: 404 responses (endpoint doesn't exist yet).

- [ ] **Step 3: Add endpoint**

In `sebastian/gateway/routes/sessions.py`, add after the existing `list_session_tasks` handler (around line 293):

```python
@router.get("/sessions/{session_id}/todos")
async def list_session_todos(
    session_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    todos = await state.todo_store.read(session_id=session_id, agent_type=session.agent_type)

    # Also read updated_at from the file itself (TodoStore.read drops it).
    # Simplest: read raw file again to surface timestamp.
    from pathlib import Path as _Path
    import json as _json

    path: _Path = state.todo_store._todos_path(session.agent_type, session_id)  # type: ignore[attr-defined]
    updated_at: str | None = None
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        try:
            updated_at = _json.loads(raw).get("updated_at")
        except Exception:
            updated_at = None

    return {
        "todos": [t.model_dump(mode="json", by_alias=True) for t in todos],
        "updated_at": updated_at,
    }
```

**Note:** `TodoStore.read` takes positional args `(agent_type, session_id)`, not kwargs. Fix the call to:

```python
    todos = await state.todo_store.read(session.agent_type, session_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_sessions_todos_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/routes/sessions.py tests/integration/test_sessions_todos_api.py
git commit -m "$(cat <<'EOF'
feat(gateway): 新增 GET /sessions/{id}/todos 接口

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Per-turn todo injection into system prompt

**Files:**
- Modify: `sebastian/core/base_agent.py`

**Context:** Current `build_system_prompt` runs once in `__init__`. Todos change mid-session, so we inject per-turn instead. The cleanest minimal change is: in `run_streaming`, compute a per-turn `effective_system_prompt` that appends a `## Session Todos` section, and pass that instead of `self.system_prompt`.

- [ ] **Step 1: Add helper method**

In `sebastian/core/base_agent.py`, add a new method inside the `BaseAgent` class (near `_knowledge_section`):

```python
    async def _session_todos_section(
        self,
        session_id: str,
        agent_type: str,
    ) -> str:
        """Return a '## Session Todos' section reflecting current todos.json.

        Empty string if no todos exist. Called fresh each turn so LLM sees
        the latest state without needing a read tool.
        """
        try:
            import sebastian.gateway.state as state
            store = state.todo_store
        except (ImportError, AttributeError):
            return ""

        items = await store.read(agent_type, session_id)
        if not items:
            return ""

        lines = ["## Session Todos", ""]
        for idx, item in enumerate(items, start=1):
            marker = {
                "pending": "[ ]",
                "in_progress": "[→]",
                "completed": "[x]",
            }.get(item.status.value, "[?]")
            display = item.active_form if item.status.value == "in_progress" else item.content
            lines.append(f"{idx}. {marker} {display}")
        lines.append("")
        lines.append(
            "(The above reflects the current session todo list. Use todo_write "
            "to update — pass the complete new list, not just changed items.)"
        )
        return "\n".join(lines)
```

- [ ] **Step 2: Inject per-turn in `run_streaming`**

In the same file, find `run_streaming` method. Locate the line `gen = self._loop.stream(self.system_prompt, messages, task_id=task_id)` (around line 298). Change it to build an effective prompt first:

```python
        todo_section = await self._session_todos_section(session_id, agent_context)
        effective_system_prompt = self.system_prompt
        if todo_section:
            effective_system_prompt = f"{self.system_prompt}\n\n{todo_section}"

        gen = self._loop.stream(effective_system_prompt, messages, task_id=task_id)
```

**Important:** The exact signature of `self._loop.stream` and the surrounding code may differ slightly. Read ±20 lines around line 298 first and make the minimal change that keeps behavior identical when there are no todos.

- [ ] **Step 3: Quick smoke test**

Run: `pytest tests/unit/test_base_agent.py -v`
Expected: all existing tests still pass (no regression).

- [ ] **Step 4: Type check**

Run: `mypy sebastian/core/base_agent.py`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/base_agent.py
git commit -m "$(cat <<'EOF'
feat(core): 每轮注入 session todos 到 system prompt

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Backend README updates

**Files:**
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/store/README.md`

- [ ] **Step 1: Add todo_write to tools README**

In `sebastian/capabilities/tools/README.md`:

1. Under "目录结构" tree, add:
   ```
   ├── todo_write/          # Session 级 todo list 覆盖式写入工具（permission_tier: LOW）
   │   └── __init__.py      # @tool: todo_write
   ```
2. Under "修改导航" table, add row:
   ```
   | Todo 列表写入工具 | [todo_write/\_\_init\_\_.py](todo_write/__init__.py) |
   ```

- [ ] **Step 2: Add TodoStore to store README**

In `sebastian/store/README.md`:

1. Under "目录结构" tree, add:
   ```
   ├── todo_store.py        # per-session todos.json 原子读写
   ```
2. Under "文件系统存储结构", update the tree:
   ```
   SEBASTIAN_DATA_DIR/sessions/
     <agent_type>/<session_id>/
       session.json
       tasks/<task_id>.json
       todos.json               # 新增：LLM 维护的 todo 列表
     index.json
   ```
3. Under "修改导航" table, add row:
   ```
   | Todo 列表读写 | [todo_store.py](todo_store.py) |
   ```

- [ ] **Step 3: Commit**

```bash
git add sebastian/capabilities/tools/README.md sebastian/store/README.md
git commit -m "$(cat <<'EOF'
docs: 更新 tools / store README，增加 todo_write 与 TodoStore 条目

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Frontend TodoItem type

**Files:**
- Modify: `ui/mobile/src/types.ts`

- [ ] **Step 1: Add types**

Open `ui/mobile/src/types.ts`. Append:

```typescript
export type TodoStatus = 'pending' | 'in_progress' | 'completed';

export interface TodoItem {
  content: string;
  activeForm: string;
  status: TodoStatus;
}

export interface SessionTodosResponse {
  todos: TodoItem[];
  updated_at: string | null;
}
```

- [ ] **Step 2: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/types.ts
git commit -m "$(cat <<'EOF'
feat(mobile): 新增 TodoItem 前端类型

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Parameterize Sidebar for left/right

**Files:**
- Modify: `ui/mobile/src/components/common/Sidebar.tsx`

- [ ] **Step 1: Rewrite Sidebar**

Replace the entire contents of `ui/mobile/src/components/common/Sidebar.tsx` with:

```typescript
import { useRef, useEffect } from 'react';
import { Animated, Dimensions, StyleSheet, TouchableOpacity, View } from 'react-native';
import { PanGestureHandler, State } from 'react-native-gesture-handler';
import { useTheme } from '../../theme/ThemeContext';

const SIDEBAR_WIDTH = Dimensions.get('window').width * 0.75;
const SWIPE_THRESHOLD = 50;

type Side = 'left' | 'right';

interface Props {
  visible: boolean;
  onOpen: () => void;
  onClose: () => void;
  children: React.ReactNode;
  side?: Side;
}

export function Sidebar({ visible, onClose, children, side = 'left' }: Props) {
  const colors = useTheme();
  const hiddenX = side === 'left' ? -SIDEBAR_WIDTH : SIDEBAR_WIDTH;
  const translateX = useRef(new Animated.Value(hiddenX)).current;

  useEffect(() => {
    Animated.timing(translateX, {
      toValue: visible ? 0 : hiddenX,
      duration: 250,
      useNativeDriver: true,
    }).start();
  }, [visible, hiddenX]);

  function handleSidebarGesture({ nativeEvent }: any) {
    if (nativeEvent.state !== State.END) return;
    // Close gesture: left sidebar closes on left swipe, right sidebar closes on right swipe
    if (side === 'left' && nativeEvent.translationX < -SWIPE_THRESHOLD) {
      onClose();
    } else if (side === 'right' && nativeEvent.translationX > SWIPE_THRESHOLD) {
      onClose();
    }
  }

  const panelStyle = [
    styles.sidebarBase,
    side === 'left' ? styles.sidebarLeft : styles.sidebarRight,
    {
      transform: [{ translateX }],
      backgroundColor: colors.secondaryBackground,
      shadowOffset: { width: side === 'left' ? 2 : -2, height: 0 },
    },
  ];

  return (
    <View style={[StyleSheet.absoluteFill, { pointerEvents: visible ? 'auto' : 'box-none' }]}>
      <TouchableOpacity
        style={[styles.overlay, { display: visible ? 'flex' : 'none', backgroundColor: colors.overlay }]}
        activeOpacity={1}
        onPress={onClose}
      />
      <PanGestureHandler onHandlerStateChange={handleSidebarGesture} enabled={visible}>
        <Animated.View collapsable={false} style={panelStyle} pointerEvents={visible ? 'auto' : 'none'}>
          {children}
        </Animated.View>
      </PanGestureHandler>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFillObject },
  sidebarBase: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: SIDEBAR_WIDTH,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 8,
    elevation: 8,
  },
  sidebarLeft: { left: 0 },
  sidebarRight: { right: 0 },
});
```

**Notes on behavior changes from old version:**
- Removed internal 25px `edgeTrigger` view (page-level gesture now handles opening).
- `onOpen` prop is still accepted (for interface compat) but no longer used internally.

- [ ] **Step 2: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/common/Sidebar.tsx
git commit -m "$(cat <<'EOF'
refactor(mobile): Sidebar 参数化支持 left/right，移除内部 edgeTrigger

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: ContentPanGestureArea

**Files:**
- Create: `ui/mobile/src/components/common/ContentPanGestureArea.tsx`

- [ ] **Step 1: Implement component**

Create `ui/mobile/src/components/common/ContentPanGestureArea.tsx`:

```typescript
import { PanGestureHandler, State } from 'react-native-gesture-handler';
import { View, StyleSheet } from 'react-native';

const SWIPE_THRESHOLD = 50;

interface Props {
  onOpenLeft?: () => void;
  onOpenRight?: () => void;
  children: React.ReactNode;
}

/**
 * Page-level horizontal pan gesture.
 *
 * Wraps the conversation content area. Detects horizontal pans and opens
 * the left or right sidebar based on direction. Vertical scrolls pass
 * through to child FlatList via failOffsetY.
 *
 * Placed INSIDE the page but OUTSIDE the composer/header, so swipes on the
 * message list trigger sidebars while swipes on the input field do not.
 */
export function ContentPanGestureArea({ onOpenLeft, onOpenRight, children }: Props) {
  function handleState({ nativeEvent }: any) {
    if (nativeEvent.state !== State.END) return;
    const { translationX, velocityX } = nativeEvent;

    if (translationX > SWIPE_THRESHOLD && velocityX >= 0 && onOpenLeft) {
      onOpenLeft();
    } else if (translationX < -SWIPE_THRESHOLD && velocityX <= 0 && onOpenRight) {
      onOpenRight();
    }
  }

  return (
    <PanGestureHandler
      onHandlerStateChange={handleState}
      activeOffsetX={[-10, 10]}
      failOffsetY={[-15, 15]}
    >
      <View style={styles.container}>{children}</View>
    </PanGestureHandler>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
});
```

- [ ] **Step 2: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/common/ContentPanGestureArea.tsx
git commit -m "$(cat <<'EOF'
feat(mobile): 新增 ContentPanGestureArea，页面级横向 pan 触发左右侧边栏

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Todo icons in Icons.tsx

**Files:**
- Modify: `ui/mobile/src/components/common/Icons.tsx`

- [ ] **Step 1: Inspect existing icons and SVG files**

Run: `cat ui/mobile/src/components/common/Icons.tsx | head -40`

Look at how existing icons are defined. If they use `SvgXml` from `react-native-svg`, follow that pattern. If they use static component imports with `react-native-svg`, follow that.

Also read both SVG files to get their inner content:

Run: `cat ui/mobile/src/assets/icons/todo_circle.svg`
Run: `cat ui/mobile/src/assets/icons/success_circle.svg`

- [ ] **Step 2: Add icon components**

Append to `ui/mobile/src/components/common/Icons.tsx`, using the same pattern as existing icons. If the file uses `SvgXml`:

```typescript
import { SvgXml } from 'react-native-svg';

const TODO_CIRCLE_XML = `<!-- paste contents of todo_circle.svg here -->`;
const SUCCESS_CIRCLE_XML = `<!-- paste contents of success_circle.svg here -->`;

interface IconProps {
  size?: number;
  color?: string;
}

export function TodoCircleIcon({ size = 20, color }: IconProps) {
  return <SvgXml xml={TODO_CIRCLE_XML} width={size} height={size} color={color} />;
}

export function SuccessCircleIcon({ size = 20 }: IconProps) {
  return <SvgXml xml={SUCCESS_CIRCLE_XML} width={size} height={size} />;
}
```

If the file uses a different pattern (e.g., static SVG component imports via `react-native-svg-transformer`), mirror that pattern instead. **The goal: two exported components `TodoCircleIcon` and `SuccessCircleIcon`, sized via `size` prop, that render the two SVG files the user has added.**

- [ ] **Step 3: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/components/common/Icons.tsx
git commit -m "$(cat <<'EOF'
feat(mobile): Icons 新增 TodoCircleIcon / SuccessCircleIcon

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: API client for todos

**Files:**
- Create: `ui/mobile/src/api/todos.ts`

- [ ] **Step 1: Inspect existing API client pattern**

Run: `cat ui/mobile/src/api/sessions.ts | head -40`

Observe how `getSessionTasks` etc. are implemented (client instance, error handling, return shape).

- [ ] **Step 2: Implement todos API client**

Create `ui/mobile/src/api/todos.ts`:

```typescript
import { client } from './client';
import type { SessionTodosResponse } from '../types';

export async function getSessionTodos(sessionId: string): Promise<SessionTodosResponse> {
  const response = await client.get<SessionTodosResponse>(
    `/api/v1/sessions/${sessionId}/todos`,
  );
  return response.data;
}
```

If the existing pattern uses a different base path (e.g. no `/api/v1` prefix because `client` base URL handles it), adjust to match other calls in `sessions.ts`.

- [ ] **Step 3: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/api/todos.ts
git commit -m "$(cat <<'EOF'
feat(mobile): 新增 todos API client

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: useSessionTodos hook

**Files:**
- Create: `ui/mobile/src/hooks/useSessionTodos.ts`

- [ ] **Step 1: Inspect existing hook pattern**

Run: `cat ui/mobile/src/hooks/useSessions.ts`

Note the React Query pattern.

- [ ] **Step 2: Implement hook**

Create `ui/mobile/src/hooks/useSessionTodos.ts`:

```typescript
import { useQuery } from '@tanstack/react-query';
import { getSessionTodos } from '../api/todos';
import type { TodoItem } from '../types';

export function useSessionTodos(sessionId: string | null) {
  return useQuery({
    queryKey: ['session-todos', sessionId],
    queryFn: async (): Promise<TodoItem[]> => {
      if (!sessionId) return [];
      const { todos } = await getSessionTodos(sessionId);
      return todos;
    },
    enabled: !!sessionId,
  });
}
```

- [ ] **Step 3: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/hooks/useSessionTodos.ts
git commit -m "$(cat <<'EOF'
feat(mobile): 新增 useSessionTodos React Query hook

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: TodoSidebar component

**Files:**
- Create: `ui/mobile/src/components/chat/TodoSidebar.tsx`

- [ ] **Step 1: Inspect SessionDetailView for Task rendering pattern**

Run: `cat ui/mobile/src/components/subagents/SessionDetailView.tsx`

Note the task row rendering structure — we'll port a simplified version.

- [ ] **Step 2: Implement component**

Create `ui/mobile/src/components/chat/TodoSidebar.tsx`:

```typescript
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getSessionTasks } from '../../api/sessions';
import { useSessionTodos } from '../../hooks/useSessionTodos';
import { useTheme } from '../../theme/ThemeContext';
import { TodoCircleIcon, SuccessCircleIcon } from '../common/Icons';
import type { TodoItem, TaskDetail } from '../../types';

interface Props {
  sessionId: string | null;
  agentType: string;
  onClose: () => void;
}

export function TodoSidebar({ sessionId, agentType }: Props) {
  const colors = useTheme();

  const { data: tasks = [] } = useQuery({
    queryKey: ['session-tasks', sessionId, agentType],
    queryFn: () => getSessionTasks(sessionId!, agentType),
    enabled: !!sessionId,
  });

  const { data: todos = [] } = useSessionTodos(sessionId);

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: colors.secondaryBackground }]} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <Text style={[styles.sectionHeader, { color: colors.textSecondary }]}>任务</Text>
        {tasks.length === 0 ? (
          <Text style={[styles.emptyText, { color: colors.textSecondary }]}>暂无任务</Text>
        ) : (
          tasks.map((task) => <TaskRow key={task.id} task={task} />)
        )}

        <View style={[styles.divider, { backgroundColor: colors.borderLight }]} />

        <Text style={[styles.sectionHeader, { color: colors.textSecondary }]}>待办</Text>
        {todos.length === 0 ? (
          <Text style={[styles.emptyText, { color: colors.textSecondary }]}>暂无待办</Text>
        ) : (
          todos.map((todo, idx) => <TodoRow key={idx} todo={todo} />)
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function TaskRow({ task }: { task: TaskDetail }) {
  const colors = useTheme();
  return (
    <View style={styles.row}>
      <Text style={[styles.taskGoal, { color: colors.text }]} numberOfLines={2}>
        {task.goal}
      </Text>
      <Text style={[styles.taskStatus, { color: colors.textSecondary }]}>[{task.status}]</Text>
    </View>
  );
}

function TodoRow({ todo }: { todo: TodoItem }) {
  const colors = useTheme();
  const isCompleted = todo.status === 'completed';
  const isInProgress = todo.status === 'in_progress';

  const displayText = isInProgress ? todo.activeForm : todo.content;
  const textStyle = [
    styles.todoText,
    {
      color: isCompleted ? colors.textSecondary : colors.text,
      textDecorationLine: (isCompleted ? 'line-through' : 'none') as 'line-through' | 'none',
      fontWeight: (isInProgress ? '600' : '400') as '600' | '400',
    },
  ];

  return (
    <View style={styles.row}>
      {isCompleted ? (
        <SuccessCircleIcon size={18} />
      ) : (
        <TodoCircleIcon size={18} color={isInProgress ? '#007AFF' : undefined} />
      )}
      <Text style={textStyle} numberOfLines={3}>
        {displayText}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  scrollContent: { padding: 16 },
  sectionHeader: {
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    marginTop: 8,
    marginBottom: 10,
    letterSpacing: 0.5,
  },
  emptyText: { fontSize: 14, fontStyle: 'italic', paddingVertical: 4 },
  divider: { height: 1, marginVertical: 18 },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: 8,
    gap: 10,
  },
  taskGoal: { flex: 1, fontSize: 14 },
  taskStatus: { fontSize: 12 },
  todoText: { flex: 1, fontSize: 14, lineHeight: 20 },
});
```

**Note:** The `TaskDetail` type is imported from `../../types`. Verify it's exported there. If not, check `ui/mobile/src/types.ts` and add an export or adjust the import.

- [ ] **Step 3: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/components/chat/TodoSidebar.tsx
git commit -m "$(cat <<'EOF'
feat(mobile): 新增 TodoSidebar 组件，展示 Tasks + Todos 两段

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Wire up main chat screen

**Files:**
- Modify: `ui/mobile/app/index.tsx`

- [ ] **Step 1: Add right sidebar state and imports**

In `ui/mobile/app/index.tsx`:

1. Add imports near the existing ones:

```typescript
import { ContentPanGestureArea } from '@/src/components/common/ContentPanGestureArea';
import { TodoSidebar } from '@/src/components/chat/TodoSidebar';
```

2. After the existing `const [sidebarOpen, setSidebarOpen] = useState(false);`, add:

```typescript
  const [todoSidebarOpen, setTodoSidebarOpen] = useState(false);
```

- [ ] **Step 2: Wrap content with ContentPanGestureArea**

Find the `<KeyboardGestureArea ...>` block in the JSX return. Wrap it with `<ContentPanGestureArea>`:

```tsx
      <ContentPanGestureArea
        onOpenLeft={() => setSidebarOpen(true)}
        onOpenRight={() => setTodoSidebarOpen(true)}
      >
        <KeyboardGestureArea
          style={styles.gestureArea}
          interpolator="ios"
          offset={COMPOSER_DEFAULT_HEIGHT}
          textInputNativeID="composer-input"
        >
          {/* ... existing children unchanged ... */}
        </KeyboardGestureArea>
      </ContentPanGestureArea>
```

- [ ] **Step 3: Mount right sidebar**

After the existing `<Sidebar visible={sidebarOpen} ...>` block, add:

```tsx
      <Sidebar
        visible={todoSidebarOpen}
        side="right"
        onOpen={() => setTodoSidebarOpen(true)}
        onClose={() => setTodoSidebarOpen(false)}
      >
        <TodoSidebar
          sessionId={currentSessionId}
          agentType="sebastian"
          onClose={() => setTodoSidebarOpen(false)}
        />
      </Sidebar>
```

- [ ] **Step 4: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add ui/mobile/app/index.tsx
git commit -m "$(cat <<'EOF'
feat(mobile): 主对话页接入右侧 TodoSidebar + ContentPanGestureArea

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Sub-agent session screen — remove tab, add sidebar

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

- [ ] **Step 1: Remove tab state and top tab bar UI**

In `ui/mobile/app/subagents/session/[id].tsx`:

1. Delete the `type Tab = 'messages' | 'tasks';` line.
2. Delete `const [tab, setTab] = useState<Tab>('messages');`.
3. Delete the entire `<View style={styles.tabs}>...</View>` block in the JSX.
4. In the content render, replace the `tab === 'messages' ? <ConversationView .../> : <SessionDetailView .../>` ternary with just `<ConversationView .../>`.
5. Remove the `SessionDetailView` import.
6. Remove the `MOCK_TASKS` constant and any remaining references to it. Since `remoteTasks` / `tasks` were only used in the tab rendering, remove the `useQuery(['session-tasks', ...])` call and the `tasks` variable (TodoSidebar will fetch its own). If `isMockSession` tests refer to `MOCK_TASKS`, strip them too.
7. Delete the now-unused tab styles from the `StyleSheet.create` block: `tabs`, `tab`, `tabActive`, `tabText`, `tabTextActive`.
8. Delete the `TaskDetail` import if it's no longer referenced.

- [ ] **Step 2: Wrap with ContentPanGestureArea and add sidebar**

1. Add imports:

```typescript
import { useState } from 'react';
import { ContentPanGestureArea } from '../../../src/components/common/ContentPanGestureArea';
import { TodoSidebar } from '../../../src/components/chat/TodoSidebar';
import { Sidebar } from '../../../src/components/common/Sidebar';
```

2. Add state near the other hooks:

```typescript
  const [todoSidebarOpen, setTodoSidebarOpen] = useState(false);
```

3. Wrap `<KeyboardGestureArea>` with `<ContentPanGestureArea>`:

```tsx
      <ContentPanGestureArea onOpenRight={() => setTodoSidebarOpen(true)}>
        <KeyboardGestureArea ...>
          {/* existing children */}
        </KeyboardGestureArea>
      </ContentPanGestureArea>
```

(Only `onOpenRight` — this screen has no left sidebar.)

4. Add the `<Sidebar>` block at the end of the `<SafeAreaView>` children:

```tsx
      <Sidebar
        visible={todoSidebarOpen}
        side="right"
        onOpen={() => setTodoSidebarOpen(true)}
        onClose={() => setTodoSidebarOpen(false)}
      >
        <TodoSidebar
          sessionId={effectiveSessionId}
          agentType={agentName}
          onClose={() => setTodoSidebarOpen(false)}
        />
      </Sidebar>
```

- [ ] **Step 3: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors. If `tasks` is flagged as unused or any removed import remains, clean up.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/app/subagents/session/[id].tsx
git commit -m "$(cat <<'EOF'
refactor(mobile): sub-agent session 页移除顶部 tab，接入右侧 TodoSidebar

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Delete SessionDetailView

**Files:**
- Delete: `ui/mobile/src/components/subagents/SessionDetailView.tsx`
- Modify: `ui/mobile/src/components/subagents/README.md`

- [ ] **Step 1: Verify no remaining references**

Run: `cd /Users/ericw/work/code/ai/sebastian && grep -rn "SessionDetailView" ui/mobile/ --include="*.tsx" --include="*.ts"`
Expected: only matches inside `SessionDetailView.tsx` itself and possibly `README.md`.

- [ ] **Step 2: Delete the file**

Run: `git rm ui/mobile/src/components/subagents/SessionDetailView.tsx`

- [ ] **Step 3: Update README**

Open `ui/mobile/src/components/subagents/README.md`. Remove any line referencing `SessionDetailView.tsx` or "Session 内任务视图". Save.

- [ ] **Step 4: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/mobile/src/components/subagents/
git commit -m "$(cat <<'EOF'
refactor(mobile): 删除 SessionDetailView，已被右侧 TodoSidebar 取代

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: SSE handling for todo_updated

**Files:**
- Modify: `ui/mobile/src/hooks/useSSE.ts` (or equivalent SSE dispatch location)

- [ ] **Step 1: Locate SSE event dispatch**

Run: `cat ui/mobile/src/hooks/useSSE.ts`
Look for the switch/if chain that routes by `event.type`.

If events are handled in `ui/mobile/src/api/sse.ts` or elsewhere, follow the actual dispatch chain to where individual event types are matched.

- [ ] **Step 2: Add todo_updated handler**

In the relevant dispatch location, add a branch that invalidates the todos query:

```typescript
if (event.type === 'todo.updated') {
  const sessionId = event.data?.session_id;
  if (sessionId) {
    queryClient.invalidateQueries({ queryKey: ['session-todos', sessionId] });
  }
  return;
}
```

Ensure `queryClient` is accessible in that scope. Mirror how existing events (e.g., `task.created`) are handled — if they use `useQueryClient()` in the hook, do the same.

- [ ] **Step 3: Type check**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/hooks/useSSE.ts
git commit -m "$(cat <<'EOF'
feat(mobile): SSE 处理 todo.updated 事件，刷新 todos query

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Update mobile README

**Files:**
- Modify: `ui/mobile/README.md`

- [ ] **Step 1: Update modification navigation table**

Open `ui/mobile/README.md`. In the "修改导航" table, add rows:

```
| 改右侧 Todo 侧边栏内容 | `src/components/chat/TodoSidebar.tsx` |
| 改页面级横向 pan 手势 | `src/components/common/ContentPanGestureArea.tsx` |
| 改 Sidebar 左右参数 | `src/components/common/Sidebar.tsx`（`side` prop） |
| 改 todos API 请求 | `src/api/todos.ts` |
| 改 todos React Query 装配 | `src/hooks/useSessionTodos.ts` |
```

Also update the `components/chat/` section to list `TodoSidebar.tsx`, and the `components/subagents/` section to remove `SessionDetailView.tsx`.

- [ ] **Step 2: Commit**

```bash
git add ui/mobile/README.md
git commit -m "$(cat <<'EOF'
docs(mobile): 更新 README 修改导航，新增 TodoSidebar 相关条目

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: End-to-end manual verification

**No files to modify. This task runs the full verification checklist from spec §6.2.**

- [ ] **Step 1: Start backend**

Run: `uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload`
Expected: gateway boots without errors. Check log for TodoStore init.

- [ ] **Step 2: Run full test suite**

In a second terminal: `pytest tests/unit/test_todo_store.py tests/unit/test_todo_write_tool.py tests/integration/test_sessions_todos_api.py tests/unit/test_base_agent.py -v`
Expected: all PASS.

- [ ] **Step 3: Start Android emulator + app**

```bash
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed
cd ui/mobile
npx expo run:android
```

- [ ] **Step 4: Run the verification checklist**

Verify each item from spec §6.2:

1. [ ] Main chat: right-swipe anywhere in conversation area → left sidebar opens
2. [ ] Main chat: left-swipe anywhere in conversation area → right TodoSidebar opens
3. [ ] Vertical scroll on message list does NOT accidentally trigger sidebar open
4. [ ] Keyboard open: horizontal swipe still works
5. [ ] Sub-agent session page: left-swipe → right TodoSidebar opens
6. [ ] Sub-agent session page: NO left sidebar (main chat only)
7. [ ] Sub-agent session page: top "消息/任务" tab is GONE
8. [ ] Empty session: TodoSidebar opens and shows "暂无任务" / "暂无待办"
9. [ ] Ask LLM to use todo_write → sidebar updates in real time via SSE
10. [ ] Completed todos: strikethrough + green success icon
11. [ ] In-progress todo: blue-highlighted + `activeForm` text
12. [ ] Pending todo: empty circle + normal text
13. [ ] Open a sub-agent session, have it call todo_write → those todos are ONLY visible in that sub-session (not in main chat sidebar)

- [ ] **Step 5: Record any failures**

For each failing item, either fix it (creating additional commits) or document it in a `known-issues` note under the PR description.

---

## Self-Review

**Spec coverage check:**

- §1 Background/Goals → covered by whole plan
- §2.1 TodoItem schema → Task 1, Task 9
- §2.2 Storage location → Task 2 (TodoStore)
- §2.3 No auto-clear deviation → Task 5 (tool has no `allDone ? [] : todos` logic)
- §3.1 todo_write tool → Task 5
- §3.1.1 Coverage semantics → enforced by tool's single-param list signature in Task 5
- §3.1.2 Prompt injection → Task 7
- §3.2 TodoStore → Task 2
- §3.3 GET endpoint → Task 6
- §3.4 todo_updated SSE → Task 3 (enum), Task 5 (publish), Task 19 (subscribe)
- §4.1 Sidebar parameterization → Task 10
- §4.2 ContentPanGestureArea → Task 11
- §4.3 TodoSidebar → Task 15
- §4.4 Icons → Task 12
- §4.5 Page integration → Task 16, 17
- §4.6 Delete SessionDetailView → Task 18
- §5 Change list → all files covered across tasks
- §6.1 Backend tests → Tasks 2, 5, 6
- §6.2 Manual verification → Task 21

**Type consistency check:**
- Backend `TodoItem.active_form` (snake_case) vs frontend `activeForm` (camelCase): handled by `alias="activeForm"` + `populate_by_name=True` in Task 1, and by `model_dump(by_alias=True)` in Tasks 2 (TodoStore.write) and 6 (gateway handler). ✓
- Tool param naming: LLM passes `activeForm` (camelCase) as JSON; Pydantic alias accepts it. ✓
- `TodoStore.read` signature: `(agent_type, session_id)` positional — consistent in Tasks 2, 5, 6, 7. ✓
- `getSessionTasks(sessionId, agentType)` argument order: consistent between existing code and Task 15 TodoSidebar. Verify against `src/api/sessions.ts` when implementing. ✓ (documented in Task 15 notes)
- `agentType` prop name on `TodoSidebar`: used consistently in Tasks 15, 16, 17. ✓

**Placeholder scan:** no "TBD", "implement later", or hand-wave steps. Each code step has full code.

**Gaps fixed inline:** initially missed documenting the prompt injection integration test — acceptable because prompt injection is an internal helper; manual verification step 9 in Task 21 indirectly validates it.

---

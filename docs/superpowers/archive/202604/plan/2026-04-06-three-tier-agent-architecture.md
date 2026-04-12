# 三层 Agent 架构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the AgentPool/Worker/A2A two-tier model with a three-tier singleton agent architecture where each agent answers directly using its own persona, users can create conversations with sub-agents, and agents can delegate sub-tasks asynchronously.

**Architecture:** Agents become singletons keyed by `agent_type`. Sessions gain `depth` (1-3), `parent_session_id`, and `last_activity_at` fields. `agent_id` is removed everywhere. Delegation uses `asyncio.create_task` instead of A2A dispatcher queues. A watchdog detects stalled sessions.

**Tech Stack:** Python 3.12+ / FastAPI / Pydantic / SQLite (file-based sessions) / React Native (Expo Router)

---

## File Structure

### Backend — Files to Create

| File | Responsibility |
|------|---------------|
| `sebastian/capabilities/tools/delegate_to_agent/__init__.py` | Sebastian-only tool: async delegation to depth=2 agents |
| `sebastian/capabilities/tools/spawn_sub_agent/__init__.py` | Leader-only tool: spawn depth=3 worker sessions |
| `sebastian/capabilities/tools/check_sub_agents/__init__.py` | Shared tool: list sub-session statuses |
| `sebastian/capabilities/tools/inspect_session/__init__.py` | Shared tool: read recent messages of a session |
| `sebastian/core/session_runner.py` | `run_agent_session()` — async wrapper that runs an agent on a session, sets status on completion/failure |
| `sebastian/core/stalled_watchdog.py` | Background watchdog: scans active sessions, marks stalled ones |

### Backend — Files to Modify

| File | What Changes |
|------|-------------|
| `sebastian/core/types.py` | Session: remove `agent_id`, add `depth`/`parent_session_id`/`last_activity_at`; SessionStatus: add `completed`/`failed`/`stalled`/`cancelled` |
| `sebastian/core/base_agent.py` | `_active_stream` and `_current_task_goal` become per-session dicts; remove `execute_delegated_task` |
| `sebastian/agents/_loader.py` | `AgentConfig`: remove `worker_count`, add `max_children`/`stalled_threshold_minutes`/`display_name` |
| `sebastian/store/session_store.py` | Remove `agent_id` from all paths; simplify `subagents/{type}/{id}/` → `{type}/{id}/` |
| `sebastian/store/index_store.py` | `upsert` writes new fields; remove `list_by_worker`; add `list_active_children` |
| `sebastian/config/__init__.py` | `ensure_data_dir`: remove `subagents/` nesting |
| `sebastian/gateway/state.py` | Replace `agent_pools`/`worker_sessions`/`dispatcher` with `agent_instances: dict[str, BaseAgent]` |
| `sebastian/gateway/app.py` | Replace `_initialize_a2a_and_pools` with `_initialize_agent_instances`; remove `_register_runtime_agent_state_handlers`; start watchdog |
| `sebastian/gateway/routes/sessions.py` | `_schedule_session_turn`: route to agent instance directly; add `POST /agents/{type}/sessions` |
| `sebastian/gateway/routes/agents.py` | Return `active_session_count`/`max_children` instead of workers array |
| `sebastian/orchestrator/sebas.py` | Remove `intervene`; update `get_or_create_session` (no agent_id); update `_agents_section` to use display_name |
| `sebastian/protocol/events/types.py` | Add `SESSION_COMPLETED`/`SESSION_FAILED`/`SESSION_STALLED` event types |
| `sebastian/permissions/types.py` | Add `agent_type` and `depth` to `ToolCallContext` |

### Backend — Files to Delete

| File | Reason |
|------|--------|
| `sebastian/core/agent_pool.py` | Worker pool replaced by singleton agents |
| `sebastian/protocol/a2a/dispatcher.py` | Queue+future mechanism removed |
| `sebastian/protocol/a2a/types.py` | `DelegateTask`/`TaskResult` removed |
| `sebastian/orchestrator/tools/delegate.py` | Moved to `capabilities/tools/delegate_to_agent/` |
| `sebastian/orchestrator/tools/__init__.py` | Directory being removed |
| `tests/unit/test_agent_pool.py` | Corresponding module deleted |

### Frontend — Files to Create

| File | Responsibility |
|------|---------------|
| `ui/mobile/src/components/common/NewChatFAB.tsx` | Floating action button for new chat |

### Frontend — Files to Modify

| File | What Changes |
|------|-------------|
| `ui/mobile/src/types.ts` | `SessionMeta`: add `depth`/`parent_session_id`/`last_activity_at`/`stalled` status; `Agent`: remove workers, add `active_session_count`/`max_children` |
| `ui/mobile/src/components/common/Icons.tsx` | Add `EditIcon` from edit.svg paths |
| `ui/mobile/src/api/sessions.ts` | Add `createAgentSession()`; update `BackendSessionMeta` |
| `ui/mobile/src/api/agents.ts` | Update `BackendAgentSummary` and `mapAgentSummary` |
| `ui/mobile/src/components/chat/AppSidebar.tsx` | Replace footer button with floating NewChatFAB |
| `ui/mobile/app/subagents/[agentId].tsx` | Add NewChatFAB; navigate to `session/new` |
| `ui/mobile/app/subagents/session/[id].tsx` | Handle `id=new` for lazy session creation |
| `ui/mobile/src/components/subagents/SessionList.tsx` | Show depth=3 badge on worker sessions |

---

## Task 1: Data Model — Session & SessionStatus

**Files:**
- Modify: `sebastian/core/types.py:28-101`
- Test: `tests/unit/test_types.py`

- [ ] **Step 1: Write failing test for new SessionStatus values**

```python
# tests/unit/test_types.py
from sebastian.core.types import Session, SessionStatus


def test_session_status_includes_new_values():
    assert SessionStatus.COMPLETED == "completed"
    assert SessionStatus.FAILED == "failed"
    assert SessionStatus.STALLED == "stalled"
    assert SessionStatus.CANCELLED == "cancelled"


def test_session_has_depth_and_parent():
    s = Session(
        agent_type="code",
        title="test",
        depth=2,
    )
    assert s.depth == 2
    assert s.parent_session_id is None
    assert s.last_activity_at is not None


def test_session_no_agent_id():
    s = Session(agent_type="code", title="test", depth=1)
    assert not hasattr(s, "agent_id") or "agent_id" not in s.model_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_types.py -v`
Expected: FAIL — `SessionStatus` has no `COMPLETED`/`FAILED`/`STALLED`/`CANCELLED`; `Session` has no `depth`

- [ ] **Step 3: Update SessionStatus and Session model**

In `sebastian/core/types.py`:

```python
class SessionStatus(StrEnum):
    """Enumeration of session lifecycle states."""

    ACTIVE = "active"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    STALLED = "stalled"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class Session(BaseModel):
    """Conversation session that owns messages and child tasks."""

    id: str = Field(
        default_factory=lambda: (
            datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S") + "_" + uuid.uuid4().hex[:6]
        )
    )
    agent_type: str
    title: str
    status: SessionStatus = SessionStatus.ACTIVE
    depth: int = 1
    parent_session_id: str | None = None
    last_activity_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_count: int = 0
    active_task_count: int = 0
```

Key change: `agent_id` field is **removed**. `depth`, `parent_session_id`, `last_activity_at` are added.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_types.py -v`
Expected: PASS

- [ ] **Step 5: Fix all imports and usages of Session.agent_id across the codebase**

Search for all references to `agent_id` in Python files (excluding test_agent_pool.py which will be deleted). Each file that constructs or reads `Session.agent_id` needs updating. Key locations:

- `sebastian/store/session_store.py` — all path methods (Task 3)
- `sebastian/store/index_store.py` — upsert entry (Task 4)
- `sebastian/orchestrator/sebas.py` — get_or_create_session (Task 12)
- `sebastian/gateway/routes/sessions.py` — _resolve_session (Task 13)
- `sebastian/core/base_agent.py` — execute_delegated_task (Task 6, deleted)

Do NOT fix these yet — they are addressed in their own tasks. This step is just to document the blast radius.

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/types.py tests/unit/test_types.py
git commit -m "refactor(core): Session 移除 agent_id，新增 depth/parent_session_id/last_activity_at；SessionStatus 新增 completed/failed/stalled/cancelled"
```

---

## Task 2: AgentConfig — New Manifest Format

**Files:**
- Modify: `sebastian/agents/_loader.py`
- Modify: `sebastian/agents/code/manifest.toml`
- Test: `tests/unit/test_loader.py` (if exists, else create)

- [ ] **Step 1: Write failing test for new AgentConfig fields**

```python
# tests/unit/test_agent_loader.py
from sebastian.agents._loader import AgentConfig


def test_agent_config_has_new_fields():
    cfg = AgentConfig(
        agent_type="code",
        name="CodeAgent",
        display_name="铁匠",
        description="编写代码",
        max_children=5,
        stalled_threshold_minutes=5,
        agent_class=object,  # placeholder
    )
    assert cfg.display_name == "铁匠"
    assert cfg.max_children == 5
    assert cfg.stalled_threshold_minutes == 5


def test_agent_config_no_worker_count():
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(AgentConfig)}
    assert "worker_count" not in field_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_loader.py -v`
Expected: FAIL — `AgentConfig` has no `display_name`/`max_children`/`stalled_threshold_minutes`

- [ ] **Step 3: Update AgentConfig dataclass**

In `sebastian/agents/_loader.py`, update the `AgentConfig` dataclass:

```python
@dataclasses.dataclass
class AgentConfig:
    agent_type: str
    name: str                             # class name (e.g. "CodeAgent")
    display_name: str                     # user-facing name (e.g. "铁匠")
    description: str
    max_children: int                     # max concurrent depth=3 sessions
    stalled_threshold_minutes: int        # stalled detection threshold
    agent_class: type[BaseAgent]
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
```

Update the `load_agents()` function to read the new manifest fields:

```python
# Inside load_agents(), where manifest is parsed:
agent_section = manifest["agent"]
config = AgentConfig(
    agent_type=agent_dir.name,
    name=agent_section["class_name"],
    display_name=agent_section.get("name", agent_section["class_name"]),
    description=agent_section.get("description", ""),
    max_children=agent_section.get("max_children", 5),
    stalled_threshold_minutes=agent_section.get("stalled_threshold_minutes", 5),
    agent_class=agent_cls,
    allowed_tools=agent_section.get("allowed_tools"),
    allowed_skills=agent_section.get("allowed_skills"),
)
```

- [ ] **Step 4: Update manifest.toml for code agent**

```toml
# sebastian/agents/code/manifest.toml
[agent]
name = "铁匠"
class_name = "CodeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5
stalled_threshold_minutes = 5
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_agent_loader.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/agents/_loader.py sebastian/agents/code/manifest.toml tests/unit/test_agent_loader.py
git commit -m "refactor(agents): AgentConfig 移除 worker_count，新增 display_name/max_children/stalled_threshold_minutes"
```

---

## Task 3: SessionStore — Remove agent_id from Paths

**Files:**
- Modify: `sebastian/store/session_store.py:32-98`
- Test: `tests/unit/test_session_store.py`

- [ ] **Step 1: Write failing test for new path structure**

```python
# tests/unit/test_session_store_paths.py
import asyncio
from pathlib import Path
from sebastian.core.types import Session
from sebastian.store.session_store import SessionStore


async def _test_subagent_session_path():
    """Sub-agent sessions should be stored at {agent_type}/{session_id}/ without agent_id."""
    tmp = Path("/tmp/test_sessions_path")
    tmp.mkdir(parents=True, exist_ok=True)
    store = SessionStore(tmp)
    session = Session(id="test123", agent_type="code", title="test", depth=2)
    await store.create_session(session)
    expected_dir = tmp / "code" / "test123"
    assert expected_dir.exists(), f"Expected {expected_dir} to exist"
    # No 'subagents' in path
    assert "subagents" not in str(expected_dir)


def test_subagent_session_path():
    asyncio.run(_test_subagent_session_path())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_session_store_paths.py -v`
Expected: FAIL — path still includes `subagents/{agent_type}/{agent_id}/`

- [ ] **Step 3: Update path construction functions**

In `sebastian/store/session_store.py`, update the two path functions:

```python
def _session_dir(sessions_dir: Path, session: Session) -> Path:
    """Return the session directory, creating the required structure."""
    if session.agent_type == "sebastian":
        directory = sessions_dir / "sebastian" / session.id
    else:
        directory = sessions_dir / session.agent_type / session.id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tasks").mkdir(exist_ok=True)
    return directory


def _session_dir_by_id(
    sessions_dir: Path,
    session_id: str,
    agent_type: str,
) -> Path:
    if agent_type == "sebastian":
        return sessions_dir / "sebastian" / session_id
    return sessions_dir / agent_type / session_id
```

Then update every method in `SessionStore` that accepts `agent_id` parameter:
- Remove `agent_id` parameter from: `get_session`, `append_message`, `get_messages`, `update_session_status`, `create_task`, `get_task`, `list_tasks`, `update_task_status`, `_session_lock`
- Update `_session_dir_by_id` calls to drop `agent_id`
- Update `create_session` to not pass `agent_id` to `_session_lock`

For `get_session_for_agent_type`, simplify:

```python
async def get_session_for_agent_type(
    self,
    session_id: str,
    agent_type: str,
) -> Session | None:
    """Look up a session by id and agent_type."""
    return await self.get_session(session_id, agent_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_session_store_paths.py -v`
Expected: PASS

- [ ] **Step 5: Run full session store tests**

Run: `pytest tests/unit/test_session_store.py -v`
Fix any failures caused by removed `agent_id` parameter in existing tests.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/session_store.py tests/unit/test_session_store_paths.py tests/unit/test_session_store.py
git commit -m "refactor(store): SessionStore 移除 agent_id 参数，路径简化为 {agent_type}/{session_id}/"
```

---

## Task 4: IndexStore — New Fields, Remove list_by_worker

**Files:**
- Modify: `sebastian/store/index_store.py`
- Test: `tests/unit/test_index_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_index_store_v2.py
import asyncio
from pathlib import Path
from sebastian.core.types import Session
from sebastian.store.index_store import IndexStore


async def _test_upsert_writes_new_fields():
    tmp = Path("/tmp/test_index_v2")
    tmp.mkdir(parents=True, exist_ok=True)
    store = IndexStore(tmp)
    session = Session(
        id="test1", agent_type="code", title="test", depth=2,
        parent_session_id=None,
    )
    await store.upsert(session)
    entries = await store.list_all()
    entry = entries[0]
    assert entry["depth"] == 2
    assert entry["parent_session_id"] is None
    assert "last_activity_at" in entry
    assert "agent_id" not in entry


async def _test_list_active_children():
    tmp = Path("/tmp/test_index_children")
    tmp.mkdir(parents=True, exist_ok=True)
    store = IndexStore(tmp)
    parent = Session(id="parent1", agent_type="code", title="parent", depth=2)
    await store.upsert(parent)
    child1 = Session(id="child1", agent_type="code", title="c1", depth=3, parent_session_id="parent1")
    child2 = Session(id="child2", agent_type="code", title="c2", depth=3, parent_session_id="parent1")
    await store.upsert(child1)
    await store.upsert(child2)
    children = await store.list_active_children("code", "parent1")
    assert len(children) == 2


def test_upsert_writes_new_fields():
    asyncio.run(_test_upsert_writes_new_fields())


def test_list_active_children():
    asyncio.run(_test_list_active_children())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_index_store_v2.py -v`
Expected: FAIL

- [ ] **Step 3: Update IndexStore**

In `sebastian/store/index_store.py`:

Update `upsert` to include new fields and remove `agent_id`:

```python
async def upsert(self, session: Session) -> None:
    async with self._lock:
        sessions = await self._read()
        entry = {
            "id": session.id,
            "agent_type": session.agent_type,
            "title": session.title,
            "status": session.status.value,
            "depth": session.depth,
            "parent_session_id": session.parent_session_id,
            "last_activity_at": session.last_activity_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "task_count": session.task_count,
            "active_task_count": session.active_task_count,
        }
        sessions = [existing for existing in sessions if existing["id"] != session.id]
        sessions.insert(0, entry)
        await self._write(sessions)
```

Remove `list_by_worker` method entirely.

Add `list_active_children` method:

```python
async def list_active_children(
    self,
    agent_type: str,
    parent_session_id: str,
) -> list[dict[str, Any]]:
    """List active depth=3 sessions for a parent session."""
    return [
        s for s in await self._read()
        if s.get("agent_type") == agent_type
        and s.get("parent_session_id") == parent_session_id
        and s.get("status") == "active"
    ]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_index_store_v2.py tests/unit/test_index_store.py -v`
Expected: PASS (fix existing tests if they reference `agent_id` in index entries)

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/index_store.py tests/unit/test_index_store_v2.py tests/unit/test_index_store.py
git commit -m "refactor(store): IndexStore 新增 depth/parent_session_id/last_activity_at，移除 list_by_worker"
```

---

## Task 5: Config — Simplify Data Directory

**Files:**
- Modify: `sebastian/config/__init__.py`

- [ ] **Step 1: Update ensure_data_dir**

In `sebastian/config/__init__.py`, update `ensure_data_dir()` to remove the `subagents/` nesting:

```python
def ensure_data_dir(self) -> None:
    """Create required data directory structure."""
    for sub in (
        "sessions/sebastian",
        "extensions/skills",
        "extensions/agents",
        "workspace",
    ):
        (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
```

The `sessions/subagents/` directory is no longer created. Sub-agent session directories (`sessions/code/`, `sessions/stock/`, etc.) will be created on-demand by `SessionStore._session_dir()`.

- [ ] **Step 2: Commit**

```bash
git add sebastian/config/__init__.py
git commit -m "refactor(config): ensure_data_dir 移除 subagents/ 嵌套"
```

---

## Task 6: BaseAgent — Per-Session Concurrency, Remove execute_delegated_task

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Test: `tests/unit/test_base_agent.py`

- [ ] **Step 1: Write failing test for per-session state**

```python
# Add to tests/unit/test_base_agent.py or create new file
import pytest
from unittest.mock import AsyncMock, MagicMock
from sebastian.core.base_agent import BaseAgent


def test_base_agent_has_no_execute_delegated_task():
    """execute_delegated_task should be removed."""
    assert not hasattr(BaseAgent, "execute_delegated_task")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_base_agent.py::test_base_agent_has_no_execute_delegated_task -v`
Expected: FAIL — method still exists

- [ ] **Step 3: Update BaseAgent**

In `sebastian/core/base_agent.py`:

1. Change instance attributes (in `__init__`):

```python
# Replace these two lines:
#   self._current_task_goal: str = ""
#   self._active_stream: asyncio.Task[str] | None = None
# With:
self._current_task_goals: dict[str, str] = {}          # session_id → goal
self._active_streams: dict[str, asyncio.Task[str]] = {}  # session_id → task
```

2. Update `run_streaming` to use per-session state:

```python
async def run_streaming(
    self,
    user_message: str,
    session_id: str,
    task_id: str | None = None,
    agent_name: str | None = None,
) -> str:
    self._current_task_goals[session_id] = user_message

    # ... LLM provider refresh logic stays the same ...

    agent_context = agent_name or self.name
    existing = self._active_streams.get(session_id)
    if existing is not None and not existing.done():
        existing.cancel()
        try:
            await existing
        except (asyncio.CancelledError, Exception):
            pass

    worker_session = await self._session_store.get_session_for_agent_type(
        session_id, agent_context,
    )
    # ... rest stays the same, but replace self._active_stream references:
    
    current_stream = asyncio.create_task(
        self._stream_inner(
            messages=messages,
            session_id=session_id,
            task_id=task_id,
            agent_context=agent_context,
        )
    )
    self._active_streams[session_id] = current_stream
    try:
        return await current_stream
    finally:
        self._active_streams.pop(session_id, None)
        self._current_task_goals.pop(session_id, None)
```

3. Update `_stream_inner` where it reads `_current_task_goal`:

```python
context = ToolCallContext(
    task_goal=self._current_task_goals.get(session_id, ""),
    session_id=session_id,
    task_id=task_id,
)
```

4. **Delete the entire `execute_delegated_task` method** (lines 400-436) and its type imports (`DelegateTask`, `A2ATaskResult`).

5. Remove the `TYPE_CHECKING` imports for `DelegateTask` and `A2ATaskResult`.

- [ ] **Step 4: Update last_activity_at during streaming**

In `_stream_inner`, after publishing key events (TURN_RECEIVED, ToolCallReady, TurnDone), update the session's `last_activity_at` in the index. To avoid excessive I/O, only update at these three points (not every delta):

```python
# In _stream_inner, after publishing TURN_RECEIVED and after each ToolCallReady/TurnDone:
async def _update_activity(self, session_id: str) -> None:
    """Update last_activity_at for stalled detection."""
    try:
        import sebastian.gateway.state as _state
        entries = await _state.index_store.list_all()
        for entry in entries:
            if entry["id"] == session_id:
                entry["last_activity_at"] = datetime.now(UTC).isoformat()
                break
        await _state.index_store._write(entries)
    except AttributeError:
        pass  # state not initialised (tests)
```

Call `await self._update_activity(session_id)` after `TURN_RECEIVED` publish, after each `ToolCallReady` handling, and before `TurnDone` return.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_base_agent.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent.py
git commit -m "refactor(core): BaseAgent 状态改为 per-session dict，移除 execute_delegated_task，流式更新 last_activity_at"
```

---

## Task 7: Delete Old Infrastructure

**Files:**
- Delete: `sebastian/core/agent_pool.py`
- Delete: `sebastian/protocol/a2a/dispatcher.py`
- Delete: `sebastian/protocol/a2a/types.py`
- Delete: `sebastian/orchestrator/tools/delegate.py`
- Delete: `sebastian/orchestrator/tools/__init__.py` (if exists)
- Delete: `tests/unit/test_agent_pool.py`

- [ ] **Step 1: Delete the files**

```bash
rm sebastian/core/agent_pool.py
rm sebastian/protocol/a2a/dispatcher.py
rm sebastian/protocol/a2a/types.py
rm -rf sebastian/orchestrator/tools/
rm tests/unit/test_agent_pool.py
```

- [ ] **Step 2: Remove stale imports**

Search for and remove any imports of the deleted modules across the codebase:

- `from sebastian.core.agent_pool import AgentPool` (in `gateway/app.py`, `gateway/state.py`)
- `from sebastian.protocol.a2a.dispatcher import A2ADispatcher` (in `gateway/app.py`, `gateway/state.py`, `orchestrator/tools/delegate.py`)
- `from sebastian.protocol.a2a.types import DelegateTask, TaskResult` (in `core/base_agent.py` — already handled in Task 6)

These imports will be addressed in their respective gateway tasks (Tasks 8-9), but scan now to verify nothing else imports them.

- [ ] **Step 3: Run lint to find broken imports**

Run: `ruff check sebastian/ --select F811,F401,E402`
Fix any remaining import errors.

- [ ] **Step 4: Commit**

```bash
git add -A  # careful: only the deletions
git commit -m "chore: 删除 AgentPool、A2A Dispatcher、orchestrator/tools — 被三层架构替代"
```

---

## Task 8: EventType — Add Session Lifecycle Events

**Files:**
- Modify: `sebastian/protocol/events/types.py`

- [ ] **Step 1: Add new event types**

In `sebastian/protocol/events/types.py`, add to the `EventType` enum:

```python
# Session lifecycle (three-tier architecture)
SESSION_COMPLETED = "session.completed"
SESSION_FAILED = "session.failed"
SESSION_STALLED = "session.stalled"
```

- [ ] **Step 2: Commit**

```bash
git add sebastian/protocol/events/types.py
git commit -m "feat(protocol): 新增 SESSION_COMPLETED/FAILED/STALLED 事件类型"
```

---

## Task 9: ToolCallContext — Add Agent Metadata

**Files:**
- Modify: `sebastian/permissions/types.py`

- [ ] **Step 1: Add agent_type and depth fields**

```python
@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
```

These fields let shared tools (check_sub_agents, inspect_session) know who is calling them and at what depth.

- [ ] **Step 2: Update all ToolCallContext construction sites**

In `sebastian/core/base_agent.py` `_stream_inner`, update the context creation to pass agent info. This requires the method to know the agent_type. Add `agent_type` parameter to `_stream_inner`:

```python
context = ToolCallContext(
    task_goal=self._current_task_goals.get(session_id, ""),
    session_id=session_id,
    task_id=task_id,
    agent_type=agent_context,
    depth=getattr(self, '_current_depth', {}).get(session_id, 1),
)
```

Note: The `depth` will be set by the session runner (Task 10) before calling `run_streaming`. For now, default to 1.

- [ ] **Step 3: Commit**

```bash
git add sebastian/permissions/types.py sebastian/core/base_agent.py
git commit -m "feat(permissions): ToolCallContext 新增 agent_type/depth 字段"
```

---

## Task 10: Session Runner — Async Wrapper

**Files:**
- Create: `sebastian/core/session_runner.py`
- Test: `tests/unit/test_session_runner.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_session_runner.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sebastian.core.types import Session, SessionStatus
from sebastian.core.session_runner import run_agent_session


@pytest.mark.asyncio
async def test_run_agent_session_success():
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value="done")
    session = Session(id="s1", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="write tests",
        session_store=session_store,
        index_store=index_store,
        event_bus=event_bus,
    )

    agent.run_streaming.assert_awaited_once_with("write tests", "s1")
    # Session should be marked completed
    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.COMPLETED


@pytest.mark.asyncio
async def test_run_agent_session_failure():
    agent = MagicMock()
    agent.run_streaming = AsyncMock(side_effect=RuntimeError("boom"))
    session = Session(id="s2", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="bad task",
        session_store=session_store,
        index_store=index_store,
        event_bus=event_bus,
    )

    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.FAILED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_session_runner.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement session_runner.py**

```python
# sebastian/core/session_runner.py
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


async def run_agent_session(
    agent: BaseAgent,
    session: Session,
    goal: str,
    session_store: SessionStore,
    index_store: IndexStore,
    event_bus: EventBus | None = None,
) -> None:
    """Run an agent on a session asynchronously. Sets status on completion/failure."""
    try:
        await agent.run_streaming(goal, session.id)
        session.status = SessionStatus.COMPLETED
    except Exception:
        logger.exception("Agent session %s failed", session.id)
        session.status = SessionStatus.FAILED
    finally:
        session.updated_at = datetime.now(UTC)
        session.last_activity_at = datetime.now(UTC)
        await session_store.update_session(session)
        await index_store.upsert(session)
        if event_bus is not None:
            event_type = (
                EventType.SESSION_COMPLETED
                if session.status == SessionStatus.COMPLETED
                else EventType.SESSION_FAILED
            )
            await event_bus.publish(
                Event(
                    type=event_type,
                    data={
                        "session_id": session.id,
                        "agent_type": session.agent_type,
                        "status": session.status.value,
                    },
                )
            )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_session_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/session_runner.py tests/unit/test_session_runner.py
git commit -m "feat(core): session_runner — 异步执行 agent session，自动标记 completed/failed"
```

---

## Task 11: delegate_to_agent Tool — Migration to capabilities/tools/

**Files:**
- Create: `sebastian/capabilities/tools/delegate_to_agent/__init__.py`
- Test: `tests/unit/test_tool_delegate.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_tool_delegate.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_delegate_to_agent_creates_session_and_dispatches():
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent
    from sebastian.permissions.types import ToolCallContext

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_agent.name = "code"
    mock_state.agent_instances = {"code": mock_agent}
    mock_state.agent_registry = {
        "code": MagicMock(display_name="铁匠", max_children=5),
    }
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.event_bus = MagicMock()

    ctx = ToolCallContext(
        task_goal="build feature",
        session_id="seb_session",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )

    with patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state):
        result = await delegate_to_agent(
            agent_type="code", goal="write auth module", context="", _ctx=ctx,
        )

    assert result.ok is True
    assert "铁匠" in result.output
    mock_state.session_store.create_session.assert_awaited_once()
    mock_state.index_store.upsert.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_delegate.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement the tool**

```python
# sebastian/capabilities/tools/delegate_to_agent/__init__.py
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import Session, ToolResult

logger = logging.getLogger(__name__)


def _get_state():
    import sebastian.gateway.state as state
    return state


@tool(
    name="delegate_to_agent",
    description="委派任务给指定的下属 Agent。任务将异步执行，你可以继续处理其他事务。",
    parameters={
        "agent_type": {"type": "string", "description": "目标 Agent 的类型标识（如 code、stock）"},
        "goal": {"type": "string", "description": "需要完成的任务目标"},
        "context": {"type": "string", "description": "相关背景信息", "default": ""},
    },
)
async def delegate_to_agent(
    agent_type: str,
    goal: str,
    context: str = "",
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    state = _get_state()

    if agent_type not in state.agent_instances:
        return ToolResult(ok=False, error=f"未知的 Agent 类型: {agent_type}")

    config = state.agent_registry.get(agent_type)
    display_name = config.display_name if config else agent_type

    session = Session(
        agent_type=agent_type,
        title=goal[:40],
        depth=2,
    )
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    agent = state.agent_instances[agent_type]
    full_goal = f"{goal}\n\n背景信息：{context}" if context else goal

    from sebastian.core.session_runner import run_agent_session

    asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=full_goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )

    return ToolResult(ok=True, output=f"已安排{display_name}处理：{goal}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_tool_delegate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/delegate_to_agent/__init__.py tests/unit/test_tool_delegate.py
git commit -m "feat(tools): delegate_to_agent 迁移至 capabilities/tools/，改为异步 create_task 委派"
```

---

## Task 12: spawn_sub_agent Tool

**Files:**
- Create: `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`
- Test: `tests/unit/test_tool_spawn.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_tool_spawn.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sebastian.permissions.types import ToolCallContext


@pytest.mark.asyncio
async def test_spawn_sub_agent_success():
    from sebastian.capabilities.tools.spawn_sub_agent import spawn_sub_agent

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_agent.name = "code"
    mock_state.agent_instances = {"code": mock_agent}
    mock_state.agent_registry = {"code": MagicMock(max_children=5)}
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.index_store.list_active_children = AsyncMock(return_value=[])
    mock_state.event_bus = MagicMock()

    ctx = ToolCallContext(
        task_goal="complex task",
        session_id="parent_session",
        task_id=None,
        agent_type="code",
        depth=2,
    )

    with patch("sebastian.capabilities.tools.spawn_sub_agent._get_state", return_value=mock_state):
        result = await spawn_sub_agent(goal="write unit tests", context="", _ctx=ctx)

    assert result.ok is True
    assert "组员" in result.output
    mock_state.session_store.create_session.assert_awaited_once()
    created_session = mock_state.session_store.create_session.call_args[0][0]
    assert created_session.depth == 3
    assert created_session.parent_session_id == "parent_session"


@pytest.mark.asyncio
async def test_spawn_sub_agent_over_limit():
    from sebastian.capabilities.tools.spawn_sub_agent import spawn_sub_agent

    mock_state = MagicMock()
    mock_state.agent_registry = {"code": MagicMock(max_children=2)}
    mock_state.index_store = AsyncMock()
    mock_state.index_store.list_active_children = AsyncMock(
        return_value=[{"id": "c1"}, {"id": "c2"}]
    )

    ctx = ToolCallContext(
        task_goal="task", session_id="parent", task_id=None, agent_type="code", depth=2,
    )

    with patch("sebastian.capabilities.tools.spawn_sub_agent._get_state", return_value=mock_state):
        result = await spawn_sub_agent(goal="another task", _ctx=ctx)

    assert result.ok is False
    assert "上限" in result.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_spawn.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the tool**

```python
# sebastian/capabilities/tools/spawn_sub_agent/__init__.py
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import Session, ToolResult

logger = logging.getLogger(__name__)


def _get_state():
    import sebastian.gateway.state as state
    return state


@tool(
    name="spawn_sub_agent",
    description="分派子任务给组员处理。组员异步执行，你可以继续处理其他工作。",
    parameters={
        "goal": {"type": "string", "description": "子任务目标"},
        "context": {"type": "string", "description": "相关背景信息", "default": ""},
    },
)
async def spawn_sub_agent(
    goal: str,
    context: str = "",
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    if _ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")

    state = _get_state()
    agent_type = _ctx.agent_type
    parent_session_id = _ctx.session_id

    config = state.agent_registry.get(agent_type)
    if config is None:
        return ToolResult(ok=False, error=f"未知的 Agent 类型: {agent_type}")

    active = await state.index_store.list_active_children(agent_type, parent_session_id)
    if len(active) >= config.max_children:
        return ToolResult(
            ok=False,
            error=f"当前已有{len(active)}个组员在工作，已达上限{config.max_children}",
        )

    session = Session(
        agent_type=agent_type,
        title=goal[:40],
        depth=3,
        parent_session_id=parent_session_id,
    )
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    agent = state.agent_instances[agent_type]
    full_goal = f"{goal}\n\n背景信息：{context}" if context else goal

    from sebastian.core.session_runner import run_agent_session

    asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=full_goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )

    return ToolResult(ok=True, output=f"已安排组员处理：{goal}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_tool_spawn.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/spawn_sub_agent/__init__.py tests/unit/test_tool_spawn.py
git commit -m "feat(tools): spawn_sub_agent — 组长分派 depth=3 组员子任务"
```

---

## Task 13: check_sub_agents Tool

**Files:**
- Create: `sebastian/capabilities/tools/check_sub_agents/__init__.py`
- Test: `tests/unit/test_tool_check_subs.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_tool_check_subs.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sebastian.permissions.types import ToolCallContext


@pytest.mark.asyncio
async def test_check_sub_agents_as_sebastian():
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents

    mock_state = MagicMock()
    mock_state.index_store = AsyncMock()
    mock_state.index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "depth": 2, "status": "active", "title": "写代码"},
        {"id": "s2", "agent_type": "stock", "depth": 2, "status": "completed", "title": "看行情"},
        {"id": "s3", "agent_type": "code", "depth": 3, "status": "active", "title": "子任务"},
    ])

    ctx = ToolCallContext(
        task_goal="check progress", session_id="seb1",
        task_id=None, agent_type="sebastian", depth=1,
    )

    with patch("sebastian.capabilities.tools.check_sub_agents._get_state", return_value=mock_state):
        result = await check_sub_agents(_ctx=ctx)

    assert result.ok is True
    # Sebastian sees depth=2 sessions only
    assert "写代码" in result.output
    assert "看行情" in result.output
    assert "子任务" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_check_subs.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the tool**

```python
# sebastian/capabilities/tools/check_sub_agents/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


def _get_state():
    import sebastian.gateway.state as state
    return state


@tool(
    name="check_sub_agents",
    description="查看下属 Agent 的任务执行状态摘要。",
    parameters={},
)
async def check_sub_agents(
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    if _ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")

    state = _get_state()
    all_sessions = await state.index_store.list_all()

    if _ctx.depth == 1:
        # Sebastian: show all depth=2 sessions
        target_depth = 2
        sessions = [s for s in all_sessions if s.get("depth") == target_depth]
    else:
        # Leader: show depth=3 sessions of same agent_type
        sessions = [
            s for s in all_sessions
            if s.get("depth") == 3 and s.get("agent_type") == _ctx.agent_type
        ]

    if not sessions:
        return ToolResult(ok=True, output="当前没有下属任务。")

    status_counts: dict[str, int] = {}
    lines: list[str] = []
    for s in sessions:
        status = s.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        lines.append(
            f"- [{status}] {s.get('title', '无标题')} (id: {s['id']}, agent: {s.get('agent_type')})"
        )

    summary_parts = [f"{count} {status}" for status, count in status_counts.items()]
    summary = f"{len(sessions)} 个下属任务：{', '.join(summary_parts)}\n\n"
    return ToolResult(ok=True, output=summary + "\n".join(lines))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_tool_check_subs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/check_sub_agents/__init__.py tests/unit/test_tool_check_subs.py
git commit -m "feat(tools): check_sub_agents — 查看下属 session 状态摘要"
```

---

## Task 14: inspect_session Tool

**Files:**
- Create: `sebastian/capabilities/tools/inspect_session/__init__.py`
- Test: `tests/unit/test_tool_inspect.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_tool_inspect.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sebastian.permissions.types import ToolCallContext


@pytest.mark.asyncio
async def test_inspect_session_returns_messages():
    from sebastian.capabilities.tools.inspect_session import inspect_session

    mock_state = MagicMock()
    mock_state.session_store = AsyncMock()
    mock_state.session_store.get_session = AsyncMock(return_value=MagicMock(
        id="s1", agent_type="code", status="active", title="写测试",
        last_activity_at="2026-04-06T10:00:00",
    ))
    mock_state.session_store.get_messages = AsyncMock(return_value=[
        {"role": "user", "content": "请写单元测试", "ts": "2026-04-06T10:00:00"},
        {"role": "assistant", "content": "好的，我来写", "ts": "2026-04-06T10:00:05"},
    ])

    ctx = ToolCallContext(
        task_goal="check", session_id="parent",
        task_id=None, agent_type="sebastian", depth=1,
    )

    with patch("sebastian.capabilities.tools.inspect_session._get_state", return_value=mock_state):
        result = await inspect_session(session_id="s1", recent_n=5, _ctx=ctx)

    assert result.ok is True
    assert "写测试" in result.output
    assert "请写单元测试" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_inspect.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the tool**

```python
# sebastian/capabilities/tools/inspect_session/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


def _get_state():
    import sebastian.gateway.state as state
    return state


@tool(
    name="inspect_session",
    description="查看指定 session 的最近消息和当前状态，用于判断下属任务进展。",
    parameters={
        "session_id": {"type": "string", "description": "要查看的 session ID"},
        "recent_n": {"type": "integer", "description": "返回最近 N 条消息", "default": 5},
    },
)
async def inspect_session(
    session_id: str,
    recent_n: int = 5,
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    state = _get_state()

    # Look up session from index to get agent_type
    all_sessions = await state.index_store.list_all()
    session_entry = next((s for s in all_sessions if s["id"] == session_id), None)
    if session_entry is None:
        return ToolResult(ok=False, error=f"Session {session_id} 未找到")

    agent_type = session_entry["agent_type"]
    session = await state.session_store.get_session(session_id, agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"Session {session_id} 数据不存在")

    messages = await state.session_store.get_messages(
        session_id, agent_type, limit=recent_n,
    )

    lines = [
        f"Session: {session.title}",
        f"状态: {session.status}",
        f"Agent: {agent_type}",
        f"最后活动: {session.last_activity_at}",
        "",
        f"最近 {len(messages)} 条消息：",
    ]
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")[:200]
        lines.append(f"  [{role}] {content}")

    return ToolResult(ok=True, output="\n".join(lines))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_tool_inspect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/inspect_session/__init__.py tests/unit/test_tool_inspect.py
git commit -m "feat(tools): inspect_session — 查看 session 最近消息和状态"
```

---

## Task 15: Gateway State — Replace Pools with Agent Instances

**Files:**
- Modify: `sebastian/gateway/state.py`

- [ ] **Step 1: Update state module**

Replace the entire `sebastian/gateway/state.py` with:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.gateway.sse import SSEManager
    from sebastian.memory.working_memory import WorkingMemory
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore
    from sebastian.llm.registry import LLMProviderRegistry

sebastian: Sebastian
sse_manager: SSEManager
event_bus: EventBus
conversation: ConversationManager
session_store: SessionStore
index_store: IndexStore
db_factory: async_sessionmaker[AsyncSession]
llm_registry: LLMProviderRegistry
agent_instances: dict[str, BaseAgent] = {}
agent_registry: dict[str, AgentConfig] = {}
```

Removed: `agent_pools`, `worker_sessions`, `dispatcher`.
Added: `agent_instances`.

- [ ] **Step 2: Commit**

```bash
git add sebastian/gateway/state.py
git commit -m "refactor(gateway): state 模块替换 agent_pools/dispatcher 为 agent_instances"
```

---

## Task 16: Gateway App — Replace Pool Initialization

**Files:**
- Modify: `sebastian/gateway/app.py`
- Test: Manual integration test

- [ ] **Step 1: Replace _initialize_a2a_and_pools**

Delete `_initialize_a2a_and_pools()` and `_register_runtime_agent_state_handlers()`. Replace with:

```python
def _initialize_agent_instances(
    agent_configs: list[AgentConfig],
    gate: PolicyGate,
    session_store: SessionStore,
    event_bus: EventBus,
) -> dict[str, BaseAgent]:
    """Create a singleton instance for each registered agent type."""
    instances: dict[str, BaseAgent] = {}
    for cfg in agent_configs:
        agent = cfg.agent_class(
            gate=gate,
            session_store=session_store,
            event_bus=event_bus,
            allowed_tools=cfg.allowed_tools,
            allowed_skills=cfg.allowed_skills,
        )
        agent.name = cfg.agent_type
        instances[cfg.agent_type] = agent
        logger.info("Registered agent instance: %s (%s)", cfg.agent_type, cfg.display_name)
    return instances
```

- [ ] **Step 2: Update lifespan function**

In the `lifespan()` function, replace the section that creates dispatcher/pools:

```python
# Remove:
# state.dispatcher = A2ADispatcher()
# agent_pools, worker_sessions = _initialize_a2a_and_pools(...)
# state.agent_pools = agent_pools
# state.worker_sessions = worker_sessions
# _register_runtime_agent_state_handlers(...)

# Replace with:
state.agent_instances = _initialize_agent_instances(
    agent_configs=agent_configs,
    gate=gate,
    session_store=state.session_store,
    event_bus=state.event_bus,
)
```

Remove the shutdown code that cancels worker loop tasks (they no longer exist).

Start the stalled watchdog (implemented in Task 17):

```python
from sebastian.core.stalled_watchdog import start_watchdog

watchdog_task = start_watchdog(
    index_store=state.index_store,
    session_store=state.session_store,
    event_bus=state.event_bus,
    agent_registry=state.agent_registry,
)
```

And cancel it on shutdown:

```python
# In the shutdown section:
watchdog_task.cancel()
```

- [ ] **Step 3: Remove A2A/AgentPool imports**

Remove all imports of `AgentPool`, `A2ADispatcher`, and related types from `app.py`.

- [ ] **Step 4: Run gateway startup test**

Run: `uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000`
Expected: Server starts without import errors.

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/app.py
git commit -m "refactor(gateway): app.py 用 _initialize_agent_instances 替代 pool/dispatcher 初始化"
```

---

## Task 17: Stalled Watchdog

**Files:**
- Create: `sebastian/core/stalled_watchdog.py`
- Test: `tests/unit/test_stalled_watchdog.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_stalled_watchdog.py
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from sebastian.core.stalled_watchdog import _check_stalled_sessions


@pytest.mark.asyncio
async def test_marks_stalled_session():
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "status": "active", "last_activity_at": old, "depth": 2},
    ])
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(return_value=MagicMock(
        id="s1", status="active", last_activity_at=now - timedelta(minutes=10),
    ))
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert len(stalled) == 1
    assert stalled[0] == "s1"
    session_store.update_session.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_stalled_watchdog.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the watchdog**

```python
# sebastian/core/stalled_watchdog.py
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

from sebastian.core.types import SessionStatus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 60


async def _check_stalled_sessions(
    index_store: IndexStore,
    session_store: SessionStore,
    event_bus: EventBus | None,
    agent_registry: dict[str, AgentConfig],
) -> list[str]:
    """Scan active sessions and mark stalled ones. Returns list of stalled session IDs."""
    now = datetime.now(UTC)
    all_sessions = await index_store.list_all()
    stalled_ids: list[str] = []

    for entry in all_sessions:
        if entry.get("status") != "active":
            continue

        agent_type = entry.get("agent_type", "")
        config = agent_registry.get(agent_type)
        threshold_minutes = config.stalled_threshold_minutes if config else 5

        last_activity_str = entry.get("last_activity_at", "")
        if not last_activity_str:
            continue

        try:
            last_activity = datetime.fromisoformat(last_activity_str)
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue

        if now - last_activity > timedelta(minutes=threshold_minutes):
            session_id = entry["id"]
            session = await session_store.get_session(session_id, agent_type)
            if session is None:
                continue

            session.status = SessionStatus.STALLED
            session.updated_at = now
            await session_store.update_session(session)
            await index_store.upsert(session)

            if event_bus is not None:
                await event_bus.publish(
                    Event(
                        type=EventType.SESSION_STALLED,
                        data={
                            "session_id": session_id,
                            "agent_type": agent_type,
                            "last_activity_at": last_activity_str,
                        },
                    )
                )

            stalled_ids.append(session_id)
            logger.warning("Session %s marked as stalled (inactive %s min)", session_id, threshold_minutes)

    return stalled_ids


async def _watchdog_loop(
    index_store: IndexStore,
    session_store: SessionStore,
    event_bus: EventBus | None,
    agent_registry: dict[str, Any],
) -> None:
    """Background loop that periodically checks for stalled sessions."""
    while True:
        try:
            await _check_stalled_sessions(index_store, session_store, event_bus, agent_registry)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Stalled watchdog error")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


def start_watchdog(
    index_store: IndexStore,
    session_store: SessionStore,
    event_bus: EventBus | None,
    agent_registry: dict[str, Any],
) -> asyncio.Task[None]:
    """Start the stalled-detection watchdog as a background task."""
    return asyncio.create_task(
        _watchdog_loop(index_store, session_store, event_bus, agent_registry),
        name="stalled_watchdog",
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_stalled_watchdog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/stalled_watchdog.py tests/unit/test_stalled_watchdog.py
git commit -m "feat(core): stalled watchdog — 后台扫描标记卡住的 session"
```

---

## Task 18: Sebastian Orchestrator — Remove intervene, Update Routing

**Files:**
- Modify: `sebastian/orchestrator/sebas.py`
- Test: `tests/unit/test_sebas.py`

- [ ] **Step 1: Update Sebastian class**

1. **Remove `intervene` method** entirely.

2. **Update `get_or_create_session`** — remove `agent_id`:

```python
async def get_or_create_session(
    self,
    session_id: str | None = None,
    first_message: str = "",
) -> Session:
    if session_id:
        session = await self._session_store.get_session(session_id, "sebastian")
        if session:
            return session

    session = Session(
        agent_type="sebastian",
        title=first_message[:40] or "新对话",
        depth=1,
    )
    await self._session_store.create_session(session)

    import sebastian.gateway.state as _state
    await _state.index_store.upsert(session)

    return session
```

3. **Update `_agents_section`** to use `display_name`:

```python
def _agents_section(self, agent_registry: dict[str, object] | None = None) -> str:
    registry = agent_registry or self._agent_registry
    if not registry:
        return ""
    lines = ["## Available Sub-Agents", ""]
    for config in registry.values():
        display = getattr(config, "display_name", config.agent_type)
        desc = getattr(config, "description", "")
        lines.append(f"- **{config.agent_type}** ({display}): {desc}")
    lines.append("")
    lines.append("Use the `delegate_to_agent` tool to assign tasks to these agents.")
    return "\n".join(lines)
```

- [ ] **Step 2: Run existing Sebastian tests**

Run: `pytest tests/unit/test_sebas.py -v` (if exists)
Fix any failures from removed `agent_id` and `intervene`.

- [ ] **Step 3: Commit**

```bash
git add sebastian/orchestrator/sebas.py
git commit -m "refactor(orchestrator): Sebastian 移除 intervene，get_or_create_session 不再用 agent_id"
```

---

## Task 19: Gateway Routes — Sessions (Direct Agent Routing + New Endpoint)

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`

- [ ] **Step 1: Update _schedule_session_turn — direct agent routing**

Replace the current routing logic:

```python
async def _schedule_session_turn(
    session: Session,
    content: str,
) -> None:
    """Route a turn to the correct agent instance."""
    import sebastian.gateway.state as state

    if session.agent_type == "sebastian":
        asyncio.create_task(
            state.sebastian.run_streaming(content, session.id)
        )
    else:
        agent = state.agent_instances.get(session.agent_type)
        if agent is None:
            raise ValueError(f"No agent instance for type: {session.agent_type}")
        asyncio.create_task(
            agent.run_streaming(content, session.id, agent_name=session.agent_type)
        )
```

- [ ] **Step 2: Update _resolve_session — no agent_id**

In `_resolve_session`, update the session lookup to not use `agent_id`:

```python
async def _resolve_session(state, session_id: str) -> Session:
    entries = await state.index_store.list_all()
    entry = next((e for e in entries if e["id"] == session_id), None)
    if entry is None:
        raise HTTPException(404, "Session not found")
    session = await state.session_store.get_session(session_id, entry["agent_type"])
    if session is None:
        raise HTTPException(404, "Session data not found")
    return session
```

- [ ] **Step 3: Add POST /agents/{agent_type}/sessions endpoint**

```python
@router.post("/agents/{agent_type}/sessions")
async def create_agent_session(agent_type: str, body: dict):
    """Create a new conversation with a sub-agent."""
    import sebastian.gateway.state as state

    if agent_type not in state.agent_instances:
        raise HTTPException(404, f"Agent type not found: {agent_type}")

    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content is required")

    session = Session(
        agent_type=agent_type,
        title=content[:40],
        depth=2,
    )
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    agent = state.agent_instances[agent_type]

    from sebastian.core.session_runner import run_agent_session

    asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=content,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )

    return {"session_id": session.id, "ts": session.created_at.isoformat()}
```

- [ ] **Step 4: Add GET /sessions/{session_id}/recent endpoint**

```python
@router.get("/sessions/{session_id}/recent")
async def get_session_recent(session_id: str, limit: int = 5):
    """HTTP version of inspect_session — returns recent messages + status."""
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    messages = await state.session_store.get_messages(
        session_id, session.agent_type, limit=limit,
    )
    return {
        "session_id": session.id,
        "status": session.status,
        "title": session.title,
        "last_activity_at": session.last_activity_at.isoformat(),
        "messages": messages,
    }
```

- [ ] **Step 5: Remove list_worker_sessions route**

Delete the route that serves `GET /agents/{agent_type}/workers/{agent_id}/sessions`.

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/sessions.py
git commit -m "refactor(gateway): session turns 直接路由到 agent 实例；新增 POST /agents/{type}/sessions + GET /sessions/{id}/recent"
```

---

## Task 20: Gateway Routes — Agents (New Response Format)

**Files:**
- Modify: `sebastian/gateway/routes/agents.py`

- [ ] **Step 1: Update list_agents response**

Replace the current worker-based response with:

```python
@router.get("/agents")
async def list_agents():
    import sebastian.gateway.state as state

    agents = []
    for agent_type, config in state.agent_registry.items():
        if agent_type == "sebastian":
            continue

        # Count active depth=2 and depth=3 sessions for this agent
        sessions = await state.index_store.list_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")

        agents.append({
            "agent_type": agent_type,
            "name": config.display_name,
            "description": config.description,
            "active_session_count": active_count,
            "max_children": config.max_children,
        })

    return {"agents": agents}
```

- [ ] **Step 2: Commit**

```bash
git add sebastian/gateway/routes/agents.py
git commit -m "refactor(gateway): agents 接口返回 active_session_count/max_children，移除 workers"
```

---

## Task 21: Frontend — Types & API Updates

**Files:**
- Modify: `ui/mobile/src/types.ts`
- Modify: `ui/mobile/src/api/sessions.ts`
- Modify: `ui/mobile/src/api/agents.ts`

- [ ] **Step 1: Update SessionMeta type**

In `ui/mobile/src/types.ts`:

```typescript
export interface SessionMeta {
  id: string;
  agent: string;
  title: string;
  status: 'active' | 'idle' | 'completed' | 'failed' | 'stalled' | 'cancelled' | 'archived';
  updated_at: string;
  task_count: number;
  active_task_count: number;
  depth: number;
  parent_session_id: string | null;
  last_activity_at: string;
}
```

- [ ] **Step 2: Update Agent type**

```typescript
export type AgentStatus = 'idle' | 'working';

export interface Agent {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  active_session_count: number;
  max_children: number;
}
```

- [ ] **Step 3: Add SSE event types**

Add to `SSEEventType`:

```typescript
| 'session.completed'
| 'session.failed'
| 'session.stalled'
```

- [ ] **Step 4: Update BackendSessionMeta in sessions.ts**

```typescript
interface BackendSessionMeta {
  id: string;
  agent_type: string;
  title: string;
  status: SessionMeta['status'];
  updated_at: string;
  task_count: number;
  active_task_count: number;
  depth: number;
  parent_session_id: string | null;
  last_activity_at: string;
}
```

Update `mapSessionMeta`:

```typescript
function mapSessionMeta(session: BackendSessionMeta): SessionMeta {
  return {
    id: session.id,
    agent: session.agent_type,
    title: session.title,
    status: session.status,
    updated_at: session.updated_at,
    task_count: session.task_count,
    active_task_count: session.active_task_count,
    depth: session.depth,
    parent_session_id: session.parent_session_id,
    last_activity_at: session.last_activity_at,
  };
}
```

- [ ] **Step 5: Add createAgentSession function**

```typescript
export async function createAgentSession(
  agent: string,
  content: string,
): Promise<{ sessionId: string; ts: string }> {
  const { data } = await apiClient.post<{ session_id: string; ts: string }>(
    `/api/v1/agents/${agent}/sessions`,
    { content },
  );
  return { sessionId: data.session_id, ts: data.ts };
}
```

- [ ] **Step 6: Update agents.ts**

```typescript
interface BackendAgentSummary {
  agent_type: string;
  name: string;
  description: string;
  active_session_count: number;
  max_children: number;
}

interface BackendAgentsResponse {
  agents: BackendAgentSummary[];
}

function mapAgentSummary(agent: BackendAgentSummary): Agent {
  return {
    id: agent.agent_type,
    name: agent.name || agent.agent_type,
    description: agent.description,
    status: agent.active_session_count > 0 ? 'working' : 'idle',
    active_session_count: agent.active_session_count,
    max_children: agent.max_children,
  };
}
```

- [ ] **Step 7: Commit**

```bash
cd ui/mobile
git add src/types.ts src/api/sessions.ts src/api/agents.ts
git commit -m "feat(mobile): 类型和 API 适配三层架构 — SessionMeta/Agent 新增字段，createAgentSession"
```

---

## Task 22: Frontend — EditIcon + NewChatFAB Component

**Files:**
- Modify: `ui/mobile/src/components/common/Icons.tsx`
- Create: `ui/mobile/src/components/common/NewChatFAB.tsx`

- [ ] **Step 1: Add EditIcon to Icons.tsx**

Add after the existing icons:

```typescript
// Path data from src/assets/icons/edit.svg
export function EditIcon({ size = 16, color = '#fff', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M772.181333 141.482667a37.12 37.12 0 0 0-5.290666 0.341333c-13.909333 0-26.069333 6.954667-34.730667 17.408l-219.306667 260.906667a164.821333 164.821333 0 0 0-26.026666 45.226666l-41.813334 142.677334a29.738667 29.738667 0 0 0 8.746667 34.773333 33.237333 33.237333 0 0 0 20.864 6.954667c5.205333 0 10.453333-1.706667 13.994667-5.205334l135.594666-64.384h1.706667c15.701333-8.661333 29.696-19.114667 40.106667-33.024l217.386666-257.450666c19.2-20.906667 15.744-53.973333-5.205333-71.338667L803.413333 154.026667c-9.045333-7.552-19.498667-12.501333-31.232-12.501334m-0.298666 69.845334l54.485333 46.805333-209.28 247.722667-1.194667 1.408-1.066666 1.493333a52.224 52.224 0 0 1-12.416 10.965333l-5.546667 2.645334-69.717333 33.066666 20.138666-68.906666c4.394667-10.368 9.386667-19.114667 14.592-25.173334l210.005334-250.026666"
        fill={color}
      />
      <Path
        d="M442.624 174.634667a32 32 0 0 1 4.309333 63.701333l-4.309333 0.298667H296.192a136.149333 136.149333 0 0 0-135.978667 128.426666l-0.213333 7.68v339.626667a136.106667 136.106667 0 0 0 128.426667 135.936l7.765333 0.213333H635.733333a136.106667 136.106667 0 0 0 135.850667-128.426666l0.213333-7.722667v-95.573333a32 32 0 0 1 63.701334-4.309334l0.298666 4.352v95.530667a200.106667 200.106667 0 0 1-190.933333 199.936l-9.130667 0.213333H296.106667a200.106667 200.106667 0 0 1-199.936-190.976l-0.213334-9.173333v-339.626667a200.149333 200.149333 0 0 1 191.018667-199.893333l9.173333-0.213333h146.432zM678.954667 224.085333a32 32 0 0 1 41.088-7.381333l3.882666 2.688 100.053334 81.152a32 32 0 0 1-36.394667 52.394667l-3.882667-2.688-100.053333-81.152a32 32 0 0 1-4.693333-45.013334z"
        fill={color}
      />
    </Svg>
  );
}
```

- [ ] **Step 2: Create NewChatFAB component**

```typescript
// ui/mobile/src/components/common/NewChatFAB.tsx
import { StyleSheet, Text, TouchableOpacity } from 'react-native';
import type { ViewStyle } from 'react-native';
import { EditIcon } from './Icons';

interface Props {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  style?: ViewStyle;
}

export function NewChatFAB({ label, onPress, disabled = false, style }: Props) {
  return (
    <TouchableOpacity
      style={[styles.fab, disabled && styles.fabDisabled, style]}
      onPress={disabled ? undefined : onPress}
      disabled={disabled}
      activeOpacity={0.85}
    >
      <EditIcon size={16} color="#fff" style={styles.icon} />
      <Text style={styles.label}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  fab: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#111111',
    borderRadius: 22,
    paddingVertical: 12,
    paddingHorizontal: 20,
    elevation: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
  fabDisabled: {
    backgroundColor: '#888888',
    opacity: 0.6,
  },
  icon: {
    marginRight: 8,
  },
  label: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
});
```

- [ ] **Step 3: Commit**

```bash
cd ui/mobile
git add src/components/common/Icons.tsx src/components/common/NewChatFAB.tsx
git commit -m "feat(mobile): EditIcon + NewChatFAB 悬浮新对话按钮组件"
```

---

## Task 23: Frontend — AppSidebar Refactor

**Files:**
- Modify: `ui/mobile/src/components/chat/AppSidebar.tsx`

- [ ] **Step 1: Replace footer with floating NewChatFAB**

1. Import `NewChatFAB`:

```typescript
import { NewChatFAB } from '../common/NewChatFAB';
```

2. Remove the entire `{/* New chat button */}` footer section (lines 101-111).

3. Add `NewChatFAB` as a floating element inside the container, after the `historySection` View:

```typescript
<NewChatFAB
  label="新对话"
  onPress={onNewChat}
  disabled={draftSession}
  style={styles.fab}
/>
```

4. Remove the `footer`, `newChatBtn`, `newChatBtnDisabled`, `newChatBtnText` styles.

5. Add `fab` style:

```typescript
fab: {
  position: 'absolute',
  bottom: 24,
  right: 16,
},
```

6. Remove `paddingBottom` constraint from footer (no longer exists). The `historySection` should now use `flex: 1` to fill remaining space (it already does).

- [ ] **Step 2: Verify layout**

Start the app and check:
- Sidebar opens, session list fills the space below features
- NewChatFAB floats at bottom-right over the list
- When `draftSession` is true, FAB appears grayed out
- Tapping FAB triggers `onNewChat`

- [ ] **Step 3: Commit**

```bash
cd ui/mobile
git add src/components/chat/AppSidebar.tsx
git commit -m "refactor(mobile): 侧边栏新对话按钮改为悬浮 NewChatFAB"
```

---

## Task 24: Frontend — Sub-agent Session List + FAB

**Files:**
- Modify: `ui/mobile/app/subagents/[agentId].tsx`
- Modify: `ui/mobile/src/components/subagents/SessionList.tsx`

- [ ] **Step 1: Add NewChatFAB to [agentId].tsx**

Import and add the FAB:

```typescript
import { NewChatFAB } from '../../src/components/common/NewChatFAB';
```

Add a handler:

```typescript
function handleNewChat() {
  router.push(`/subagents/session/new?agent=${normalizedAgentId}`);
}
```

Add the FAB in the return JSX, as the last child of the outer `<View>`:

```typescript
<NewChatFAB
  label="新对话"
  onPress={handleNewChat}
  style={styles.fab}
/>
```

Add style:

```typescript
fab: {
  position: 'absolute',
  bottom: 24,
  right: 16,
},
```

- [ ] **Step 2: Add depth badge to SessionList**

In `SessionList.tsx`, add a depth=3 badge to the card:

```typescript
{item.depth === 3 && (
  <View style={styles.subTaskBadge}>
    <Text style={styles.subTaskBadgeText}>子任务</Text>
  </View>
)}
```

Add to the `topRow` section, after the existing `badge`. Add styles:

```typescript
subTaskBadge: {
  paddingHorizontal: 8,
  paddingVertical: 3,
  borderRadius: 999,
  backgroundColor: '#FFF3E0',
  marginLeft: 6,
},
subTaskBadgeText: {
  fontSize: 11,
  fontWeight: '600',
  color: '#E65100',
},
```

Also update `StatusDot` to include `stalled` status color:

```typescript
function StatusDot({ status }: { status: SessionMeta['status'] }) {
  const color =
    status === 'active' ? '#34C759'
    : status === 'stalled' ? '#FF9500'
    : status === 'idle' ? '#999999'
    : '#CCCCCC';
  return <View style={[styles.dot, { backgroundColor: color }]} />;
}
```

- [ ] **Step 3: Commit**

```bash
cd ui/mobile
git add app/subagents/\\[agentId\\].tsx src/components/subagents/SessionList.tsx
git commit -m "feat(mobile): sub-agent session 列表新增 NewChatFAB + depth=3 子任务标签 + stalled 状态"
```

---

## Task 25: Frontend — Sub-agent Session Detail (Lazy Creation)

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

- [ ] **Step 1: Handle id=new for lazy session creation**

Update the component to handle the `new` case:

```typescript
import { createAgentSession } from '../../../src/api/sessions';

// At the top of the component:
const isNewSession = sessionId === 'new';
const [realSessionId, setRealSessionId] = useState<string | null>(null);
const effectiveSessionId = realSessionId || (isNewSession ? null : sessionId);
```

Update `handleSend`:

```typescript
const handleSend = useCallback(
  async (text: string) => {
    if (isMockSession) {
      Alert.alert('模拟会话', '这是用于导航测试的假数据页面。');
      return;
    }
    setSending(true);
    try {
      if (isNewSession && !realSessionId) {
        // First message: create the session via API
        const { sessionId: newId } = await createAgentSession(agentName, text);
        setRealSessionId(newId);
        // Replace route so back button doesn't return to "new"
        router.replace(`/subagents/session/${newId}?agent=${agentName}`);
        // Connect SSE for the new session
        useConversationStore.getState().appendUserMessage(newId, text);
      } else {
        const sid = effectiveSessionId!;
        await sendTurnToSession(sid, text, agentName);
        useConversationStore.getState().appendUserMessage(sid, text);
        queryClient.invalidateQueries({
          queryKey: ['session-detail', sid, agentName],
        });
      }
    } catch {
      Alert.alert('发送失败，请重试');
    } finally {
      setSending(false);
    }
  },
  [agentName, effectiveSessionId, isMockSession, isNewSession, queryClient, realSessionId, router],
);
```

Update queries to skip when `isNewSession && !realSessionId`:

```typescript
const { data: remoteDetail } = useQuery({
  queryKey: ['session-detail', effectiveSessionId, agentName],
  queryFn: () => getSessionDetail(effectiveSessionId!, agentName),
  enabled: !!effectiveSessionId && !isMockSession,
});
```

Update the title display for new sessions:

```typescript
<Text style={styles.title} numberOfLines={1}>
  {isNewSession && !realSessionId ? '新对话' : (detail?.session.title ?? '会话详情')}
</Text>
```

Update ConversationView sessionId:

```typescript
<ConversationView sessionId={isMockSession ? null : effectiveSessionId} />
```

- [ ] **Step 2: Verify the flow**

Test manually:
1. Navigate to sub-agent session list
2. Tap "新对话" FAB → lands on empty conversation page titled "新对话"
3. Type and send first message → API creates session → URL changes → conversation starts
4. Press back → session list shows the new session
5. Navigate to session list, press back without sending → no empty session created

- [ ] **Step 3: Commit**

```bash
cd ui/mobile
git add app/subagents/session/\\[id\\].tsx
git commit -m "feat(mobile): sub-agent session 详情页支持 lazy creation — id=new 时首条消息才创建"
```

---

## Task 26: Integration Verification

- [ ] **Step 1: Run full backend test suite**

```bash
pytest tests/ -v --ignore=tests/e2e
```

Fix any remaining failures from the architecture change.

- [ ] **Step 2: Run lint**

```bash
ruff check sebastian/ tests/
ruff format sebastian/ tests/
mypy sebastian/
```

- [ ] **Step 3: Start gateway and verify**

```bash
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
```

Test endpoints:
- `GET /api/v1/agents` — should return agents without workers array
- `POST /api/v1/agents/code/sessions` — should create session and return session_id
- `POST /api/v1/sessions/{id}/turns` — should route directly to agent

- [ ] **Step 4: Start mobile app and verify**

```bash
cd ui/mobile && npx expo start
```

Test flows:
- Main chat: sidebar NewChatFAB works, sessions list fills space
- Sub-agents: session list shows, "新对话" FAB visible
- New session flow: tap FAB → empty page → send message → session created
- Stalled badge: if any session is stalled, orange dot shows

- [ ] **Step 5: Update README files**

Update the following READMEs to reflect the architecture change:
- `sebastian/README.md`: Remove AgentPool references, update module descriptions
- `sebastian/core/README.md`: Remove agent_pool.py, add session_runner.py and stalled_watchdog.py
- `sebastian/capabilities/README.md`: Document new tools (delegate_to_agent, spawn_sub_agent, check_sub_agents, inspect_session)
- `sebastian/gateway/README.md`: Update state description, new endpoint
- `sebastian/protocol/README.md`: Mark A2A as removed
- `ui/mobile/README.md`: Document NewChatFAB, lazy session creation

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "docs: README 更新适配三层 Agent 架构"
```

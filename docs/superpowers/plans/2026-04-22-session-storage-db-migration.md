# Session Storage SQLite Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Sebastian session, timeline, task, checkpoint, and per-session todo storage from filesystem JSON/JSONL into SQLite, with timeline-first context APIs and no `IndexStore`/old `EpisodicMemory` runtime dependency.

**Architecture:** SQLite becomes the only runtime truth for sessions. `SessionStore` remains the public facade, but delegates to focused helpers for records, timeline, context projection, tasks, and todos. BaseAgent uses `get_context_messages()` at turn start and a turn-local pending timeline buffer during streaming/tool loops, then flushes canonical `session_items` at turn completion or interruption.

**Tech Stack:** Python 3.12, SQLAlchemy async, SQLite, FastAPI, pytest/pytest-asyncio, ruff.

---

## Source Spec

- Design: `docs/superpowers/specs/2026-04-22-session-storage-db-migration-design.md`
- Branch: `feat/session-storage-sqlite`
- Important rule: this migration does **not** import old `~/.sebastian/sessions/` test data.

## File Structure

Create:

- `sebastian/store/session_records.py` — session row CRUD, list queries, active child queries, activity updates.
- `sebastian/store/session_timeline.py` — `session_items` CRUD, `next_item_seq` allocation, archive/context/recent/since views.
- `sebastian/store/session_context.py` — project canonical timeline items into Anthropic/OpenAI provider messages and legacy UI messages.
- `sebastian/store/session_tasks.py` — session-scoped Task/Checkpoint CRUD plus task count refresh.
- `sebastian/store/session_todos.py` — SQLite-backed per-session todo read/write.
- `tests/unit/store/test_session_records.py`
- `tests/unit/store/test_session_timeline.py`
- `tests/unit/store/test_session_context.py`
- `tests/unit/store/test_session_tasks.py`
- `tests/unit/store/test_session_todos_sqlite.py`

Modify:

- `sebastian/store/models.py` — add `SessionRecord`, `SessionItemRecord`, `SessionTodoRecord`; add columns to existing records.
- `sebastian/store/database.py` — add idempotent schema patches and indexes.
- `sebastian/store/session_store.py` — replace file implementation with facade composed from helper modules.
- `sebastian/store/todo_store.py` — either delete after call sites migrate, or turn into a thin DB-backed wrapper.
- `sebastian/store/task_store.py` — delete, deprecate, or delegate to `session_tasks.py`; no independent task write path.
- `sebastian/store/index_store.py` — remove from runtime; if deletion is too disruptive in one task, temporarily keep a compatibility wrapper that delegates to `SessionStore`.
- `sebastian/core/base_agent.py` — remove `_episodic`, use context API and timeline flush.
- `sebastian/core/agent_loop.py` — keep provider-specific working state; ensure timeline metadata can be produced by BaseAgent.
- `sebastian/core/task_manager.py`
- `sebastian/core/session_runner.py`
- `sebastian/core/stalled_watchdog.py`
- `sebastian/gateway/app.py`
- `sebastian/gateway/state.py`
- `sebastian/gateway/routes/sessions.py`
- `sebastian/gateway/routes/turns.py`
- `sebastian/gateway/routes/stream.py`
- `sebastian/gateway/routes/debug.py`
- `sebastian/gateway/completion_notifier.py`
- `sebastian/capabilities/tools/inspect_session/__init__.py`
- `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`
- `sebastian/capabilities/tools/resume_agent/__init__.py`
- `sebastian/capabilities/tools/delegate_to_agent/__init__.py`
- `sebastian/capabilities/tools/stop_agent/__init__.py`
- `sebastian/memory/consolidation.py`
- `sebastian/memory/README.md`
- `sebastian/store/README.md`
- `sebastian/gateway/README.md`
- `sebastian/core/README.md`
- Relevant tests that instantiate `SessionStore`, `IndexStore`, `TodoStore`, or mock `EpisodicMemory`.

Delete after callers are migrated:

- `sebastian/memory/episodic_memory.py`
- `sebastian/store/index_store.py` if no compatibility wrapper remains.

## Test Fixtures

Before the first implementation task, create or reuse a small in-memory SQLite fixture for store tests. Keep it local to `tests/unit/store/conftest.py` unless a broader fixture already exists.

Example fixture shape:

```python
@pytest.fixture
async def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
```

Use `SessionStore(db_factory=factory)` or equivalent final constructor in new tests. If the facade must temporarily accept `sessions_dir` for call-site compatibility, tests should still inject DB explicitly.

---

### Task 1: Schema And Store Test Fixture

**Files:**
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/store/database.py`
- Create: `tests/unit/store/conftest.py`
- Test: `tests/unit/store/test_session_records.py`

- [ ] **Step 1: Write failing model/fixture smoke test**

Add a test that creates all tables and asserts the new tables/columns exist.

```python
async def test_session_storage_tables_exist(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        rows = await session.execute(sqlalchemy.text("PRAGMA table_info(sessions)"))
        columns = {row[1] for row in rows.fetchall()}
        assert {"id", "agent_type", "next_item_seq"}.issubset(columns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_session_records.py::test_session_storage_tables_exist -q`

Expected: FAIL because `sessions` does not exist yet.

- [ ] **Step 3: Add ORM records**

In `models.py`, add:

- `SessionRecord` with composite primary key `(agent_type, id)`.
- `SessionItemRecord` with UUID `id`, `(agent_type, session_id, seq)` uniqueness, timeline fields.
- `SessionTodoRecord` with composite primary key `(agent_type, session_id)`.
- Add `agent_type` to `TaskRecord`.
- Add `agent_type` and `session_id` to `CheckpointRecord`.
- Add `last_seen_item_seq`, `last_consolidated_source_seq`, and `consolidation_mode` to `SessionConsolidationRecord`.
- Preserve/add `last_consolidated_seq` in `SessionConsolidationRecord` and include it in the schema smoke test, because the spec keeps it for compatibility alongside the newer cursor fields.

- [ ] **Step 4: Add idempotent migrations**

In `database.py`, extend `_apply_idempotent_migrations()`:

- Add missing columns to `tasks`, `checkpoints`, and `session_consolidations`.
- Add `CREATE INDEX IF NOT EXISTS` statements for session/timeline query paths.
- Do not assume old test DBs have clean rows.

- [ ] **Step 5: Run focused schema tests**

Run: `pytest tests/unit/store/test_session_records.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py tests/unit/store/conftest.py tests/unit/store/test_session_records.py
git commit -m "feat(store): 新增 session SQLite schema"
```

### Task 2: Session Records Helper

**Files:**
- Create: `sebastian/store/session_records.py`
- Modify: `sebastian/store/session_store.py`
- Test: `tests/unit/store/test_session_records.py`

- [ ] **Step 1: Write failing CRUD/list tests**

Cover:

- `create_session()` then `get_session()`.
- `update_session()`.
- `list_sessions()`.
- `list_sessions_by_agent_type()`.
- `list_active_children()`.
- `update_activity()` transitions `stalled` to `active`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/store/test_session_records.py -q`

Expected: FAIL because `SessionStore` still reads files.

- [ ] **Step 3: Implement `SessionRecordsStore`**

Create helper methods:

- `create(session: Session) -> Session`
- `get(session_id: str, agent_type: str) -> Session | None`
- `update(session: Session) -> None`
- `delete(session: Session) -> None`
- `list_all() -> list[dict[str, Any]]`
- `list_by_agent_type(agent_type: str) -> list[dict[str, Any]]`
- `list_active_children(agent_type: str, parent_session_id: str) -> list[dict[str, Any]]`
- `update_activity(session_id: str, agent_type: str | None = None) -> None`

- [ ] **Step 4: Wire facade methods**

Update `SessionStore` to delegate session metadata/list/activity methods to `SessionRecordsStore`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/store/test_session_records.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/session_records.py sebastian/store/session_store.py tests/unit/store/test_session_records.py
git commit -m "feat(store): 将 session 元数据切到 SQLite"
```

### Task 3: Timeline Append And Views

**Files:**
- Create: `sebastian/store/session_timeline.py`
- Modify: `sebastian/store/session_store.py`
- Test: `tests/unit/store/test_session_timeline.py`

- [ ] **Step 1: Write failing timeline tests**

Cover:

- `append_timeline_items()` assigns contiguous `seq`.
- `sessions.next_item_seq` advances.
- `append_message(role="user")` creates `user_message`.
- `append_message(role="assistant", blocks=[...])` creates `thinking`, `assistant_message`, `tool_call`/`tool_result` or `raw_block`.
- `get_context_timeline_items()` excludes archived items and includes `context_summary`.
- `get_timeline_items(include_archived=True)` returns full history.
- `get_recent_timeline_items(limit=25)` returns unarchived recent items in ascending order.
- concurrent append test: no duplicate seq.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/store/test_session_timeline.py -q`

Expected: FAIL because timeline helper does not exist.

- [ ] **Step 3: Define timeline item app shape**

Use a small `TypedDict` or dataclass in `session_timeline.py` for internal conversion:

```python
class TimelineItemInput(TypedDict, total=False):
    kind: str
    role: str | None
    content: str
    payload: dict[str, Any]
    turn_id: str | None
    provider_call_index: int | None
    block_index: int | None
    effective_seq: int | None
```

- [ ] **Step 4: Implement atomic seq allocation**

Implement `append_items()` using `sessions.next_item_seq` as fact source.

Required behavior:

- Use one DB transaction.
- Prefer SQLite `UPDATE ... RETURNING`.
- If fallback is needed, use SQLite-level transaction locking such as `BEGIN IMMEDIATE`; never rely on only `asyncio.Lock`.
- Set `effective_seq = seq` unless caller provides another value.
- Retry limited times on `IntegrityError`.

- [ ] **Step 5: Implement timeline queries**

Implement:

- `get_context_items()` ordered by `(effective_seq, seq)`.
- `get_items(include_archived=True)` ordered by real `seq`.
- `get_recent_items(limit=25)` using descending query then return ascending.
- `get_items_since(after_seq, include_kinds=...)`.

- [ ] **Step 6: Implement `append_message()` adapter**

Adapter rules:

- user -> `user_message`.
- system -> `system_event`.
- plain assistant -> `assistant_message`.
- assistant blocks -> split known blocks; unknown -> `raw_block`.

- [ ] **Step 7: Run tests**

Run: `pytest tests/unit/store/test_session_timeline.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/session_timeline.py sebastian/store/session_store.py tests/unit/store/test_session_timeline.py
git commit -m "feat(store): 新增 session timeline SQLite 读写"
```

### Task 4: Provider Context Projection

**Files:**
- Create: `sebastian/store/session_context.py`
- Modify: `sebastian/store/session_store.py`
- Test: `tests/unit/store/test_session_context.py`

- [ ] **Step 1: Write failing context projection tests**

Cover:

- Default context excludes `thinking`.
- Anthropic projection builds assistant content blocks and user `tool_result` blocks.
- OpenAI projection builds assistant `tool_calls` and `role="tool"` messages.
- `include_thinking=True` preserves Anthropic `payload.signature`.
- `context_summary` appears at `effective_seq` position.
- legacy UI messages are role/content only and do not contain provider-specific blocks.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/store/test_session_context.py -q`

Expected: FAIL because formatter does not exist.

- [ ] **Step 3: Implement projection helper**

Create functions/classes:

- `build_context_messages(items, provider_format, include_thinking=False)`
- `build_legacy_messages(items)`

Rules:

- Sort provider context by `(effective_seq, seq)`.
- Use `turn_id`, `provider_call_index`, `block_index` to group blocks.
- OpenAI tool calls from the same provider call stay in one assistant message.
- Tool result uses `payload.model_content`.
- `payload.display` is UI/debug only.

- [ ] **Step 4: Wire `SessionStore.get_context_messages()`**

Expose:

```python
async def get_context_messages(
    self,
    session_id: str,
    agent_type: str,
    provider_format: str,
    include_thinking: bool = False,
) -> list[dict[str, Any]]:
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/store/test_session_context.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/session_context.py sebastian/store/session_store.py tests/unit/store/test_session_context.py
git commit -m "feat(store): 添加 timeline 上下文投影"
```

### Task 5: Task And Checkpoint SQLite Path

**Files:**
- Create: `sebastian/store/session_tasks.py`
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/store/task_store.py`
- Test: `tests/unit/store/test_session_tasks.py`
- Update: existing `tests/unit/store/test_session_store.py`

- [ ] **Step 1: Write failing task/checkpoint tests**

Cover:

- `create_task()` writes DB.
- `get_task(session_id, task_id, agent_type)` is scoped.
- `list_tasks()` is session scoped.
- `update_task_status()` updates terminal `completed_at`.
- `append_checkpoint()` / `get_checkpoints()` are session/agent scoped.
- session `task_count` and `active_task_count` refresh.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/store/test_session_tasks.py -q`

Expected: FAIL because facade still writes files.

- [ ] **Step 3: Implement `SessionTaskStore`**

Implement DB CRUD using existing `Task` and `Checkpoint` Pydantic types.

- [ ] **Step 4: Retire old `TaskStore` path**

Choose one:

- Delete `task_store.py` if no runtime imports remain.
- Or make it a thin compatibility wrapper that delegates to `SessionTaskStore`.

Do not leave a second independent task write implementation.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/store/test_session_tasks.py tests/unit/store/test_session_store.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/session_tasks.py sebastian/store/session_store.py sebastian/store/task_store.py tests/unit/store/test_session_tasks.py tests/unit/store/test_session_store.py
git commit -m "feat(store): 将 task checkpoint 切到 SQLite"
```

### Task 6: SQLite Todo Store

**Files:**
- Create: `sebastian/store/session_todos.py`
- Modify: `sebastian/store/todo_store.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/core/base_agent.py`
- Test: `tests/unit/store/test_session_todos_sqlite.py`
- Update: `tests/unit/store/test_todo_store.py`
- Update: `tests/unit/capabilities/test_todo_write_tool.py`
- Update: `tests/unit/core/test_base_agent_memory.py`

- [ ] **Step 1: Write failing DB todo tests**

Cover:

- missing todo returns `[]`.
- write/read roundtrip.
- overwrite.
- agent/session isolation.
- no filesystem directories are created.
- BaseAgent todo section reads from DB-backed todo store and does not create `todos.json`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/store/test_session_todos_sqlite.py -q`

Expected: FAIL because `TodoStore` writes files.

- [ ] **Step 3: Implement DB-backed todo store**

Either:

- Add `SessionTodoStore` and update gateway state to use it.
- Or rewrite `TodoStore` to accept DB factory and write `session_todos`.

Do not write `sessions/{agent_type}/{session_id}/todos.json`.

- [ ] **Step 4: Update todo tool tests**

Update tests to use DB fixture instead of tmp file directories.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/store/test_session_todos_sqlite.py tests/unit/store/test_todo_store.py tests/unit/capabilities/test_todo_write_tool.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/session_todos.py sebastian/store/todo_store.py sebastian/gateway/app.py sebastian/gateway/state.py sebastian/core/base_agent.py tests/unit/store/test_session_todos_sqlite.py tests/unit/store/test_todo_store.py tests/unit/capabilities/test_todo_write_tool.py tests/unit/core/test_base_agent_memory.py
git commit -m "feat(store): 将 session todo 切到 SQLite"
```

### Task 7: Remove IndexStore Runtime Dependency

**Files:**
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/core/task_manager.py`
- Modify: `sebastian/core/session_runner.py`
- Modify: `sebastian/core/stalled_watchdog.py`
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/gateway/routes/agents.py`
- Modify: `sebastian/memory/consolidation.py`
- Modify: sub-agent tools using `index_store`
- Modify: `sebastian/capabilities/tools/ask_parent/__init__.py`
- Modify: `sebastian/capabilities/tools/check_sub_agents/__init__.py`
- Modify: `sebastian/capabilities/tools/delegate_to_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/resume_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/stop_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/inspect_session/__init__.py`
- Test: `tests/unit/store/test_activity_sync.py`
- Test: `tests/unit/store/test_index_store.py` and related tests, either delete or rewrite.
- Test: core/runtime tests that instantiate `IndexStore`.
- Test: `tests/integration/test_memory_catchup_sweep.py`

- [ ] **Step 1: Write failing/no-IndexStore tests**

Add or update a focused test that constructs gateway/core dependencies without `IndexStore`.

- [ ] **Step 2: Search all runtime imports**

Run: `rg "IndexStore|index_store" sebastian tests -n`

Expected: find all remaining call sites before editing.

- [ ] **Step 3: Move methods to SessionStore call sites**

Replace:

- `index_store.upsert(session)` -> `session_store.update_session(session)` or no-op if already persisted.
- `index_store.update_activity(session_id)` -> `session_store.update_activity(session_id, agent_type?)`.
- `index_store.list_active_children(...)` -> `session_store.list_active_children(...)`.
- `index_store.list_*` -> `session_store.list_*`.
- `prune_orphans()` -> delete call.

- [ ] **Step 4: Remove gateway state field**

Remove `state.index_store` and constructor injection where possible.

- [ ] **Step 5: Decide fate of `index_store.py`**

If no runtime imports remain:

- Delete `sebastian/store/index_store.py`.
- Delete or rewrite old index tests.

If many tests still need transition:

- Keep a deprecated wrapper for one task only, delegating to `SessionStore`.
- Add a TODO in the plan notes to delete it in Task 12.

- [ ] **Step 6: Run focused tests**

Run: `pytest tests/unit/store tests/unit/core/test_task_manager.py tests/unit/runtime/test_sebas.py tests/unit/core/test_stalled_watchdog.py tests/integration/test_memory_catchup_sweep.py -q`

Expected: PASS. Do not commit this task with known red tests. If unrelated BaseAgent context tests fail, narrow this command to the files changed in Task 7 and record the unrelated failures for Task 8.

- [ ] **Step 7: Commit**

```bash
git status --short
git add sebastian/gateway/app.py sebastian/gateway/state.py sebastian/orchestrator/sebas.py sebastian/core/base_agent.py sebastian/core/task_manager.py sebastian/core/session_runner.py sebastian/core/stalled_watchdog.py sebastian/gateway/routes/sessions.py sebastian/gateway/routes/agents.py sebastian/memory/consolidation.py
git add sebastian/capabilities/tools/ask_parent/__init__.py sebastian/capabilities/tools/check_sub_agents/__init__.py sebastian/capabilities/tools/delegate_to_agent/__init__.py sebastian/capabilities/tools/resume_agent/__init__.py sebastian/capabilities/tools/spawn_sub_agent/__init__.py sebastian/capabilities/tools/stop_agent/__init__.py sebastian/capabilities/tools/inspect_session/__init__.py
git add tests/unit/store/test_activity_sync.py tests/unit/store/test_index_store.py tests/unit/store/test_index_store_v2.py tests/unit/store/test_index_store_goal.py tests/unit/core/test_task_manager.py tests/unit/runtime/test_sebas.py tests/unit/core/test_stalled_watchdog.py tests/unit/core/test_session_runner.py tests/unit/core/test_session_runner_events.py tests/unit/core/test_base_agent_index_store.py tests/integration/test_memory_catchup_sweep.py
git commit -m "refactor(store): 移除 IndexStore 运行时依赖"
```

### Task 8: Replace Old EpisodicMemory Path In BaseAgent

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/core/agent_loop.py` only if needed for metadata access.
- Delete or rename: `sebastian/memory/episodic_memory.py`
- Modify: `sebastian/memory/store.py`
- Tests: `tests/unit/core/test_base_agent.py`
- Tests: `tests/unit/core/test_base_agent_provider.py`
- Tests: `tests/unit/core/test_base_agent_memory.py`
- Tests: `tests/unit/llm/test_thinking_duration.py`

- [ ] **Step 1: Write failing BaseAgent context tests**

Add tests that prove:

- BaseAgent calls `get_context_messages()` at turn start.
- It does not call `get_turns(limit=20)`.
- User input is written before stream starts.
- Assistant timeline items flush at `TurnDone`.
- partial cancel flushes pending items.
- tool loop second provider call uses turn-local working state, not DB reread.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/test_base_agent.py tests/unit/core/test_base_agent_provider.py -q`

Expected: FAIL because `_episodic` still exists.

- [ ] **Step 3: Remove `_episodic` from BaseAgent**

Replace:

- `_episodic.get_turns(limit=20)` with `session_store.get_context_messages(... provider_format=provider.message_format ...)`.
- `_episodic.add_turn()` with direct timeline writes.

Need access to provider format:

- Prefer adding a method/property on AgentLoop or LLM registry path that exposes current provider `message_format`.
- Do not guess provider format.

- [ ] **Step 4: Implement turn-local timeline buffer**

During `_stream_inner()`:

- Keep current provider-specific `working` behavior in `AgentLoop`.
- Buffer timeline item inputs with `turn_id`, `provider_call_index`, `block_index`.
- Flush at `TurnDone`.
- Flush partial assistant message on cancel/interruption.

- [ ] **Step 5: Delete or retire old `EpisodicMemory`**

If no imports remain:

- Delete `sebastian/memory/episodic_memory.py`.
- Update `sebastian/memory/store.py`.

If tests still need a protocol:

- Replace with a small test fake for `SessionStore`, not `EpisodicMemory`.

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/core/test_base_agent.py tests/unit/core/test_base_agent_provider.py tests/unit/core/test_base_agent_memory.py tests/unit/llm/test_thinking_duration.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git status --short
git add sebastian/core/base_agent.py sebastian/core/agent_loop.py sebastian/memory/episodic_memory.py sebastian/memory/store.py
git add tests/unit/core/test_base_agent.py tests/unit/core/test_base_agent_provider.py tests/unit/core/test_base_agent_memory.py tests/unit/llm/test_thinking_duration.py
git commit -m "refactor(core): 用 session timeline 替换旧 EpisodicMemory"
```

### Task 9: Gateway And Tool Read Path Migration

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/gateway/routes/turns.py`
- Modify: `sebastian/gateway/routes/stream.py`
- Modify: `sebastian/gateway/routes/debug.py`
- Modify: `sebastian/gateway/routes/agents.py`
- Modify: `sebastian/gateway/completion_notifier.py`
- Modify: `sebastian/capabilities/tools/inspect_session/__init__.py`
- Modify: `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/resume_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/delegate_to_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/stop_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/check_sub_agents/__init__.py`
- Modify: `sebastian/capabilities/tools/ask_parent/__init__.py`
- Tests: gateway and capability tests.

- [ ] **Step 1: Write failing API/tool response tests**

Cover:

- `GET /sessions/{id}` returns `messages` legacy projection and `timeline_items`.
- `/recent` or equivalent uses limit 25 and excludes archived original items.
- `inspect_session` shows timeline items.
- completion notifier finds recent assistant content without reading archived original.
- resume/stop append user/system timeline items.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/gateway tests/unit/capabilities -q`

Expected: FAIL because routes/tools still call old methods.

- [ ] **Step 3: Update routes**

Rules:

- No route reads filesystem session paths.
- Legacy `messages` schema is role/content/created_at/seq only.
- `timeline_items` schema is canonical item shape.
- `include_archived=true` uses full history view.

- [ ] **Step 4: Update tools**

Rules:

- Use `SessionStore` only.
- Do not inject or expect `IndexStore`.
- Stop/resume marker writes become timeline items.

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/gateway tests/unit/capabilities -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git status --short
git add sebastian/gateway/routes/sessions.py sebastian/gateway/routes/turns.py sebastian/gateway/routes/stream.py sebastian/gateway/routes/debug.py sebastian/gateway/routes/agents.py sebastian/gateway/completion_notifier.py
git add sebastian/capabilities/tools/inspect_session/__init__.py sebastian/capabilities/tools/spawn_sub_agent/__init__.py sebastian/capabilities/tools/resume_agent/__init__.py sebastian/capabilities/tools/delegate_to_agent/__init__.py sebastian/capabilities/tools/stop_agent/__init__.py sebastian/capabilities/tools/check_sub_agents/__init__.py sebastian/capabilities/tools/ask_parent/__init__.py
git add tests/integration/gateway/test_gateway_sessions.py tests/integration/gateway/test_gateway_no_provider.py tests/integration/gateway/test_sessions_todos_api.py tests/unit/gateway/test_agents_route.py tests/unit/gateway/test_completion_notifier.py tests/unit/capabilities/test_tool_inspect.py tests/unit/capabilities/test_tool_spawn.py tests/unit/capabilities/test_tool_resume_agent.py tests/unit/capabilities/test_tool_delegate.py tests/unit/capabilities/test_tool_stop_agent.py tests/unit/capabilities/test_tool_check_subs.py tests/unit/capabilities/test_tool_ask_parent.py
git commit -m "refactor(gateway): 迁移 session API 到 timeline 视图"
```

### Task 10: Memory Consolidation Cursor And Since API

**Files:**
- Modify: `sebastian/memory/consolidation.py`
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/store/session_timeline.py`
- Tests: `tests/unit/memory/test_consolidation.py`
- Tests: `tests/integration/test_memory_consolidation.py`
- Tests: `tests/integration/test_memory_catchup_sweep.py`

- [ ] **Step 1: Write failing since/cursor tests**

Cover:

- `get_messages_since(after_seq)` includes user/assistant/tool/summary.
- It excludes thinking/raw_block.
- `context_summary` with `source_seq_end <= last_consolidated_source_seq` is skipped for increment logic.
- completed-session consolidation writes `last_consolidated_seq`, `last_seen_item_seq`, and `last_consolidated_source_seq`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/memory/test_consolidation.py tests/integration/test_memory_consolidation.py tests/integration/test_memory_catchup_sweep.py -q`

Expected: FAIL because consolidation uses `get_messages()`.

- [ ] **Step 3: Implement since API**

In timeline helper:

- Query real `seq > after_seq`.
- Filter allowed kinds.
- Exclude thinking/raw_block.
- Return enough metadata for consolidation cursor decisions.

- [ ] **Step 4: Update consolidation**

For current completed-session worker:

- Use context or since API as appropriate.
- Persist `last_seen_item_seq` and `last_consolidated_source_seq`.
- Preserve existing idempotency behavior for full-session completed consolidation.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/memory/test_consolidation.py tests/integration/test_memory_consolidation.py tests/integration/test_memory_catchup_sweep.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/consolidation.py sebastian/store/session_store.py sebastian/store/session_timeline.py tests/unit/memory/test_consolidation.py tests/integration/test_memory_consolidation.py tests/integration/test_memory_catchup_sweep.py
git commit -m "feat(memory): 为 session timeline 增加增量游标"
```

### Task 11: Cleanup Old Filesystem Session Assumptions

**Files:**
- Modify/delete old store tests:
  - `tests/unit/store/test_session_store_paths.py`
  - `tests/unit/store/test_activity_sync.py`
  - `tests/unit/store/test_index_store.py`
  - `tests/unit/store/test_index_store_v2.py`
  - `tests/unit/store/test_index_store_goal.py`
- Search target: all `messages.jsonl`, `meta.json`, `index.json`, `sessions_dir / agent_type / session_id` runtime assumptions.

- [ ] **Step 1: Search for filesystem assumptions**

Run:

```bash
rg "messages\\.jsonl|meta\\.json|index\\.json|sessions_dir|EpisodicMemory|IndexStore" sebastian tests -n
```

Expected: only docs/archive or intentionally deprecated references remain.

- [ ] **Step 2: Delete or rewrite obsolete tests**

Delete tests that only validate old file paths. Rewrite behavior tests to DB semantics.

- [ ] **Step 3: Remove unused imports/files**

Remove:

- `aiofiles` imports no longer needed by session store.
- `shutil/os/weakref` file lock remnants.
- old file helper functions.

- [ ] **Step 4: Run store/core/gateway tests**

Run: `pytest tests/unit/store tests/unit/core tests/unit/capabilities tests/integration/gateway -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git status --short
git add sebastian/store/session_store.py sebastian/store/index_store.py sebastian/memory/episodic_memory.py tests/unit/store/test_session_store_paths.py tests/unit/store/test_activity_sync.py tests/unit/store/test_index_store.py tests/unit/store/test_index_store_v2.py tests/unit/store/test_index_store_goal.py tests/unit/core/test_base_agent_index_store.py
git commit -m "refactor(store): 清理 session 文件存储遗留"
```

### Task 12: Documentation Updates

**Files:**
- Modify: `sebastian/store/README.md`
- Modify: `sebastian/memory/README.md`
- Modify: `sebastian/gateway/README.md`
- Modify: `sebastian/core/README.md`
- Modify: `docs/architecture/spec/INDEX.md` if adding architecture reference links is appropriate.
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write doc update checklist**

Use the spec as source of truth. Ensure docs state:

- SQLite is session truth.
- `IndexStore` removed or no longer runtime concept.
- old `EpisodicMemory` removed/renamed.
- todos are DB-backed.
- context is timeline-based.

- [ ] **Step 2: Update READMEs**

Keep README updates concise and aligned with module navigation tables.

- [ ] **Step 3: Update CHANGELOG**

Add user-facing `[Unreleased]` entry under `Changed`:

- Session history, tasks, checkpoints, and per-session todos now use SQLite-backed storage and timeline views.

- [ ] **Step 4: Run markdown-adjacent checks**

Run: `git diff --check`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/README.md sebastian/memory/README.md sebastian/gateway/README.md sebastian/core/README.md CHANGELOG.md docs/architecture/spec/INDEX.md
git commit -m "docs: 更新 session SQLite 存储说明"
```

### Task 13: Full Verification

**Files:**
- No planned edits unless verification finds failures.

- [ ] **Step 1: Run focused store tests**

Run: `pytest tests/unit/store -q`

Expected: PASS.

- [ ] **Step 2: Run focused core tests**

Run: `pytest tests/unit/core -q`

Expected: PASS.

- [ ] **Step 3: Run capabilities tests**

Run: `pytest tests/unit/capabilities -q`

Expected: PASS.

- [ ] **Step 4: Run memory tests touched by migration**

Run: `pytest tests/unit/memory tests/integration/test_memory_consolidation.py tests/integration/test_memory_catchup_sweep.py -q`

Expected: PASS.

- [ ] **Step 5: Run gateway integration tests**

Run: `pytest tests/integration/gateway -q`

Expected: PASS.

- [ ] **Step 6: Run lint**

Run: `ruff check sebastian/ tests/`

Expected: PASS.

- [ ] **Step 7: Run type check if practical**

Run: `mypy sebastian/`

Expected: PASS or document pre-existing unrelated failures with exact output.

- [ ] **Step 8: Manual smoke test**

If dependencies and credentials allow:

1. Start gateway against a temp data dir.
2. Create a session.
3. Send a user turn.
4. Confirm `sessions` and `session_items` rows exist.
5. Restart gateway.
6. Confirm session and timeline still load.

- [ ] **Step 9: Final status**

Run: `git status --short`

Expected: clean or only intentional uncommitted changes.

## Cross-Cutting Guardrails

- Do not reintroduce filesystem session runtime reads/writes.
- Do not keep both `IndexStore` and `SessionStore` as active session list sources.
- Do not use `asyncio.Lock` as the only seq correctness mechanism.
- Do not feed legacy UI `messages` into provider context.
- Do not include thinking in default provider context.
- Do not let `TaskStore` and `SessionStore` both independently mutate tasks.
- If any file approaches 500 lines, split it before continuing; do not wait until it reaches 800 lines.

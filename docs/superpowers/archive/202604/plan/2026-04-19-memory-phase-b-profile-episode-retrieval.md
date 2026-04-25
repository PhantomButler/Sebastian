# Memory Phase B Profile Episode Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a toggleable, usable DB-backed memory system with explicit save/search tools, Profile/Episode stores, retrieval lanes, and BaseAgent prompt injection.

**Architecture:** This phase builds on Phase A. It implements deterministic stores and retrieval without automatic LLM extraction. User-visible value comes from explicit `memory_save`, `memory_search`, and automatic memory injection through a small `MemorySectionAssembler`.

**Tech Stack:** Python 3.12, SQLAlchemy async, SQLite FTS5, jieba, pytest, pytest-asyncio.

---

## Prerequisites

- Phase A completed.
- `sebastian/memory/types.py`, `slots.py`, `segmentation.py`, and `decision_log.py` exist.
- Memory ORM records exist in `sebastian/store/models.py`.
- Existing `EpisodicMemory` still serves session history.

## File Structure

Create:

- `sebastian/memory/profile_store.py`
  - CRUD and resolution application for `fact` / `preference`.
- `sebastian/memory/episode_store.py`
  - Episode/summary persistence and FTS-backed search.
- `sebastian/memory/entity_registry.py`
  - Entity lookup and jieba userdict sync.
- `sebastian/memory/startup.py`
  - Memory storage startup initializer for SQLite virtual tables.
- `sebastian/memory/resolver.py`
  - Deterministic conflict resolution.
- `sebastian/memory/retrieval.py`
  - `RetrievalPlanner`, lane result types, `MemorySectionAssembler`.
- `sebastian/capabilities/tools/memory_save/__init__.py`
- `sebastian/capabilities/tools/memory_search/__init__.py`
- `tests/unit/memory/test_profile_store.py`
- `tests/unit/memory/test_episode_store.py`
- `tests/unit/memory/test_entity_registry.py`
- `tests/unit/memory/test_resolver.py`
- `tests/unit/memory/test_retrieval.py`
- `tests/unit/tools/test_memory_tools.py`
- `tests/unit/gateway/test_memory_settings.py`

Modify:

- `sebastian/memory/store.py`
  - Expose new stores while keeping `working` and existing `episodic`.
- `sebastian/core/base_agent.py`
  - Add optional memory store/retriever hook and memory section injection.
- `sebastian/gateway/state.py`
  - Add runtime memory settings only. Do not store DB-backed memory stores globally.
- `sebastian/gateway/app.py`
  - Call memory storage startup initialization after `init_db()`.
- `sebastian/config/__init__.py`
  - Add `sebastian_memory_enabled: bool = True`, mapped from `SEBASTIAN_MEMORY_ENABLED`.
- `sebastian/config/README.md`
  - Document memory toggle.
- `sebastian/gateway/routes/settings.py` or existing settings/debug route
  - Expose read/update API for runtime memory toggle if a settings route already exists. If none exists, create a focused `memory_settings` route.
- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/README.md`
  - Document Settings toggle placement. Implementation may be scheduled in this phase only if backend settings API exists.
- `sebastian/capabilities/tools/README.md`
- `sebastian/memory/README.md`

Do not create:

- `memory_list` tool
- `memory_delete` tool
- LLM extractor
- Consolidation worker

## DB Session Wiring Convention

Memory stores depend on `AsyncSession`, so they must be constructed per operation inside an explicit session scope. Do not attach `ProfileMemoryStore`, `EpisodeMemoryStore`, `EntityRegistry`, or `MemoryDecisionLogger` as long-lived singletons on `sebastian.gateway.state`.

Tool wiring:

```python
import sebastian.gateway.state as state

async with state.db_factory() as session:
    profile_store = ProfileMemoryStore(session)
    episode_store = EpisodeMemoryStore(session)
    entity_registry = EntityRegistry(session)
    decision_logger = MemoryDecisionLogger(session)
```

BaseAgent wiring:

- `BaseAgent` must not import `sebastian.gateway.state`.
- Add an optional constructor dependency such as `db_factory: async_sessionmaker[AsyncSession] | None = None`.
- Gateway/orchestrator construction code passes `state.db_factory` into agents.
- `_memory_section()` opens `async with self._db_factory() as session:` and constructs stores inside that block.

This keeps `sebastian/core` independent from `sebastian/gateway` while still matching the existing per-request database lifecycle.

## Task 0: Memory Enabled Toggle

**Files:**

- Modify: `sebastian/config/__init__.py`
- Modify: `sebastian/config/README.md`
- Create or modify: `sebastian/gateway/routes/memory_settings.py` or existing settings route
- Modify: `sebastian/gateway/app.py`
- Test: `tests/unit/gateway/test_memory_settings.py`

- [ ] **Step 1: Write failing config tests**

Tests must cover:

- Default `settings.sebastian_memory_enabled` is `True`.
- Environment value `SEBASTIAN_MEMORY_ENABLED=false` results in `False`.
- Invalid boolean values fail through pydantic-settings.

- [ ] **Step 2: Add config field**

Add to `Settings` in `sebastian/config/__init__.py`:

```python
sebastian_memory_enabled: bool = True
```

Rules:

- Default is enabled.
- The environment variable is `SEBASTIAN_MEMORY_ENABLED`.
- This controls backend behavior even before App UI exists.

- [ ] **Step 3: Add runtime route tests**

Tests must cover:

- `GET /api/v1/memory/settings` returns `{ "enabled": true }` by default.
- `PUT /api/v1/memory/settings { "enabled": false }` disables memory for current process.
- `PUT /api/v1/memory/settings { "enabled": true }` re-enables memory.
- Routes require auth, matching other settings routes.

- [ ] **Step 4: Implement runtime state**

Implement a minimal runtime state holder:

```python
class MemoryRuntimeSettings(BaseModel):
    enabled: bool
```

Store it in `sebastian.gateway.state` as `memory_settings`.

Important:

- Runtime toggle may be process-local in Phase B.
- Persisted App setting can be added later if global settings storage exists.
- Disabling memory must not delete memory records.

- [ ] **Step 5: Implement routes**

Routes:

```text
GET /api/v1/memory/settings
PUT /api/v1/memory/settings
```

Behavior:

- Read/write `state.memory_settings.enabled`.
- Return JSON `{ "enabled": bool }`.

- [ ] **Step 6: Wire behavior gates**

The following Phase B code must check this flag:

- BaseAgent `_memory_section()` returns empty string when disabled.
- `memory_save` returns ok=false or clear disabled message without writing.
- `memory_search` returns empty result or clear disabled message without reading.

Phase C code must also check this flag:

- Consolidation scheduler does not schedule work when disabled.
- Running worker exits early when disabled.

- [ ] **Step 7: Document App Settings requirement**

Update Android settings README with planned UI:

- Add a Memory（记忆）section in Settings.
- Add switch: `Memory enabled`.
- Default on.
- Turning off should call `PUT /api/v1/memory/settings`.
- UI copy: “关闭后不会读取、写入或沉淀记忆；已有记忆不会删除。”

- [ ] **Step 8: Run tests**

Run: `pytest tests/unit/gateway/test_memory_settings.py -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add sebastian/config/__init__.py sebastian/config/README.md sebastian/gateway/routes/memory_settings.py sebastian/gateway/app.py tests/unit/gateway/test_memory_settings.py ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/README.md
git commit -m "feat(memory): 新增记忆功能开关" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 1: Profile Store

**Files:**

- Create: `sebastian/memory/profile_store.py`
- Test: `tests/unit/memory/test_profile_store.py`

- [ ] **Step 1: Write failing tests**

Tests must cover:

- `add()` inserts an active preference.
- `get_active_by_slot(subject_id, scope, slot_id)` returns current active record.
- `supersede(old_id, new_artifact)` marks old record `superseded` and inserts new active record.
- `touch(memory_ids)` increments `access_count` and sets `last_accessed_at`.

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/memory/test_profile_store.py -v`

Expected: FAIL because `profile_store.py` does not exist.

- [ ] **Step 3: Implement `ProfileMemoryStore`**

Constructor:

```python
class ProfileMemoryStore:
    def __init__(self, db_session: AsyncSession) -> None: ...
```

Required methods:

```python
async def add(self, artifact: MemoryArtifact) -> ProfileMemoryRecord: ...
async def get_active_by_slot(self, subject_id: str, scope: str, slot_id: str) -> list[ProfileMemoryRecord]: ...
async def supersede(self, old_ids: list[str], artifact: MemoryArtifact) -> ProfileMemoryRecord: ...
async def search_active(self, *, subject_id: str, scope: str | None = None, limit: int = 8) -> list[ProfileMemoryRecord]: ...
async def touch(self, memory_ids: list[str]) -> None: ...
```

Rules:

- Do not commit internally.
- Only return `status == "active"` from active methods.
- Filter expired records by `valid_until`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_profile_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/profile_store.py tests/unit/memory/test_profile_store.py
git commit -m "feat(memory): 新增画像记忆存储" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 2: Episode Store And FTS

**Files:**

- Create: `sebastian/memory/episode_store.py`
- Test: `tests/unit/memory/test_episode_store.py`

- [ ] **Step 1: Write failing FTS tests**

Tests must cover:

- Saving episode stores `content` and `content_segmented`.
- Search query `用户` matches episode `用户偏好简洁中文回复`.
- Search query `小橘` matches episode containing `小橘`.
- Search query `Memory Artifact` matches English phrase.
- Single-character query `猫` returns no FTS result unless entity lookup is used later.

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/memory/test_episode_store.py -v`

Expected: FAIL because store does not exist.

- [ ] **Step 3: Implement FTS DDL helper**

Implement in `episode_store.py`:

```python
async def ensure_episode_fts(conn: AsyncConnection) -> None: ...
```

DDL:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts
USING fts5(content_segmented, content='episode_memories', content_rowid='rowid', tokenize='unicode61');
```

If `episode_memories` does not have a stable integer rowid mapping through SQLAlchemy primary key, use a contentless FTS table with a separate `memory_id` UNINDEXED column instead:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts
USING fts5(memory_id UNINDEXED, content_segmented, tokenize='unicode61');
```

Pick one implementation and test it. Do not leave both paths active.

- [ ] **Step 4: Implement `EpisodeMemoryStore`**

Required methods:

```python
async def ensure_fts(self) -> None: ...
async def add_episode(self, artifact: MemoryArtifact) -> EpisodeMemoryRecord: ...
async def add_summary(self, artifact: MemoryArtifact) -> EpisodeMemoryRecord: ...
async def search(self, query: str, *, subject_id: str, limit: int = 8) -> list[EpisodeMemoryRecord]: ...
async def touch(self, memory_ids: list[str]) -> None: ...
```

Rules:

- Use `segment_for_fts(content)` on write.
- Use `terms_for_query(query)` on search.
- Query each term separately, merge IDs, rank by number of matched terms then `recorded_at DESC`.
- Do not use trigram.
- Do not use raw `unicode61` on original content.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/memory/test_episode_store.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/episode_store.py tests/unit/memory/test_episode_store.py
git commit -m "feat(memory): 新增情景记忆存储与中文检索" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 2.5: Memory Storage Startup

**Files:**

- Create: `sebastian/memory/startup.py`
- Modify: `sebastian/gateway/app.py`
- Test: `tests/integration/test_memory_startup.py`

- [ ] **Step 1: Write failing startup test**

Test must cover:

- Gateway startup calls memory storage initialization after `init_db()`.
- `episode_memories_fts` exists after startup.
- Running startup twice is idempotent.

- [ ] **Step 2: Implement startup helper**

Implement:

```python
async def init_memory_storage(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await ensure_episode_fts(conn)
```

Rules:

- `ensure_episode_fts()` lives in `sebastian/memory/episode_store.py`.
- `init_memory_storage()` owns startup orchestration only.
- Do not rely on `Base.metadata.create_all()` for FTS5 virtual tables.

- [ ] **Step 3: Wire app lifespan**

In `sebastian/gateway/app.py`, call `await init_memory_storage(engine)` immediately after the existing database initialization path.

Important:

- This initialization should run regardless of `memory_enabled`; the toggle disables behavior, not schema readiness.
- Startup failure should fail fast because broken FTS means episode search is not reliable.

- [ ] **Step 4: Run test**

Run: `pytest tests/integration/test_memory_startup.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/startup.py sebastian/gateway/app.py tests/integration/test_memory_startup.py
git commit -m "feat(memory): 初始化记忆检索存储" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 3: Entity Registry

**Files:**

- Create: `sebastian/memory/entity_registry.py`
- Test: `tests/unit/memory/test_entity_registry.py`

- [ ] **Step 1: Write failing tests**

Tests must cover:

- `upsert_entity("小橘", "pet", aliases=["橘猫"])` creates entity.
- Re-upserting same canonical name merges aliases.
- `lookup("小橘")` returns entity.
- `sync_jieba_terms()` calls segmentation helper with canonical names and aliases.

- [ ] **Step 2: Implement**

Required methods:

```python
async def upsert_entity(self, canonical_name: str, entity_type: str, aliases: list[str] | None = None, metadata: dict[str, Any] | None = None) -> EntityRecord: ...
async def lookup(self, text: str) -> list[EntityRecord]: ...
async def sync_jieba_terms(self) -> None: ...
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/memory/test_entity_registry.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/memory/entity_registry.py tests/unit/memory/test_entity_registry.py
git commit -m "feat(memory): 新增实体注册表" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 4: Resolver

**Files:**

- Create: `sebastian/memory/resolver.py`
- Test: `tests/unit/memory/test_resolver.py`

- [ ] **Step 1: Write failing resolver tests**

Tests must cover:

- Explicit preference supersedes inferred preference in same single slot.
- Multi-value fact merges/adds instead of superseding.
- Episode is always `ADD`.
- Low-confidence inferred candidate without slot becomes `DISCARD`.

- [ ] **Step 2: Implement deterministic resolver**

Required function:

```python
async def resolve_candidate(
    candidate: CandidateArtifact,
    *,
    subject_id: str,
    profile_store: ProfileMemoryStore,
    slot_registry: SlotRegistry,
) -> ResolveDecision: ...
```

Rules:

- Resolver never reads raw messages.
- Resolver never calls LLM.
- Resolver writes no DB state itself.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/memory/test_resolver.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/memory/resolver.py tests/unit/memory/test_resolver.py
git commit -m "feat(memory): 新增记忆冲突解析器" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 5: Retrieval Planner And Assembler

**Files:**

- Create: `sebastian/memory/retrieval.py`
- Test: `tests/unit/memory/test_retrieval.py`

- [ ] **Step 1: Write failing tests**

Tests must cover:

- Planner enables Profile Lane for every normal turn.
- Planner enables Episode Lane for query `我们上次讨论到哪了`.
- Assembler filters `policy_tags=["do_not_auto_inject"]`.
- Assembler separates current truth and historical evidence sections.
- Assembler respects fixed per-lane limits.

- [ ] **Step 2: Implement models and planner**

Required classes:

```python
class RetrievalContext(BaseModel): ...
class RetrievalPlan(BaseModel): ...
class MemoryRetrievalPlanner: ...
class MemorySectionAssembler: ...
```

Minimum section output:

```text
## What I know about the user
- ...

## Relevant current context
- ...

## Relevant past episodes
- ...

## Important relationships
- ...
```

Rules:

- Empty sections are omitted.
- Maximum total items in Phase B: 8.
- `policy_tags` filtering must run before formatting.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/memory/test_retrieval.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/memory/retrieval.py tests/unit/memory/test_retrieval.py
git commit -m "feat(memory): 新增记忆检索规划与注入装配" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 6: Explicit Memory Tools

**Files:**

- Create: `sebastian/capabilities/tools/memory_save/__init__.py`
- Create: `sebastian/capabilities/tools/memory_search/__init__.py`
- Test: `tests/unit/tools/test_memory_tools.py`
- Modify: `sebastian/capabilities/tools/README.md`

- [ ] **Step 1: Write failing tool tests**

Tests must cover:

- `memory_save(content="以后回答简洁中文", slot_id="user.preference.response_style")` returns ok.
- `memory_search(query="简洁中文")` returns saved memory.
- Tools return disabled message if memory subsystem is unavailable.
- Tools return disabled message when `memory_enabled == false`.
- No `memory_list` or `memory_delete` tool exists.

- [ ] **Step 2: Implement `memory_save`**

Tool metadata:

```python
@tool(
    name="memory_save",
    description="Save an explicit user-approved memory. Use only when the user asks you to remember something.",
    permission_tier=PermissionTier.LOW,
)
```

Input parameters:

- `content: str`
- `slot_id: str | None = None`
- `scope: str = "user"`
- `policy_tags: list[str] | None = None`

Behavior:

- Treat source as `explicit`.
- Build `CandidateArtifact`.
- Normalize subject as owner for Phase B.
- Resolve and persist.
- Write decision log.
- Open `async with state.db_factory() as session:` inside the tool, then construct memory stores with that session.
- Commit once after all writes succeed.
- If memory is disabled, return `ToolResult(ok=False, error="记忆功能已关闭")` and do not write.

- [ ] **Step 3: Implement `memory_search`**

Tool metadata:

```python
@tool(
    name="memory_search",
    description="Search long-term memory for relevant facts, preferences, summaries, or episodes.",
    permission_tier=PermissionTier.LOW,
)
```

Input parameters:

- `query: str`
- `limit: int = 5`

Behavior:

- Use retrieval planner with `access_purpose="tool_search"`.
- Return concise list with memory type, content, source, confidence.
- Open `async with state.db_factory() as session:` inside the tool, then construct memory stores with that session.
- If memory is disabled, return `ToolResult(ok=False, error="记忆功能已关闭")` and do not read.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/tools/test_memory_tools.py -v`

Expected: PASS.

- [ ] **Step 5: Update tools README**

Add `memory_save` and `memory_search` to Native tools directory tree and navigation table.

- [ ] **Step 6: Commit**

```bash
git add sebastian/capabilities/tools/memory_save/__init__.py sebastian/capabilities/tools/memory_search/__init__.py tests/unit/tools/test_memory_tools.py sebastian/capabilities/tools/README.md
git commit -m "feat(memory): 新增显式记忆工具" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 7: BaseAgent Memory Injection

**Files:**

- Modify: `sebastian/core/base_agent.py`
- Test: `tests/unit/core/test_base_agent_memory.py`
- Modify: `sebastian/core/README.md`
- Modify: `sebastian/memory/README.md`

- [ ] **Step 1: Write failing BaseAgent test**

Test must assert:

- `BaseAgent` accepts an optional `db_factory`.
- `_memory_section()` returns assembled memory text when memory store has records.
- `_stream_inner()` includes memory section in effective system prompt.
- Existing todo section still appears.
- If memory retrieval raises, turn continues and logs warning.
- If memory is disabled, `_memory_section()` returns empty string and does not call stores.

- [ ] **Step 2: Implement `_memory_section()`**

Add method near `_session_todos_section()`:

```python
async def _memory_section(self, session_id: str, agent_context: str, user_message: str) -> str:
    ...
```

Rules:

- No LLM calls.
- Use retrieval planner and assembler.
- Use `async with self._db_factory() as session:` and construct stores inside the session scope.
- Return empty string when `self._db_factory is None`.
- Return empty string when `memory_enabled == false`.
- Catch exceptions and return empty string.
- Do not mutate `self.system_prompt`.
- Do not import `sebastian.gateway.state` from `sebastian/core/base_agent.py`.

- [ ] **Step 3: Wire into `_stream_inner()`**

Current code builds:

```python
todo_section = await self._session_todos_section(session_id, agent_context)
effective_system_prompt = f"{self.system_prompt}\n\n{todo_section}" if todo_section else self.system_prompt
```

Replace with deterministic composition:

```python
sections = [self.system_prompt]
memory_section = await self._memory_section(session_id, agent_context, user_message=messages[-1]["content"])
if memory_section:
    sections.append(memory_section)
if todo_section:
    sections.append(todo_section)
effective_system_prompt = "\n\n".join(sections)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/core/test_base_agent_memory.py -v`

Expected: PASS.

- [ ] **Step 5: Run focused existing tests**

Run:

```bash
pytest tests/unit/core/test_base_agent_provider.py tests/unit/llm/test_thinking_duration.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_base_agent_memory.py sebastian/core/README.md sebastian/memory/README.md
git commit -m "feat(memory): 注入长期记忆上下文" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Phase B Completion Criteria

- [ ] Explicit save/search tools work in unit tests.
- [ ] `memory_enabled=false` disables memory injection, tools, and future consolidation scheduling without deleting data.
- [ ] BaseAgent prompt injection works with memory section and existing todo section.
- [ ] `pytest tests/unit/memory tests/unit/tools/test_memory_tools.py tests/unit/core/test_base_agent_memory.py -q` passes.
- [ ] `ruff check sebastian/memory sebastian/capabilities/tools/memory_save sebastian/capabilities/tools/memory_search tests/unit/memory tests/unit/tools/test_memory_tools.py` passes.
- [ ] No automatic LLM extraction added yet.
- [ ] No `memory_list` / `memory_delete` agent tools added.

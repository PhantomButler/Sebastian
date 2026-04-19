# Memory Phase D Relation Admin Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the memory system with relation promotion, owner-only management APIs, maintenance workers, and observability after the core memory loop is already usable.

**Architecture:** This phase turns relation candidates into confirmed relation facts, adds safe owner management paths for listing/deleting memories outside agent tools, and adds scheduled maintenance. It intentionally does not introduce vector DB or embedding.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite, EventBus, pytest, pytest-asyncio.

---

## Prerequisites

- Phase A completed.
- Phase B completed.
- Phase C completed.
- `relation_candidates` are being persisted.
- `memory_decision_log` is populated for memory writes.

## File Structure

Create:

- `sebastian/memory/relation_store.py`
- `sebastian/memory/maintenance.py`
- `sebastian/gateway/routes/memory.py`
- `tests/unit/memory/test_relation_store.py`
- `tests/unit/memory/test_maintenance.py`
- `tests/unit/gateway/test_memory_routes.py`

Modify:

- `sebastian/store/models.py`
  - Add `RelationFactRecord` if not already present.
- `sebastian/gateway/app.py`
  - Include memory router.
- `sebastian/gateway/routes/README.md`
- `sebastian/memory/README.md`
- `docs/architecture/spec/memory/storage.md`
- `docs/architecture/spec/memory/retrieval.md`
- `docs/architecture/spec/memory/consolidation.md`

Do not create:

- Agent-facing `memory_list`
- Agent-facing `memory_delete`

## Task 1: Relation Store

**Files:**

- Create: `sebastian/memory/relation_store.py`
- Modify: `sebastian/store/models.py`
- Test: `tests/unit/memory/test_relation_store.py`

- [ ] **Step 1: Write failing relation tests**

Tests must cover:

- Adding relation candidate.
- Promoting candidate to confirmed relation fact.
- Exclusive predicate sets previous active relation `valid_until`.
- Non-exclusive predicate allows multiple active relations.
- Query by `source_entity_id`, `target_entity_id`, and `predicate`.

- [ ] **Step 2: Add `RelationFactRecord`**

Fields:

- `id: str PK`
- `subject_id: str index`
- `predicate: str index`
- `source_entity_id: str index`
- `target_entity_id: str index`
- `content: str`
- `structured_payload: dict[str, Any]`
- `confidence: float`
- `status: str index`
- `valid_from: datetime | None`
- `valid_until: datetime | None`
- `provenance: dict[str, Any]`
- `policy_tags: list[str]`
- `created_at: datetime`
- `updated_at: datetime`

- [ ] **Step 3: Implement `RelationMemoryStore`**

Required methods:

```python
async def add_candidate(self, artifact: CandidateArtifact, *, subject_id: str) -> RelationCandidateRecord: ...
async def promote_candidate(self, candidate_id: str, *, exclusive: bool) -> RelationFactRecord: ...
async def search(self, *, subject_id: str, entity_id: str | None = None, predicate: str | None = None, limit: int = 8) -> list[RelationFactRecord]: ...
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_relation_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/relation_store.py sebastian/store/models.py tests/unit/memory/test_relation_store.py
git commit -m "feat(memory): 新增关系记忆存储" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 2: Relation Lane Retrieval

**Files:**

- Modify: `sebastian/memory/retrieval.py`
- Test: `tests/unit/memory/test_retrieval.py`
- Modify: `docs/architecture/spec/memory/retrieval.md`

- [ ] **Step 1: Add failing retrieval test**

Scenario:

- Query mentions entity `ForgeAgent`.
- Planner enables Relation Lane.
- Assembler injects relation under `Important relationships`.
- `policy_tags=["do_not_auto_inject"]` relation is filtered.

- [ ] **Step 2: Implement relation lane**

Rules:

- Use `EntityRegistry.lookup(query)` first.
- Query relation facts by matched entity IDs.
- Do not query relation candidates for automatic injection unless status is confirmed.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/memory/test_retrieval.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/memory/retrieval.py tests/unit/memory/test_retrieval.py docs/architecture/spec/memory/retrieval.md
git commit -m "feat(memory): 接入关系记忆检索通道" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 3: Owner-Only Memory Management API

**Files:**

- Create: `sebastian/gateway/routes/memory.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/routes/README.md`
- Test: `tests/unit/gateway/test_memory_routes.py`

- [ ] **Step 1: Write failing route tests**

Routes:

- `GET /api/v1/memory`
  - Query params: `kind`, `status`, `subject_id`, `limit`, `offset`.
  - Returns memory summaries, not raw decision log by default.
- `GET /api/v1/memory/{memory_id}`
  - Returns full record with provenance.
- `DELETE /api/v1/memory/{memory_id}`
  - Marks memory `deleted`, does not hard delete.
  - Writes decision log.
- `GET /api/v1/memory/decisions`
  - Lists decision log for debugging.

- [ ] **Step 2: Implement auth**

Rules:

- All routes require owner auth through existing auth dependency.
- Do not expose these as LLM tools.
- Delete route must soft-delete and write decision log.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/gateway/test_memory_routes.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/gateway/routes/memory.py sebastian/gateway/app.py sebastian/gateway/routes/README.md tests/unit/gateway/test_memory_routes.py
git commit -m "feat(memory): 新增主人记忆管理 API" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 4: Memory Maintenance Worker

**Files:**

- Create: `sebastian/memory/maintenance.py`
- Test: `tests/unit/memory/test_maintenance.py`

- [ ] **Step 1: Write failing maintenance tests**

Tests must cover:

- Expired active memory becomes `expired`.
- Duplicate episode summaries can be marked superseded.
- Low-confidence stale candidates can be left untouched until policy is explicit.
- Every state transition writes decision log.

- [ ] **Step 2: Implement `MemoryMaintenanceWorker`**

Required methods:

```python
async def expire_due_memories(self, now: datetime | None = None) -> int: ...
async def compact_summaries(self, *, subject_id: str, dry_run: bool = False) -> int: ...
```

Rules:

- No hard deletes.
- No LLM calls.
- All transitions log decisions.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/memory/test_maintenance.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/memory/maintenance.py tests/unit/memory/test_maintenance.py
git commit -m "feat(memory): 新增记忆维护 worker" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 5: Observability And Debugging

**Files:**

- Modify: `sebastian/log/README.md`
- Modify: `sebastian/memory/README.md`
- Test: no code test unless logging helper added.

- [ ] **Step 1: Add structured log points**

If not already present from previous phases, add logs for:

- extraction schema failure
- resolve decision
- consolidation start/end
- maintenance transitions

Rules:

- Do not log raw sensitive memory content at INFO.
- DEBUG logs may include memory IDs and slot IDs.

- [ ] **Step 2: Update docs**

Document where to look for memory decision logs and runtime logs.

- [ ] **Step 3: Verify**

Run: `ruff check sebastian/memory`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add sebastian/log/README.md sebastian/memory/README.md
git commit -m "docs(memory): 补充记忆系统可观测性说明" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Phase D Completion Criteria

- [ ] Relation candidates can be promoted to relation facts.
- [ ] Relation Lane injects only confirmed, allowed relationships.
- [ ] Owner-only API can list, inspect, and soft-delete memories.
- [ ] No agent-facing delete/list tools exist.
- [ ] Maintenance worker can expire memories and log transitions.
- [ ] `pytest tests/unit/memory tests/unit/gateway/test_memory_routes.py -q` passes.
- [ ] `ruff check sebastian/memory sebastian/gateway/routes/memory.py tests/unit/memory tests/unit/gateway/test_memory_routes.py` passes.


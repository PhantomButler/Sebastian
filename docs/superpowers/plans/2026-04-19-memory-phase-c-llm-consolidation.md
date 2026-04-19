# Memory Phase C LLM Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured LLM memory extraction and asynchronous session consolidation while keeping final writes deterministic through Normalize and Resolve.

**Architecture:** This phase introduces `memory_extractor` and `memory_consolidator` provider bindings, Pydantic schema validation for LLM outputs, and background workers triggered by session lifecycle events. LLMs produce candidates and suggestions only; they never directly mutate memory state.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, existing LLMProviderRegistry, EventBus, pytest, pytest-asyncio.

---

## Prerequisites

- Phase A completed.
- Phase B completed.
- `ProfileMemoryStore`, `EpisodeMemoryStore`, `MemoryRetrievalPlanner`, `MemorySectionAssembler`, `memory_save`, and `memory_search` exist.
- `memory_enabled` runtime toggle exists and defaults to enabled.

## Scope Decision: No Per-Turn LLM Inference In This Phase

This phase implements session-end consolidation only. It does not add a per-turn hook after `TurnDone` / `_stream_inner()` to run LLM extraction on every user message.

Reason:

- Per-turn LLM inference increases latency, cost, and noisy writes on the main chat path.
- Urgent user-approved writes are already covered by explicit `memory_save`.
- Normal inferred facts and preferences are handled by session consolidation after the conversation lifecycle event.

If real-time conversational inference becomes necessary, create a separate follow-up phase, for example `memory-phase-e-per-turn-inference`, with its own latency budget, debounce rules, and write-noise tests.

## File Structure

Create:

- `sebastian/memory/extraction.py`
  - `ExtractorInput`, `MemoryExtractor`, schema validation and retry logic.
- `sebastian/memory/consolidation.py`
  - `ConsolidatorInput`, `ConsolidationResult`, `SessionConsolidationWorker`.
- `sebastian/memory/provider_bindings.py`
  - Constants and helper for `memory_extractor` / `memory_consolidator` provider names.
- `tests/unit/memory/test_extraction.py`
- `tests/unit/memory/test_consolidation.py`
- `tests/integration/test_memory_consolidation.py`

Modify:

- `sebastian/llm/registry.py`
  - Support non-agent component bindings or document reuse through `agent_llm_bindings` with component names.
- `sebastian/store/models.py`
  - Add session consolidation marker table or columns if needed.
- `sebastian/gateway/app.py`
  - Start/stop consolidation worker in lifespan if existing app startup owns workers.
- `sebastian/gateway/state.py`
  - Store worker reference if needed.
- `docs/architecture/spec/memory/implementation.md`
  - Update if final binding storage differs.

## Task 1: Component Provider Bindings

**Files:**

- Create: `sebastian/memory/provider_bindings.py`
- Modify: `sebastian/llm/registry.py`
- Test: `tests/unit/memory/test_provider_bindings.py`

- [ ] **Step 1: Write failing tests**

Tests must cover:

- `get_provider("memory_extractor")` can resolve a binding row.
- `get_provider("memory_consolidator")` can resolve a binding row.
- If no component binding exists, fallback to global default provider.

- [ ] **Step 2: Implement constants**

```python
MEMORY_EXTRACTOR_BINDING = "memory_extractor"
MEMORY_CONSOLIDATOR_BINDING = "memory_consolidator"
```

- [ ] **Step 3: Reuse existing registry path**

If `AgentLLMBindingRecord.agent_type` is already generic enough, do not create a new table. Use component names as binding keys.

If a new table is required, stop and update `docs/architecture/spec/memory/implementation.md` first before coding.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_provider_bindings.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/provider_bindings.py sebastian/llm/registry.py tests/unit/memory/test_provider_bindings.py docs/architecture/spec/memory/implementation.md
git commit -m "feat(memory): 新增记忆模型绑定入口" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 2: Memory Extractor

**Files:**

- Create: `sebastian/memory/extraction.py`
- Test: `tests/unit/memory/test_extraction.py`

- [ ] **Step 1: Write failing schema tests**

Tests must cover:

- `ExtractorInput` serializes known slots and conversation window.
- Valid LLM JSON parses to `list[CandidateArtifact]`.
- Invalid enum value fails validation.
- Malformed JSON retries once and then returns empty candidates with a warning result.

- [ ] **Step 2: Implement schema classes**

Classes:

```python
class ExtractorInput(BaseModel): ...
class ExtractorOutput(BaseModel):
    artifacts: list[CandidateArtifact]
```

- [ ] **Step 3: Implement `MemoryExtractor`**

Constructor:

```python
class MemoryExtractor:
    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None: ...
```

Method:

```python
async def extract(self, input: ExtractorInput) -> list[CandidateArtifact]: ...
```

Rules:

- Resolve provider through `memory_extractor`.
- Reuse `AgentLLMBindingRecord.agent_type` with component key `memory_extractor`; do not create a new binding table unless the existing registry cannot support it.
- Use low temperature if provider API supports options through existing abstraction. If not supported, document limitation in code comment.
- Prompt must instruct strict JSON only.
- Validate with Pydantic.
- Do not persist.

- [ ] **Step 4: Use fake provider in tests**

Do not call real cloud APIs in unit tests.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/memory/test_extraction.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/extraction.py tests/unit/memory/test_extraction.py
git commit -m "feat(memory): 新增结构化记忆提取器" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 3: Consolidator Schema And Summaries

**Files:**

- Create/Modify: `sebastian/memory/consolidation.py`
- Test: `tests/unit/memory/test_consolidation.py`

- [ ] **Step 1: Write failing tests**

Tests must cover:

- `ConsolidatorInput` includes session messages, candidate artifacts, active memories, recent summaries, slot definitions, entity snapshot.
- Valid `ConsolidationResult` parses summaries, proposed artifacts, proposed actions.
- Consolidator output is passed through Normalize/Resolve in worker tests, not written directly.

- [ ] **Step 2: Implement models**

```python
class ConsolidatorInput(BaseModel): ...
class MemorySummary(BaseModel): ...
class ProposedAction(BaseModel): ...
class ConsolidationResult(BaseModel): ...
```

- [ ] **Step 3: Implement `MemoryConsolidator`**

```python
class MemoryConsolidator:
    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None: ...
    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult: ...
```

Rules:

- Resolve provider through `memory_consolidator`.
- Reuse `AgentLLMBindingRecord.agent_type` with component key `memory_consolidator`; do not create a new binding table unless the existing registry cannot support it.
- Return empty result on schema failure after retry.
- Do not persist.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_consolidation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/consolidation.py tests/unit/memory/test_consolidation.py
git commit -m "feat(memory): 新增记忆沉淀协议" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 4: Session Consolidation Worker

**Files:**

- Modify: `sebastian/memory/consolidation.py`
- Test: `tests/integration/test_memory_consolidation.py`

- [ ] **Step 1: Write failing integration test**

Scenario:

- Create a session with messages in `SessionStore`.
- Seed an active memory for same subject.
- Run `SessionConsolidationWorker.consolidate_session(session_id, agent_type)`.
- Fake consolidator returns one summary and one proposed artifact.
- Assert summary saved to Episode Store.
- Assert proposed artifact resolved and written to Profile Store.
- Assert decision log contains entries.
- Assert running worker again for same session does not duplicate results.
- Assert worker exits without reading messages or writing memories when `memory_enabled == false`.

- [ ] **Step 2: Add consolidation marker**

Pick one:

- Add `SessionConsolidationRecord(session_id PK, agent_type, consolidated_at, worker_version)`.
- Or add a marker in existing session metadata if that pattern is already used.

Prefer DB record to avoid mutating session JSON shape.

- [ ] **Step 3: Implement worker**

```python
class SessionConsolidationWorker:
    async def consolidate_session(self, session_id: str, agent_type: str) -> None: ...
```

Rules:

- Read full session messages from `SessionStore`.
- Exit early if memory is disabled.
- Build `ConsolidatorInput`.
- Persist summaries through `EpisodeMemoryStore`.
- Proposed artifacts pass Normalize/Resolve/Persist.
- Write decision log.
- Mark session consolidated only after successful transaction.
- Idempotent: no duplicate writes on rerun.

- [ ] **Step 4: Run test**

Run: `pytest tests/integration/test_memory_consolidation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/consolidation.py sebastian/store/models.py tests/integration/test_memory_consolidation.py
git commit -m "feat(memory): 新增会话记忆沉淀 worker" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 5: EventBus / Lifespan Integration

**Files:**

- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/state.py`
- Test: `tests/integration/test_memory_consolidation_lifecycle.py`

- [ ] **Step 1: Use existing session lifecycle event**

Use existing event types in `sebastian/protocol/events/`.

`SESSION_COMPLETED` already exists and is the default event for this phase. Do not add a new event unless implementation proves `SESSION_COMPLETED` cannot represent the lifecycle boundary.

- [ ] **Step 2: Write failing lifecycle test**

Test that publishing the selected session lifecycle event schedules consolidation once.

Also test that publishing the event while memory is disabled schedules nothing.

- [ ] **Step 3: Implement background scheduling**

Rules:

- Worker must not block SSE or turn response path.
- Scheduler must check `memory_enabled` before `asyncio.create_task`.
- Use `asyncio.create_task`.
- This scheduler triggers session-end consolidation only; it must not run extractor per turn.
- Log exceptions.
- Do not retry infinitely.
- Provide shutdown cleanup if worker owns tasks.

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_memory_consolidation_lifecycle.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/app.py sebastian/gateway/state.py tests/integration/test_memory_consolidation_lifecycle.py
git commit -m "feat(memory): 接入会话沉淀生命周期" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 6: Documentation

**Files:**

- Modify: `sebastian/memory/README.md`
- Modify: `docs/architecture/spec/memory/consolidation.md`
- Modify: `docs/architecture/spec/memory/implementation.md`

- [ ] **Step 1: Update docs**

Document:

- Provider binding names.
- Worker idempotency marker.
- LLM schema retry behavior.
- No direct LLM database mutation rule.

- [ ] **Step 2: Verify docs**

Run: `git diff --check`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add sebastian/memory/README.md docs/architecture/spec/memory/consolidation.md docs/architecture/spec/memory/implementation.md
git commit -m "docs(memory): 补充记忆沉淀实现说明" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Phase C Completion Criteria

- [ ] No real LLM API calls in unit/integration tests.
- [ ] Extractor and consolidator validate strict schemas.
- [ ] Consolidation worker is idempotent.
- [ ] `memory_enabled=false` prevents new consolidation tasks.
- [ ] All LLM-produced writes pass Normalize and Resolve.
- [ ] `pytest tests/unit/memory tests/integration/test_memory_consolidation.py -q` passes.
- [ ] `ruff check sebastian/memory tests/unit/memory tests/integration/test_memory_consolidation.py` passes.

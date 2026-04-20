# Memory Spec Audit Follow-up Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining memory spec gaps confirmed after cross-checking `docs/architecture/spec/memory/` against the current `feat/agent-memory` implementation.

**Architecture:** Keep the fix set narrow and protocol-driven: preserve memory kind/type semantics during retrieval, make the explicit tool path and automatic injection path behaviorally consistent, persist the artifact fields needed for future-safe filtering/auditing, and route every memory lifecycle action through the same resolver/persist/logger pipeline. Do not implement deferred Phase D semantics such as exclusive relations, cross-session consolidation, summary replacement, or a maintenance worker in this plan.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, SQLite/FTS5, jieba, pytest, ruff, mypy.

---

## Preflight

**Read first:**
- `docs/architecture/spec/INDEX.md`
- `docs/architecture/spec/memory/INDEX.md`
- `docs/architecture/spec/memory/artifact-model.md`
- `docs/architecture/spec/memory/storage.md`
- `docs/architecture/spec/memory/write-pipeline.md`
- `docs/architecture/spec/memory/retrieval.md`
- `docs/architecture/spec/memory/implementation.md`
- `docs/architecture/spec/memory/consolidation.md`
- `sebastian/README.md`
- `sebastian/memory/README.md`
- `sebastian/capabilities/tools/README.md`

**Branch/worktree rule:**
- This plan is intended as follow-up work on the current memory feature branch. If starting from scratch, follow the repository `AGENTS.md` rule and create a short-lived branch from `main`.
- Do not use `git add .` or `git add -A`. Stage explicit files only.
- Do not mix unrelated formatting/refactor churn into these tasks.

**Important scope boundary:**
- Implement only the gaps listed here.
- Do not add CrossSessionConsolidationWorker, MemoryMaintenanceWorker, exclusive relation semantics, provider temperature support, or BaseAgent hook decomposition.
- If a task exposes a larger design problem, stop and update the plan instead of patching around it.

---

## File Structure

**Core protocol and retrieval:**
- Modify: `sebastian/memory/retrieval.py`
  - Add `RetrievalContext.active_project_or_agent_context`.
  - Preserve `[kind]` labels for Context, Episode, and Relation lanes.
  - Keep filtering centralized in `MemorySectionAssembler._keep()`.
- Modify: `sebastian/memory/types.py`
  - Existing enum/model support should stay; no new top-level protocol type expected.

**Stores and persistence:**
- Modify: `sebastian/store/models.py`
  - Add missing persisted logical fields:
    - `ProfileMemoryRecord.cardinality`
    - `ProfileMemoryRecord.resolution_policy`
    - `EpisodeMemoryRecord.valid_from`
    - `EpisodeMemoryRecord.valid_until`
    - `RelationCandidateRecord.policy_tags`
- Modify: `sebastian/store/database.py`
  - Add idempotent SQLite migrations for those columns.
- Modify: `sebastian/memory/profile_store.py`
  - Persist profile cardinality/resolution policy.
  - Support exact-active lookup for duplicate/merge decisions.
- Modify: `sebastian/memory/episode_store.py`
  - Persist episode validity fields.
  - Support exact-active lookup for episode/summary dedupe.
  - Optionally add `expire()` if needed by unified EXPIRE routing.
- Modify: `sebastian/memory/entity_registry.py`
  - Persist and return relation candidate `policy_tags`.

**Resolve/write pipeline:**
- Modify: `sebastian/memory/resolver.py`
  - Implement exact dedupe for episode/summary.
  - Implement minimal MERGE decision support for merge-policy/multi-cardinality profile records.
  - Ensure `_make_artifact()` can use effective slot cardinality/policy values from the registry.
- Modify: `sebastian/memory/write_router.py`
  - Treat MERGE explicitly.
  - Execute EXPIRE decisions through the router instead of direct caller writes.
  - Persist relation `policy_tags`.
- Modify: `sebastian/memory/consolidation.py`
  - Change `ConsolidatorInput.task` to `Literal["consolidate_memory"]`.
  - Route EXPIRE proposed actions through `persist_decision()`.

**Tools:**
- Modify: `sebastian/capabilities/tools/memory_save/__init__.py`
  - Put `session_id` into candidate evidence when available.
- Modify: `sebastian/capabilities/tools/memory_search/__init__.py`
  - Fetch all planned lanes: profile, context, episode summary-first, relation.
  - Return enough structured fields to distinguish lane/kind/citation semantics.

**Docs/tests:**
- Modify: `sebastian/memory/README.md`
- Modify: `sebastian/capabilities/tools/README.md` only if tool output shape docs need an update.
- Modify: `CHANGELOG.md`
- Tests:
  - `tests/unit/memory/test_retrieval.py`
  - `tests/unit/memory/test_resolver.py`
  - `tests/unit/memory/test_write_router.py`
  - `tests/unit/memory/test_profile_store.py`
  - `tests/unit/memory/test_episode_store.py`
  - `tests/unit/memory/test_entity_registry.py`
  - `tests/unit/memory/test_consolidation.py`
  - `tests/unit/capabilities/test_memory_tools.py`
  - Relevant integration tests in `tests/integration/test_memory_consolidation.py`

---

### Task 1: Persist Missing Protocol Fields

**Files:**
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/store/database.py`
- Modify: `sebastian/memory/profile_store.py`
- Modify: `sebastian/memory/episode_store.py`
- Modify: `sebastian/memory/entity_registry.py`
- Test: `tests/unit/memory/test_profile_store.py`
- Test: `tests/unit/memory/test_episode_store.py`
- Test: `tests/unit/memory/test_entity_registry.py`
- Test: `tests/unit/memory/test_write_router.py`

**Intent:** The artifact protocol keeps `cardinality`, `resolution_policy`, `valid_from`, `valid_until`, and `policy_tags`. Current storage drops some of these fields, which makes future filtering/auditing depend on mutable slot definitions or silently bypass policy tags.

- [ ] **Step 1: Write failing profile persistence tests**

In `tests/unit/memory/test_profile_store.py`, add a test that creates a `MemoryArtifact` with:
- `cardinality=Cardinality.SINGLE`
- `resolution_policy=ResolutionPolicy.SUPERSEDE`

Then persist it via `ProfileMemoryStore.add()` and assert the DB row has:

```python
assert row.cardinality == "single"
assert row.resolution_policy == "supersede"
```

- [ ] **Step 2: Write failing episode validity tests**

In `tests/unit/memory/test_episode_store.py`, add a test that persists an episode artifact with non-null `valid_from` and `valid_until`, then asserts:

```python
assert row.valid_from == valid_from
assert row.valid_until == valid_until
```

- [ ] **Step 3: Write failing relation policy tag tests**

In `tests/unit/memory/test_write_router.py` or `tests/unit/memory/test_entity_registry.py`, persist a relation artifact with:

```python
policy_tags=["do_not_auto_inject", "agent:sebastian"]
```

Assert the `RelationCandidateRecord.policy_tags` row field preserves the list.

- [ ] **Step 4: Run the new tests and verify they fail**

```bash
pytest tests/unit/memory/test_profile_store.py -k "cardinality or resolution_policy" -v
pytest tests/unit/memory/test_episode_store.py -k "valid_from or valid_until" -v
pytest tests/unit/memory/test_write_router.py -k "relation and policy_tags" -v
```

Expected: FAIL because the columns/fields are missing.

- [ ] **Step 5: Add model columns**

In `sebastian/store/models.py`:

```python
class ProfileMemoryRecord(Base):
    ...
    cardinality: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_policy: Mapped[str | None] = mapped_column(String, nullable=True)

class EpisodeMemoryRecord(Base):
    ...
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class RelationCandidateRecord(Base):
    ...
    policy_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
```

Place the new columns near related protocol fields, not at random.

- [ ] **Step 6: Add idempotent SQLite migrations**

In `sebastian/store/database.py`, extend `_apply_idempotent_migrations()`:

```python
patches: list[tuple[str, str, str]] = [
    ...
    ("profile_memories", "cardinality", "VARCHAR"),
    ("profile_memories", "resolution_policy", "VARCHAR"),
    ("episode_memories", "valid_from", "DATETIME"),
    ("episode_memories", "valid_until", "DATETIME"),
    ("relation_candidates", "policy_tags", "TEXT"),
]
```

SQLite JSON fields are stored as text; follow the current `input_source` migration pattern.

- [ ] **Step 7: Persist the fields in stores/router**

In `ProfileMemoryStore._artifact_to_record()`:

```python
cardinality=artifact.cardinality.value if artifact.cardinality is not None else None,
resolution_policy=(
    artifact.resolution_policy.value
    if artifact.resolution_policy is not None
    else None
),
```

In `EpisodeMemoryStore._artifact_to_record()`:

```python
valid_from=artifact.valid_from,
valid_until=artifact.valid_until,
```

In `write_router.persist_decision()` relation branch:

```python
policy_tags=artifact.policy_tags,
```

- [ ] **Step 8: Run focused tests**

```bash
pytest tests/unit/memory/test_profile_store.py tests/unit/memory/test_episode_store.py tests/unit/memory/test_write_router.py tests/unit/memory/test_entity_registry.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py sebastian/memory/profile_store.py sebastian/memory/episode_store.py sebastian/memory/entity_registry.py sebastian/memory/write_router.py tests/unit/memory/test_profile_store.py tests/unit/memory/test_episode_store.py tests/unit/memory/test_entity_registry.py tests/unit/memory/test_write_router.py
git commit -m "fix(memory): 补齐记忆协议字段持久化" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Preserve Memory Kind Labels in All Retrieval Lanes

**Files:**
- Modify: `sebastian/memory/retrieval.py`
- Test: `tests/unit/memory/test_retrieval.py`

**Intent:** `retrieval.md §6` requires automatic prompt injection to preserve memory kind labels. Current Profile lane preserves `[fact]` / `[preference]`, but Context, Episode, and Relation lanes lose type information.

- [ ] **Step 1: Write failing assembler tests**

In `tests/unit/memory/test_retrieval.py`, add/extend `TestMemorySectionAssembler` tests with fake records:

```python
class FakeRecord:
    def __init__(self, kind: str, content: str) -> None:
        self.kind = kind
        self.content = content
        self.confidence = 1.0
        self.status = "active"
        self.subject_id = "user:owner"
        self.valid_from = None
        self.valid_until = None
        self.policy_tags = []
```

Assert:

```python
assert "- [fact] 当前项目是 Sebastian" in output
assert "- [summary] 上次讨论了记忆模块" in output
assert "- [episode] 用户确认了方案" in output
```

For relation records, assert:

```python
assert "- [relation]" in output
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/unit/memory/test_retrieval.py::TestMemorySectionAssembler -k "kind or label or relation" -v
```

Expected: FAIL because Context/Episode/Relation render without kind labels.

- [ ] **Step 3: Implement minimal rendering helpers**

In `sebastian/memory/retrieval.py`, add:

```python
def _record_kind(record: Any, fallback: str) -> str:
    kind = getattr(record, "kind", None)
    if kind is None:
        return fallback
    value = getattr(kind, "value", kind)
    return str(value)
```

Then render:

```python
lines = "\n".join(f"- [{_record_kind(r, 'fact')}] {r.content}" for r in contexts)
lines = "\n".join(f"- [{_record_kind(r, 'episode')}] {r.content}" for r in episodes)
lines = "\n".join(f"- [relation] {_render_relation(r)}" for r in relations)
```

Keep Profile lane behavior unchanged unless refactoring into the helper makes it clearer.

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/unit/memory/test_retrieval.py::TestMemorySectionAssembler -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/retrieval.py tests/unit/memory/test_retrieval.py
git commit -m "fix(memory): 检索注入保留记忆类型标签" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Make memory_search Fetch All Planned Lanes

**Files:**
- Modify: `sebastian/capabilities/tools/memory_search/__init__.py`
- Test: `tests/unit/capabilities/test_memory_tools.py`
- Possibly modify: `sebastian/capabilities/tools/README.md`

**Intent:** `memory_search` uses `MemoryRetrievalPlanner.plan()` but currently fetches only Profile and Episode records. It must match the automatic injection path for Context and Relation lanes and should use the same summary-first episode strategy.

- [ ] **Step 1: Write failing context lane tool test**

In `tests/unit/capabilities/test_memory_tools.py`, add a test that:
- Inserts a recent active profile record.
- Calls `memory_search("今天正在做什么")`.
- Asserts at least one item has:

```python
assert item["lane"] == "context"
assert item["kind"] in ("fact", "preference")
assert item["citation_type"] == "current_truth"
```

- [ ] **Step 2: Write failing relation lane tool test**

Insert a `RelationCandidateRecord` for the resolved subject with active status and call:

```python
result = await memory_search("这个项目和谁 related to", limit=5)
```

Assert:

```python
assert any(item["lane"] == "relation" for item in result.output["items"])
assert any(item["kind"] == "relation" for item in result.output["items"])
```

- [ ] **Step 3: Write failing summary-first tool test**

Create one matching summary and one matching episode. Call a query that triggers episode lane. Assert the summary is returned before the episode:

```python
items = result.output["items"]
episode_items = [item for item in items if item["lane"] == "episode"]
assert episode_items[0]["citation_type"] == "historical_summary"
```

- [ ] **Step 4: Run the failing tests**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -k "memory_search and (context or relation or summary_first)" -v
```

Expected: FAIL because context/relation are not fetched and episode uses mixed `search()`.

- [ ] **Step 5: Implement all-lane fetch**

In `memory_search/__init__.py`:

```python
from sebastian.memory.entity_registry import EntityRegistry
```

Inside the DB session:

```python
context_records = (
    await profile_store.search_recent_context(
        subject_id=subject_id,
        limit=plan.context_limit,
    )
    if plan.context_lane
    else []
)

episode_records = []
if plan.episode_lane:
    summary_records = await episode_store.search_summaries_by_query(
        subject_id=subject_id,
        query=query,
        limit=plan.episode_limit,
    )
    if len(summary_records) >= plan.episode_limit:
        episode_records = summary_records
    else:
        detail_records = await episode_store.search_episodes_only(
            subject_id=subject_id,
            query=query,
            limit=plan.episode_limit - len(summary_records),
        )
        episode_records = [*summary_records, *detail_records]

entity_registry = EntityRegistry(session)
relation_records = (
    await entity_registry.list_relations(
        subject_id=subject_id,
        limit=plan.relation_limit,
    )
    if plan.relation_lane
    else []
)
```

Return structured items with a stable `lane` field:

```python
{
    "lane": "context",
    "kind": record.kind,
    "content": record.content,
    "source": record.source,
    "confidence": record.confidence if record.confidence is not None else 1.0,
    "citation_type": "current_truth",
    "is_current": True,
}
```

For relation records:

```python
{
    "lane": "relation",
    "kind": "relation",
    "content": record.content,
    "source": "system_derived",
    "confidence": record.confidence if record.confidence is not None else 1.0,
    "citation_type": "current_truth",
    "is_current": True,
}
```

Keep existing fields for backwards compatibility.

- [ ] **Step 6: Update trace payload**

Include all fetched record refs:

```python
items=[record_ref(r) for r in [*profile_records, *context_records, *episode_records, *relation_records]][:limit]
```

- [ ] **Step 7: Run focused tests**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -k "memory_search" -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/capabilities/tools/memory_search/__init__.py tests/unit/capabilities/test_memory_tools.py sebastian/capabilities/tools/README.md
git commit -m "fix(memory): memory_search 覆盖全部检索通道" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

If `sebastian/capabilities/tools/README.md` was not changed, omit it from `git add`.

---

### Task 4: Add session_id Evidence to memory_save Artifacts

**Files:**
- Modify: `sebastian/capabilities/tools/memory_save/__init__.py`
- Test: `tests/unit/capabilities/test_memory_tools.py`
- Modify: `CHANGELOG.md` if its current provenance entry needs correction.

**Intent:** `memory_save` logs `input_source.session_id`, but the actual `MemoryArtifact.provenance` remains missing `session_id` because `CandidateArtifact.evidence` is empty.

- [ ] **Step 1: Write failing provenance test**

In `tests/unit/capabilities/test_memory_tools.py`, add a test that monkeypatches:

```python
monkeypatch.setattr(state_module, "current_session_id", "sess-memory-save", raising=False)
```

Call `memory_save(content="以后回答简洁中文", slot_id="user.preference.response_style")`, then query `ProfileMemoryRecord` and assert:

```python
assert row.provenance["session_id"] == "sess-memory-save"
assert row.provenance["evidence"] == [{"session_id": "sess-memory-save"}]
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -k "memory_save and provenance" -v
```

Expected: FAIL because `evidence=[]`.

- [ ] **Step 3: Populate evidence**

In `memory_save/__init__.py`:

```python
evidence = [{"session_id": tool_session_id}] if tool_session_id is not None else []
```

Then pass:

```python
evidence=evidence,
```

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -k "memory_save" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/memory_save/__init__.py tests/unit/capabilities/test_memory_tools.py CHANGELOG.md
git commit -m "fix(memory): memory_save provenance 记录 session_id" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

If `CHANGELOG.md` was not changed, omit it from `git add`.

---

### Task 5: Implement Episode/Summary Exact Dedupe

**Files:**
- Modify: `sebastian/memory/episode_store.py`
- Modify: `sebastian/memory/resolver.py`
- Modify callers of `resolve_candidate()` as needed:
  - `sebastian/capabilities/tools/memory_save/__init__.py`
  - `sebastian/memory/consolidation.py`
- Test: `tests/unit/memory/test_episode_store.py`
- Test: `tests/unit/memory/test_resolver.py`
- Test: `tests/integration/test_memory_consolidation.py`

**Intent:** Spec default strategy says episode is append-only but still does exact dedupe. Current resolver always ADDs episode/summary, so repeated extraction can create duplicate historical evidence.

- [ ] **Step 1: Add failing store lookup test**

In `tests/unit/memory/test_episode_store.py`, add a test for a new method:

```python
existing = await store.find_active_exact(
    subject_id="user:owner",
    kind=MemoryKind.SUMMARY,
    content="本次讨论了记忆模块",
)
assert existing is not None
assert existing.id == row.id
```

Also assert a different kind or different content returns `None`.

- [ ] **Step 2: Add failing resolver duplicate test**

In `tests/unit/memory/test_resolver.py`, create an existing episode/summary record, then call `resolve_candidate(candidate, ..., episode_store=episode_store)` with the same subject/kind/content. Assert:

```python
assert decision.decision == MemoryDecisionType.DISCARD
assert decision.old_memory_ids == [existing.id]
assert decision.new_memory is None
assert "duplicate" in decision.reason.lower() or "重复" in decision.reason
```

- [ ] **Step 3: Run failing tests**

```bash
pytest tests/unit/memory/test_episode_store.py -k "find_active_exact" -v
pytest tests/unit/memory/test_resolver.py -k "episode and duplicate" -v
```

Expected: FAIL because lookup/resolver dedupe do not exist.

- [ ] **Step 4: Implement `EpisodeMemoryStore.find_active_exact()`**

In `episode_store.py`:

```python
async def find_active_exact(
    self,
    *,
    subject_id: str,
    kind: MemoryKind,
    content: str,
) -> EpisodeMemoryRecord | None:
    statement = select(EpisodeMemoryRecord).where(
        EpisodeMemoryRecord.subject_id == subject_id,
        EpisodeMemoryRecord.kind == kind.value,
        EpisodeMemoryRecord.status == MemoryStatus.ACTIVE.value,
        EpisodeMemoryRecord.content == content,
    )
    result = await self._session.scalars(statement)
    return result.first()
```

- [ ] **Step 5: Update resolver signature**

In `resolver.py`, under `TYPE_CHECKING` import `EpisodeMemoryStore`, then change:

```python
async def resolve_candidate(
    candidate: CandidateArtifact,
    *,
    subject_id: str,
    profile_store: ProfileMemoryStore,
    slot_registry: SlotRegistry,
    episode_store: EpisodeMemoryStore | None = None,
) -> ResolveDecision:
```

For `MemoryKind.EPISODE` / `MemoryKind.SUMMARY`:

```python
if episode_store is not None:
    existing = await episode_store.find_active_exact(
        subject_id=subject_id,
        kind=candidate.kind,
        content=candidate.content,
    )
    if existing is not None:
        return _trace_decision(ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason="exact duplicate episode/summary already exists",
            old_memory_ids=[existing.id],
            new_memory=None,
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=None,
        ))
```

Then keep the existing ADD behavior for non-duplicates or when `episode_store` is not supplied.

- [ ] **Step 6: Pass `episode_store` from real callers**

In `memory_save` and `consolidation`, update `resolve_candidate()` calls where an `episode_store` object already exists:

```python
decision = await resolve_candidate(
    candidate,
    subject_id=subject_id,
    profile_store=profile_store,
    slot_registry=DEFAULT_SLOT_REGISTRY,
    episode_store=episode_store,
)
```

Do the same for summary decisions in consolidation.

- [ ] **Step 7: Run focused tests**

```bash
pytest tests/unit/memory/test_episode_store.py tests/unit/memory/test_resolver.py tests/integration/test_memory_consolidation.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/memory/episode_store.py sebastian/memory/resolver.py sebastian/capabilities/tools/memory_save/__init__.py sebastian/memory/consolidation.py tests/unit/memory/test_episode_store.py tests/unit/memory/test_resolver.py tests/integration/test_memory_consolidation.py
git commit -m "fix(memory): 经历记忆写入执行精确去重" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Implement Minimal MERGE Decision Path

**Files:**
- Modify: `sebastian/memory/profile_store.py`
- Modify: `sebastian/memory/resolver.py`
- Modify: `sebastian/memory/write_router.py`
- Test: `tests/unit/memory/test_profile_store.py`
- Test: `tests/unit/memory/test_resolver.py`
- Test: `tests/unit/memory/test_write_router.py`

**Intent:** `MemoryDecisionType.MERGE` exists in protocol but resolver never emits it, and write router would currently treat it as ADD. Implement the minimal deterministic MERGE path needed for merge-policy profile memories without designing fuzzy semantic merging.

- [ ] **Step 1: Add failing profile exact lookup test**

In `tests/unit/memory/test_profile_store.py`, add:

```python
existing = await store.find_active_exact(
    subject_id="user:owner",
    scope="user",
    slot_id="test.multi.merge",
    kind="fact",
    content="用户使用 Sebastian",
)
assert existing is not None
```

Also verify different content returns `None`.

- [ ] **Step 2: Add failing resolver MERGE test**

In `tests/unit/memory/test_resolver.py`, create a custom `SlotRegistry` with:

```python
SlotDefinition(
    slot_id="test.multi.merge",
    scope=MemoryScope.USER,
    subject_kind="user",
    cardinality=Cardinality.MULTI,
    resolution_policy=ResolutionPolicy.MERGE,
    kind_constraints=[MemoryKind.FACT],
    description="test merge slot",
)
```

Persist an active profile record with the same content. Resolve a candidate with the same slot/content. Assert:

```python
assert decision.decision == MemoryDecisionType.MERGE
assert decision.old_memory_ids == [existing.id]
assert decision.new_memory is not None
assert decision.new_memory.cardinality == Cardinality.MULTI
assert decision.new_memory.resolution_policy == ResolutionPolicy.MERGE
```

- [ ] **Step 3: Add failing write_router MERGE test**

In `tests/unit/memory/test_write_router.py`, construct a `ResolveDecision(decision=MemoryDecisionType.MERGE, old_memory_ids=[old.id], new_memory=artifact, ...)`, call `persist_decision()`, and assert:

```python
assert old_row.status == MemoryStatus.SUPERSEDED.value
assert len(active_rows_for_slot) == 1
assert active_rows_for_slot[0].content == artifact.content
```

- [ ] **Step 4: Run failing tests**

```bash
pytest tests/unit/memory/test_profile_store.py -k "find_active_exact" -v
pytest tests/unit/memory/test_resolver.py -k "merge" -v
pytest tests/unit/memory/test_write_router.py -k "merge" -v
```

Expected: FAIL.

- [ ] **Step 5: Implement exact profile lookup**

In `profile_store.py`:

```python
async def find_active_exact(
    self,
    *,
    subject_id: str,
    scope: str,
    slot_id: str,
    kind: str,
    content: str,
) -> ProfileMemoryRecord | None:
    now = datetime.now(UTC)
    statement = select(ProfileMemoryRecord).where(
        ProfileMemoryRecord.subject_id == subject_id,
        ProfileMemoryRecord.scope == scope,
        ProfileMemoryRecord.slot_id == slot_id,
        ProfileMemoryRecord.kind == kind,
        ProfileMemoryRecord.content == content,
        ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
        or_(ProfileMemoryRecord.valid_until.is_(None), ProfileMemoryRecord.valid_until > now),
        or_(ProfileMemoryRecord.valid_from.is_(None), ProfileMemoryRecord.valid_from <= now),
    )
    result = await self._session.scalars(statement)
    return result.first()
```

- [ ] **Step 6: Let `_make_artifact()` accept effective slot metadata**

In `resolver.py`, change `_make_artifact()` signature:

```python
def _make_artifact(
    candidate: CandidateArtifact,
    subject_id: str,
    *,
    cardinality: Cardinality | None = None,
    resolution_policy: ResolutionPolicy | None = None,
) -> MemoryArtifact:
```

Then set:

```python
cardinality=cardinality if cardinality is not None else candidate.cardinality,
resolution_policy=(
    resolution_policy
    if resolution_policy is not None
    else candidate.resolution_policy
),
```

Update resolver calls after effective metadata is computed to pass:

```python
_make_artifact(
    candidate,
    subject_id,
    cardinality=effective_cardinality,
    resolution_policy=effective_policy,
)
```

- [ ] **Step 7: Emit MERGE for merge-policy exact duplicates**

Before the current `MULTI cardinality or APPEND_ONLY policy -> ADD` branch returns ADD, handle merge policy:

```python
if (
    candidate.slot_id is not None
    and effective_policy == ResolutionPolicy.MERGE
):
    existing = await profile_store.find_active_exact(
        subject_id=subject_id,
        scope=candidate.scope.value,
        slot_id=candidate.slot_id,
        kind=candidate.kind.value,
        content=candidate.content,
    )
    if existing is not None:
        return _trace_decision(ResolveDecision(
            decision=MemoryDecisionType.MERGE,
            reason=f"merge-policy slot '{candidate.slot_id}' matched an exact active record",
            old_memory_ids=[existing.id],
            new_memory=_make_artifact(
                candidate,
                subject_id,
                cardinality=effective_cardinality,
                resolution_policy=effective_policy,
            ),
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        ))
```

For multi-cardinality non-merge policy, still ADD unless exact dedupe behavior is explicitly needed by tests. Do not invent fuzzy text similarity or LLM-assisted merging.

- [ ] **Step 8: Route MERGE explicitly**

In `write_router.py` profile branch:

```python
if decision.decision in (MemoryDecisionType.SUPERSEDE, MemoryDecisionType.MERGE):
    await profile_store.supersede(decision.old_memory_ids, artifact)
else:
    await profile_store.add(artifact)
```

This records MERGE in decision log while preserving old row history as superseded.

- [ ] **Step 9: Run focused tests**

```bash
pytest tests/unit/memory/test_profile_store.py tests/unit/memory/test_resolver.py tests/unit/memory/test_write_router.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add sebastian/memory/profile_store.py sebastian/memory/resolver.py sebastian/memory/write_router.py tests/unit/memory/test_profile_store.py tests/unit/memory/test_resolver.py tests/unit/memory/test_write_router.py
git commit -m "fix(memory): 补齐 MERGE 决策执行路径" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Route EXPIRE Through write_router

**Files:**
- Modify: `sebastian/memory/write_router.py`
- Modify: `sebastian/memory/consolidation.py`
- Test: `tests/unit/memory/test_write_router.py`
- Test: `tests/integration/test_memory_consolidation.py`

**Intent:** All lifecycle mutations should go through the shared persist route. Current consolidation worker directly calls `profile_store.expire()` and then separately constructs a log-only placeholder decision.

- [ ] **Step 1: Write failing router EXPIRE test**

In `tests/unit/memory/test_write_router.py`, create an active profile row, then call:

```python
decision = ResolveDecision(
    decision=MemoryDecisionType.EXPIRE,
    reason="no longer current",
    old_memory_ids=[old.id],
    new_memory=None,
    candidate=placeholder_candidate,
    subject_id="user:owner",
    scope=MemoryScope.USER,
    slot_id=None,
)
await persist_decision(...)
```

Assert the old row status is `expired`.

- [ ] **Step 2: Write/adjust consolidation integration test**

In `tests/integration/test_memory_consolidation.py`, keep existing EXPIRE behavior assertions, and add one assertion that no direct profile-store-only path is needed. The practical assertion is:

```python
assert expire_logs[0].decision == "EXPIRE"
assert expired_row.status == "expired"
```

The code review should verify `consolidation.py` no longer calls `profile_store.expire()` directly.

- [ ] **Step 3: Run failing tests**

```bash
pytest tests/unit/memory/test_write_router.py -k "expire" -v
pytest tests/integration/test_memory_consolidation.py -k "expire" -v
```

Expected: router test FAIL because EXPIRE currently skips writes.

- [ ] **Step 4: Implement EXPIRE routing**

In `write_router.persist_decision()`:

```python
if decision.decision == MemoryDecisionType.DISCARD:
    trace(...)
    return

if decision.decision == MemoryDecisionType.EXPIRE:
    if decision.candidate.kind in (MemoryKind.FACT, MemoryKind.PREFERENCE):
        for memory_id in decision.old_memory_ids:
            await profile_store.expire(memory_id)
        _trace_write("profile", decision)
        return
    trace("persist.skip", ...)
    return
```

Update `_trace_write()` so it can handle `decision.new_memory is None`:

```python
kind=(
    decision.new_memory.kind
    if decision.new_memory is not None
    else decision.candidate.kind
),
new_memory_id=decision.new_memory.id if decision.new_memory is not None else None,
```

- [ ] **Step 5: Update consolidation EXPIRE path**

In `consolidation.py`, replace:

```python
await profile_store.expire(action.memory_id)
```

with:

```python
await persist_decision(
    expire_decision,
    session=session,
    profile_store=profile_store,
    episode_store=episode_store,
    entity_registry=entity_registry,
)
```

Do this after constructing `expire_decision`, before appending the decision log.

- [ ] **Step 6: Run focused tests**

```bash
pytest tests/unit/memory/test_write_router.py tests/integration/test_memory_consolidation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sebastian/memory/write_router.py sebastian/memory/consolidation.py tests/unit/memory/test_write_router.py tests/integration/test_memory_consolidation.py
git commit -m "fix(memory): EXPIRE 统一走写入路由" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Tighten ConsolidatorInput Task Contract

**Files:**
- Modify: `sebastian/memory/consolidation.py`
- Test: `tests/unit/memory/test_consolidation.py`

**Intent:** `implementation.md §8` specifies `task: Literal["consolidate_memory"]`. Current model uses plain `str`, so invalid task values are accepted.

- [ ] **Step 1: Write failing invalid-task test**

In `tests/unit/memory/test_consolidation.py`, add:

```python
def test_task_rejects_invalid_literal(self) -> None:
    with pytest.raises(Exception):
        ConsolidatorInput(
            task="wrong_task",
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/memory/test_consolidation.py -k "task" -v
```

Expected: FAIL because plain `str` accepts invalid values.

- [ ] **Step 3: Implement Literal**

In `consolidation.py`:

```python
from typing import TYPE_CHECKING, Any, Literal
```

Then:

```python
class ConsolidatorInput(BaseModel):
    task: Literal["consolidate_memory"] = "consolidate_memory"
```

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/unit/memory/test_consolidation.py -q
mypy sebastian/memory/consolidation.py
```

Expected: PASS / no type errors.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/consolidation.py tests/unit/memory/test_consolidation.py
git commit -m "fix(memory): ConsolidatorInput 收紧 task 契约" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Add RetrievalContext Project/Agent Context Field

**Files:**
- Modify: `sebastian/memory/retrieval.py`
- Modify: `sebastian/core/base_agent.py`
- Test: `tests/unit/memory/test_retrieval.py`
- Test: `tests/unit/core/test_base_agent_memory.py`

**Intent:** `retrieval.md §3` lists `active_project_or_agent_context` as planner input. Current context model omits it, so callers cannot pass current project/agent state even though planner can ignore it for now.

- [ ] **Step 1: Write failing context model test**

In `tests/unit/memory/test_retrieval.py`, add:

```python
def test_retrieval_context_accepts_active_project_or_agent_context() -> None:
    ctx = RetrievalContext(
        subject_id="user:owner",
        session_id="sess-1",
        agent_type="sebastian",
        user_message="现在项目做什么",
        active_project_or_agent_context={"agent_type": "sebastian", "project": "Sebastian"},
    )
    assert ctx.active_project_or_agent_context == {
        "agent_type": "sebastian",
        "project": "Sebastian",
    }
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/memory/test_retrieval.py -k "active_project_or_agent_context" -v
```

Expected: FAIL because field is missing or ignored.

- [ ] **Step 3: Add field**

In `retrieval.py`:

```python
class RetrievalContext(BaseModel):
    subject_id: str
    session_id: str
    agent_type: str
    user_message: str
    access_purpose: str = "context_injection"
    active_project_or_agent_context: dict[str, Any] | None = None
```

No planner behavior change is required in this task.

- [ ] **Step 4: Pass basic agent context from BaseAgent**

In `BaseAgent._memory_section()`, construct:

```python
active_project_or_agent_context={"agent_type": agent_context}
```

Keep this conservative. Do not invent project detection in this task.

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/unit/memory/test_retrieval.py tests/unit/core/test_base_agent_memory.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/retrieval.py sebastian/core/base_agent.py tests/unit/memory/test_retrieval.py tests/unit/core/test_base_agent_memory.py
git commit -m "fix(memory): 补齐检索上下文项目代理字段" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: README and CHANGELOG Alignment

**Files:**
- Modify: `sebastian/memory/README.md`
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `CHANGELOG.md`
- Optionally modify: `docs/architecture/spec/memory/INDEX.md`
- Optionally modify: `docs/architecture/spec/memory/retrieval.md`
- Optionally modify: `docs/architecture/spec/memory/storage.md`
- Optionally modify: `docs/architecture/spec/memory/implementation.md`
- Optionally modify: `docs/architecture/spec/memory/consolidation.md`

**Intent:** The implementation docs should state what is now implemented and what remains deferred. Avoid claiming future Phase D features are complete.

- [ ] **Step 1: Update memory README implemented boundary**

In `sebastian/memory/README.md`, update the current state table to mention:
- Assembler preserves kind labels for all lanes.
- `memory_search` fetches profile/context/episode/relation lanes.
- Profile rows persist cardinality/resolution policy.
- Episode rows persist validity fields.
- Relation candidates persist policy tags.
- Explicit `memory_save` artifact provenance includes session_id when session context exists.
- MERGE has only minimal deterministic exact-record support; no fuzzy/LLM merge semantics.
- EXPIRE lifecycle writes route through `write_router`.

- [ ] **Step 2: Update tools README only if output shape changed**

If `memory_search` now returns a `lane` field, document it in `sebastian/capabilities/tools/README.md` near the `memory_search` entry or tool result conventions.

- [ ] **Step 3: Update CHANGELOG**

Under `## [Unreleased]`, add user-facing bullets under `Fixed` or `Changed`. Suggested wording:

```markdown
- 记忆注入现在在所有检索通道保留类型标签，避免事实、偏好、经历和关系在 prompt 中混淆。
- `memory_search` 主动检索补齐 context/relation 通道，并与自动注入保持 summary-first episode 策略一致。
- 记忆存储补齐协议字段持久化与显式保存 provenance，提升审计与后续迁移可靠性。
- 记忆写入补齐 episode 精确去重、MERGE 最小执行路径和统一 EXPIRE 路由。
```

Do not add a manual release version under `[Unreleased]`.

- [ ] **Step 4: Update spec status only if needed**

If any spec pages currently say a now-fixed item is still missing, update the status. Do not rewrite architecture decisions.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/README.md sebastian/capabilities/tools/README.md CHANGELOG.md docs/architecture/spec/memory/INDEX.md docs/architecture/spec/memory/retrieval.md docs/architecture/spec/memory/storage.md docs/architecture/spec/memory/implementation.md docs/architecture/spec/memory/consolidation.md
git commit -m "docs(memory): 对齐 spec 审查后续修复状态" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

Only stage files that were actually changed.

---

### Task 11: Final Verification

**Files:**
- No source changes expected unless verification exposes failures.

**Intent:** Verify the repair set as a cohesive change before handing back for review.

- [ ] **Step 1: Run focused memory tests**

```bash
pytest tests/unit/memory tests/unit/capabilities/test_memory_tools.py tests/unit/core/test_base_agent_memory.py -q
```

Expected: PASS.

- [ ] **Step 2: Run integration tests for memory consolidation**

```bash
pytest tests/integration/test_memory_consolidation.py tests/integration/test_memory_consolidation_lifecycle.py tests/integration/test_memory_supersede_chain.py tests/integration/test_memory_catchup_sweep.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint/type checks**

```bash
ruff check sebastian/memory sebastian/capabilities/tools/memory_save sebastian/capabilities/tools/memory_search tests/unit/memory tests/unit/capabilities/test_memory_tools.py
mypy sebastian/memory
```

Expected: PASS / no type errors.

- [ ] **Step 4: Inspect git state**

```bash
git status --short
git log --oneline --decorate --max-count=12
```

Expected: only intentional committed changes remain. If uncommitted docs or tests remain, either commit them explicitly or explain why they are intentionally unstaged.

- [ ] **Step 5: Prepare review handoff**

Summarize:
- Which tasks were completed.
- Which tests were run.
- Any deliberate deviations from the plan.
- Any remaining deferred items, explicitly limited to: exclusive relation semantics, cross-session consolidation, summary replacement, full maintenance worker, provider temperature support.

Do not claim “fully spec complete” if any deferred Phase C/D items remain.


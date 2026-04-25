# Memory Spec Audit Second Round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six memory spec gaps identified in the second spec audit round (April 20): Context Lane query-awareness, memory_search filtering consistency, ProposedAction contract, EXPIRE 0-hit audit, Profile sort correctness, and relation source persistence.

**Architecture:** All six fixes are independent and narrow. They do not touch the Phase A artifact protocol, Phase D relation semantics, cross-session consolidation, or the maintenance worker. Each task produces a self-contained commit. The existing TDD pattern (write failing test → run to confirm fail → implement minimal fix → run to confirm pass → commit) must be followed throughout.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, SQLite/FTS5, jieba, pytest, ruff, mypy.

---

## Preflight

**Read first:**
- `docs/architecture/spec/memory/retrieval.md` — Context Lane query-aware requirement (§4.2)
- `docs/architecture/spec/memory/consolidation.md` — ProposedAction semantics (§1.1)
- `docs/architecture/spec/memory/implementation.md` — ConsolidationResult schema (§9)
- `sebastian/memory/README.md`
- `sebastian/memory/episode_store.py` — reference implementation for FTS pattern

**Branch rule:** This plan continues work on the current `feat/agent-memory` branch. Do not open a new branch. Do not use `git add .` or `git add -A`.

**Scope boundary:**
- Do not implement cross-session consolidation, memory maintenance worker, summary replacement policy, provider temperature support, or exclusive relation semantics.
- If a task exposes a larger design problem, stop and update this plan instead of patching around it.

---

## File Structure

| File | Role in this plan |
|------|-------------------|
| `sebastian/store/models.py` | Add `content_segmented` to `ProfileMemoryRecord`; add `source` to `RelationCandidateRecord` |
| `sebastian/store/database.py` | Add migration patches for the two new columns |
| `sebastian/memory/segmentation.py` | Extract `_build_match_query` from `episode_store.py` here so profile store can reuse it |
| `sebastian/memory/episode_store.py` | Import `_build_match_query` from segmentation instead of defining it locally |
| `sebastian/memory/startup.py` | Call `ensure_profile_fts` + backfill on init |
| `sebastian/memory/profile_store.py` | Add `content_segmented` write, `profile_memories_fts` insert, query-aware `search_recent_context`, confidence-first sort in `search_active`, `expire()` returns rowcount |
| `sebastian/memory/retrieval.py` | Pass `query` to `search_recent_context`; extract `_keep` as module-level `_keep_record` |
| `sebastian/memory/write_router.py` | Trace 0-hit EXPIRE; persist `source` for relation candidates |
| `sebastian/memory/consolidation.py` | Log non-EXPIRE `proposed_actions` as DISCARD; check EXPIRE rowcount via new `persist_decision` return |
| `sebastian/capabilities/tools/memory_search/__init__.py` | Pass `query` to `search_recent_context`; apply `_keep_record` filter to all lanes |
| `tests/unit/memory/test_profile_store.py` | New tests for FTS search, confidence sort, expire rowcount |
| `tests/unit/memory/test_retrieval.py` | New test for query-aware context fetch; `_keep_record` standalone test |
| `tests/unit/memory/test_consolidation.py` | Non-EXPIRE ignored action test |
| `tests/unit/capabilities/test_memory_tools.py` | memory_search policy/confidence filter tests |

---

## Task 1: Extract `_build_match_query` to `segmentation.py`

**Files:**
- Modify: `sebastian/memory/segmentation.py`
- Modify: `sebastian/memory/episode_store.py`
- Test: `tests/unit/memory/test_segmentation.py`

**Why first:** Both Profile and Episode FTS need this helper. Moving it to `segmentation.py` removes the circular-import risk before Task 2 adds a second caller.

- [ ] **Step 1: Write a test for the helper in test_segmentation.py**

Add to `tests/unit/memory/test_segmentation.py`:

```python
from sebastian.memory.segmentation import build_match_query

def test_build_match_query_single_term() -> None:
    assert build_match_query(["项目"]) == '"项目"'

def test_build_match_query_multiple_terms() -> None:
    result = build_match_query(["记忆", "模块"])
    assert result == '"记忆" "模块"'

def test_build_match_query_empty() -> None:
    assert build_match_query([]) == '""'

def test_build_match_query_escapes_double_quotes() -> None:
    result = build_match_query(['say "hello"'])
    assert '""' in result  # inner quote is doubled
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest tests/unit/memory/test_segmentation.py -k "build_match_query" -v
```

Expected: FAIL with `ImportError: cannot import name 'build_match_query'`.

- [ ] **Step 3: Move the function to segmentation.py**

Add to `sebastian/memory/segmentation.py` (public name, no leading underscore):

```python
def build_match_query(terms: list[str]) -> str:
    """Wrap each term as a double-quoted FTS5 phrase to prevent operator injection.

    Empty term list yields an empty-string phrase that FTS5 treats as no-match.
    """
    safe = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms if t]
    return " ".join(safe) if safe else '""'
```

- [ ] **Step 4: Update episode_store.py to import from segmentation**

In `sebastian/memory/episode_store.py`, remove the local `_build_match_query` definition and add to the import:

```python
from sebastian.memory.segmentation import build_match_query, segment_for_fts, terms_for_query
```

Replace every call of `_build_match_query(...)` with `build_match_query(...)` (two occurrences inside `_search_by_kind`).

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/unit/memory/test_segmentation.py tests/unit/memory/test_episode_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/segmentation.py sebastian/memory/episode_store.py tests/unit/memory/test_segmentation.py
git commit -m "refactor(memory): 将 _build_match_query 提取到 segmentation 供多模块共用"
```

---

## Task 2: Profile Context Lane FTS (H1)

**Files:**
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/store/database.py`
- Modify: `sebastian/memory/startup.py`
- Modify: `sebastian/memory/profile_store.py`
- Modify: `sebastian/memory/retrieval.py`
- Modify: `sebastian/capabilities/tools/memory_search/__init__.py`
- Test: `tests/unit/memory/test_profile_store.py`
- Test: `tests/unit/memory/test_retrieval.py`

**Why:** `retrieval.md §4.2` says Context Lane must be "强 query-aware"。Current `search_recent_context` ignores the query and returns any recent active records by time order. This means asking "今天项目 A 怎么样" may retrieve unrelated recent facts.

- [ ] **Step 1: Write failing FTS search test**

Add to `tests/unit/memory/test_profile_store.py`:

```python
@pytest.fixture
async def fts_db_session():
    """DB session with both profile_memories table and profile_memories_fts virtual table."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import text
    from sebastian.store.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_search_recent_context_is_query_aware(fts_db_session) -> None:
    store = ProfileMemoryStore(fts_db_session)
    now = datetime.now(UTC)

    # Two records: one about project focus, one unrelated
    project_artifact = _make_artifact(
        id="mem-project",
        slot_id="user.current_project_focus",
        kind=MemoryKind.FACT,
        content="当前专注 Sebastian 项目的记忆模块",
        confidence=0.9,
        recorded_at=now,
    )
    other_artifact = _make_artifact(
        id="mem-timezone",
        slot_id="user.profile.timezone",
        kind=MemoryKind.FACT,
        content="用户所在时区为 Asia/Shanghai",
        confidence=0.95,
        recorded_at=now,
    )
    await store.add(project_artifact)
    await store.add(other_artifact)

    results = await store.search_recent_context(
        subject_id="owner",
        query="记忆模块",
        limit=5,
    )
    assert len(results) >= 1
    assert results[0].id == "mem-project"
    # timezone record should not appear for this query
    assert all(r.id != "mem-timezone" for r in results)
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/memory/test_profile_store.py -k "query_aware" -v
```

Expected: FAIL — `search_recent_context` has no `query` parameter and no FTS table exists.

- [ ] **Step 3: Add `content_segmented` to ProfileMemoryRecord**

In `sebastian/store/models.py`, inside `ProfileMemoryRecord`, after the `content` column:

```python
content_segmented: Mapped[str] = mapped_column(String, default="")
```

- [ ] **Step 4: Add DB migration**

In `sebastian/store/database.py`, add to the `patches` list:

```python
("profile_memories", "content_segmented", "VARCHAR DEFAULT ''"),
```

- [ ] **Step 5: Add `ensure_profile_fts` and backfill to startup.py**

In `sebastian/memory/startup.py`, add imports:

```python
from sqlalchemy import text

from sebastian.memory.episode_store import ensure_episode_fts
from sebastian.memory.segmentation import segment_for_fts
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.store.models import MemorySlotRecord
```

Add two new functions and update `init_memory_storage`:

```python
async def ensure_profile_fts(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
            "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
        )
    )


async def _backfill_profile_fts(conn: AsyncConnection) -> None:
    """Index any profile_memories rows not yet in the FTS virtual table."""
    result = await conn.execute(
        text(
            "SELECT id, content FROM profile_memories "
            "WHERE id NOT IN (SELECT memory_id FROM profile_memories_fts)"
        )
    )
    rows = result.fetchall()
    for row in rows:
        segmented = segment_for_fts(row[1])
        await conn.execute(
            text(
                "INSERT INTO profile_memories_fts(memory_id, content_segmented) "
                "VALUES (:memory_id, :content_segmented)"
            ),
            {"memory_id": row[0], "content_segmented": segmented},
        )


async def init_memory_storage(engine: AsyncEngine) -> None:
    """Initialize memory storage virtual tables. Idempotent. Call after init_db()."""
    async with engine.begin() as conn:
        await ensure_episode_fts(conn)
        await ensure_profile_fts(conn)
        await _backfill_profile_fts(conn)
```

- [ ] **Step 6: Update ProfileMemoryStore.add() to populate FTS and content_segmented**

In `sebastian/memory/profile_store.py`, add imports:

```python
from sqlalchemy import text
from sebastian.memory.segmentation import build_match_query, segment_for_fts, terms_for_query
```

Update `add()`:

```python
async def add(self, artifact: MemoryArtifact) -> ProfileMemoryRecord:
    record = self._artifact_to_record(artifact)
    self._session.add(record)
    await self._session.flush()
    await self._session.execute(
        text(
            "INSERT INTO profile_memories_fts(memory_id, content_segmented) "
            "VALUES (:memory_id, :content_segmented)"
        ),
        {"memory_id": record.id, "content_segmented": record.content_segmented},
    )
    await self._session.flush()
    return record
```

Update `_artifact_to_record()` to populate `content_segmented`:

```python
content_segmented=segment_for_fts(artifact.content),
```

- [ ] **Step 7: Implement query-aware search_recent_context**

Replace the existing `search_recent_context` method with:

```python
async def search_recent_context(
    self,
    *,
    subject_id: str,
    query: str = "",
    window_days: int = 7,
    limit: int = 3,
) -> list[ProfileMemoryRecord]:
    """Return recent active records matching *query* within *window_days*.

    Uses FTS5 + jieba when *query* is non-empty.
    Falls back to confidence-then-recency order when *query* is empty or
    produces no FTS terms (e.g. single-character tokens are filtered out).
    """
    from collections import Counter

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=window_days)
    base_where = [
        ProfileMemoryRecord.subject_id == subject_id,
        ProfileMemoryRecord.status == MemoryStatus.ACTIVE.value,
        or_(ProfileMemoryRecord.valid_until.is_(None), ProfileMemoryRecord.valid_until > now),
        or_(ProfileMemoryRecord.valid_from.is_(None), ProfileMemoryRecord.valid_from <= now),
        ProfileMemoryRecord.created_at >= cutoff,
    ]

    terms = terms_for_query(query) if query else []
    if terms:
        match_counts: Counter[str] = Counter()
        for term in terms:
            phrase = build_match_query([term])
            result = await self._session.execute(
                text(
                    "SELECT memory_id FROM profile_memories_fts "
                    "WHERE content_segmented MATCH :query"
                ),
                {"query": phrase},
            )
            match_counts.update(row[0] for row in result)

        if match_counts:
            ids_by_rank = [mid for mid, _ in match_counts.most_common()]
            rank_by_id = {mid: rank for rank, mid in enumerate(ids_by_rank)}

            rows = await self._session.scalars(
                select(ProfileMemoryRecord).where(
                    *base_where,
                    ProfileMemoryRecord.id.in_(ids_by_rank),
                )
            )
            records = list(rows.all())
            records.sort(
                key=lambda r: (rank_by_id[r.id], -(r.confidence or 0.0))
            )
            return records[:limit]

    # Fallback: confidence-then-recency (no FTS terms or empty query)
    statement = (
        select(ProfileMemoryRecord)
        .where(*base_where)
        .order_by(
            ProfileMemoryRecord.confidence.desc(),
            ProfileMemoryRecord.created_at.desc(),
        )
        .limit(limit)
    )
    result = await self._session.scalars(statement)
    return list(result.all())
```

- [ ] **Step 8: Pass query in retrieval.py**

In `sebastian/memory/retrieval.py`, inside `retrieve_memory_section()`, change the Context Lane fetch:

```python
if plan.context_lane:
    context_records = await profile_store.search_recent_context(
        subject_id=context.subject_id,
        query=context.user_message,   # ADDED
        limit=plan.context_limit,
    )
```

- [ ] **Step 9: Pass query in memory_search tool**

In `sebastian/capabilities/tools/memory_search/__init__.py`, change:

```python
context_records = (
    await profile_store.search_recent_context(
        subject_id=subject_id,
        query=query,               # ADDED
        limit=lane_budgets["context"],
    )
    if plan.context_lane
    else []
)
```

- [ ] **Step 10: Run focused tests**

```bash
pytest tests/unit/memory/test_profile_store.py tests/unit/memory/test_retrieval.py tests/unit/capabilities/test_memory_tools.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py sebastian/memory/startup.py sebastian/memory/profile_store.py sebastian/memory/retrieval.py sebastian/capabilities/tools/memory_search/__init__.py tests/unit/memory/test_profile_store.py
git commit -m "feat(memory): Profile Context Lane 接入 FTS + jieba 实现 query-aware 检索"
```

---

## Task 3: memory_search Unified Filtering (GPT-new)

**Files:**
- Modify: `sebastian/memory/retrieval.py`
- Modify: `sebastian/capabilities/tools/memory_search/__init__.py`
- Test: `tests/unit/capabilities/test_memory_tools.py`

**Why:** Automatic injection goes through `MemorySectionAssembler._keep()` which filters by confidence, valid_from/until, policy_tags, agent/access purpose. `memory_search` skips this entirely — a low-confidence or policy-restricted record visible to the tool but invisible to injection breaks the "shared lane semantics" promise in `retrieval.md §7.1`.

- [ ] **Step 1: Write failing filter tests**

Add to `tests/unit/capabilities/test_memory_tools.py`:

```python
async def test_memory_search_excludes_low_confidence(db_with_profile) -> None:
    """Records below MIN_CONFIDENCE must not appear in memory_search results."""
    # db_with_profile: fixture that inserts a ProfileMemoryRecord with confidence=0.1
    result = await memory_search("用户偏好", limit=5)
    assert result.ok
    items = result.output["items"]
    assert all(item["confidence"] >= 0.3 for item in items)


async def test_memory_search_excludes_expired_valid_until(db_with_profile) -> None:
    """Records whose valid_until is in the past must not appear."""
    # db_with_profile inserts a record with valid_until = now - 1 day
    result = await memory_search("用户偏好", limit=5)
    assert result.ok
    assert all(item.get("is_current", True) for item in result.output["items"])


async def test_memory_search_excludes_do_not_auto_inject_for_tool_search(db_with_profile) -> None:
    """do_not_auto_inject records SHOULD appear in tool_search (not excluded)."""
    # The do_not_auto_inject filter only applies to context_injection purpose,
    # not to explicit tool_search.
    result = await memory_search("用户偏好", limit=5)
    assert result.ok
    # Record with do_not_auto_inject should still be returned for tool search
    assert any("do_not_auto_inject" in item.get("policy_tags", []) for item in result.output["items"])
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -k "exclude" -v
```

Expected: FAIL — no filtering applied in memory_search.

- [ ] **Step 3: Extract _keep_record from MemorySectionAssembler**

In `sebastian/memory/retrieval.py`, add a module-level function before `MemorySectionAssembler`:

```python
def _keep_record(
    record: Any,
    *,
    context: RetrievalContext,
    min_confidence: float = MIN_CONFIDENCE,
) -> bool:
    """Return False if *record* should be filtered out before injection or tool return.

    Applies the same rules as MemorySectionAssembler._keep() so that
    memory_search and automatic injection behave consistently.
    """
    now = datetime.now(UTC)
    policy_tags = getattr(record, "policy_tags", None) or []

    # do_not_auto_inject: only blocks context_injection, not tool_search
    if (
        context.access_purpose == "context_injection"
        and DO_NOT_AUTO_INJECT_TAG in policy_tags
    ):
        return False

    for tag in policy_tags:
        if tag.startswith("access:"):
            _, allowed_purpose = tag.split(":", 1)
            if allowed_purpose != context.access_purpose:
                return False
        if tag.startswith("agent:"):
            _, allowed_agent = tag.split(":", 1)
            if allowed_agent != context.agent_type:
                return False

    confidence = getattr(record, "confidence", 1.0)
    if confidence is not None and confidence < min_confidence:
        return False

    valid_until = getattr(record, "valid_until", None)
    if valid_until is not None:
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=UTC)
        if valid_until <= now:
            return False

    status = getattr(record, "status", None)
    if status is not None and status != "active":
        return False

    record_subject = getattr(record, "subject_id", None)
    if (
        record_subject is not None
        and context.subject_id
        and record_subject != context.subject_id
    ):
        return False

    valid_from = getattr(record, "valid_from", None)
    if valid_from is not None:
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=UTC)
        if valid_from > now:
            return False

    return True
```

Update `MemorySectionAssembler.assemble()` to delegate to `_keep_record`:

```python
def _keep(record: Any) -> bool:
    result = _keep_record(record, context=effective_context, min_confidence=min_confidence)
    # update filter_counts for trace (keep existing accounting logic)
    ...
    return result
```

Or simpler: replace the inner `_keep` closure entirely with a call to `_keep_record`, keeping the `filter_counts` tracking separately. The filter_counts tracking can remain local — it's only for the trace log.

- [ ] **Step 4: Apply _keep_record in memory_search**

In `sebastian/capabilities/tools/memory_search/__init__.py`, after fetching all records and before building the `items` list, add:

```python
from sebastian.memory.retrieval import _keep_record

filter_ctx = RetrievalContext(
    subject_id=subject_id,
    session_id=session_id,
    agent_type="memory_search_tool",
    user_message=query,
    access_purpose="tool_search",
)

profile_records = [r for r in profile_records if _keep_record(r, context=filter_ctx)]
context_records = [r for r in context_records if _keep_record(r, context=filter_ctx)]
episode_records = [r for r in episode_records if _keep_record(r, context=filter_ctx)]
relation_records = [r for r in relation_records if _keep_record(r, context=filter_ctx)]
```

Place this block immediately after closing the `async with state.db_factory()` block and before the `items` list construction.

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -k "memory_search" -q
pytest tests/unit/memory/test_retrieval.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/retrieval.py sebastian/capabilities/tools/memory_search/__init__.py tests/unit/capabilities/test_memory_tools.py
git commit -m "fix(memory): memory_search 统一复用 Assembler 过滤逻辑避免策略绕过"
```

---

## Task 4: ProposedAction Contract + Non-EXPIRE Audit (M1)

**Files:**
- Modify: `sebastian/memory/consolidation.py`
- Test: `tests/unit/memory/test_consolidation.py`

**Why:** `consolidation.md §1.1` says `proposed_actions.action` is only `"EXPIRE"`. Currently non-EXPIRE actions are silently dropped with no decision log. Any ADD/SUPERSEDE in `proposed_actions` should be logged as DISCARD/ignored so the audit trail is complete.

- [ ] **Step 1: Write failing test for non-EXPIRE action audit**

Add to `tests/unit/memory/test_consolidation.py`:

```python
async def test_non_expire_proposed_action_is_logged_as_discard(
    db_session, fake_consolidator, fake_extractor
) -> None:
    """A proposed_action with action != EXPIRE must produce a DISCARD decision log."""
    from sebastian.store.models import MemoryDecisionLogRecord
    from sqlalchemy import select

    # Configure fake_consolidator to return an ADD action
    fake_consolidator.result = ConsolidationResult(
        summaries=[],
        proposed_artifacts=[],
        proposed_actions=[
            ProposedAction(action="ADD", memory_id=None, reason="test ignored action"),
        ],
    )

    worker = SessionConsolidationWorker(
        db_factory=db_session_factory,
        consolidator=fake_consolidator,
        extractor=fake_extractor,
        session_store=fake_session_store,
        memory_settings_fn=lambda: True,
    )
    await worker.consolidate_session("sess-1", "sebastian")

    async with db_session_factory() as session:
        rows = await session.scalars(select(MemoryDecisionLogRecord))
        log_entries = list(rows.all())

    discard_entries = [e for e in log_entries if e.decision == "DISCARD"]
    assert len(discard_entries) >= 1
    ignored = discard_entries[0]
    assert "ignored" in ignored.reason.lower() or "unsupported" in ignored.reason.lower()
    assert "ADD" in ignored.reason
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/memory/test_consolidation.py -k "non_expire" -v
```

Expected: FAIL — currently non-EXPIRE actions are silently continued past without logging.

- [ ] **Step 3: Implement ignored-action decision log**

In `sebastian/memory/consolidation.py`, replace the `proposed_actions` loop:

```python
for action in result.proposed_actions:
    if action.action != "EXPIRE" or not action.memory_id:
        # Non-EXPIRE actions are not directly executable.
        # ADD/SUPERSEDE intent must come via proposed_artifacts → resolver.
        # Log as DISCARD so the audit trail is complete.
        ignored_candidate = CandidateArtifact(
            kind=MemoryKind.FACT,
            content=f"ignored_action: {action.action} — {action.reason}",
            structured_payload={},
            subject_hint=context_subject_id,
            scope=MemoryScope.USER,
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=0.0,
            source=MemorySource.SYSTEM_DERIVED,
            evidence=[{"session_id": session_id}],
            valid_from=None,
            valid_until=None,
            policy_tags=[],
            needs_review=False,
        )
        ignored_decision = ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason=(
                f"proposed_actions only supports EXPIRE; "
                f"unsupported action '{action.action}' ignored"
            ),
            old_memory_ids=[],
            new_memory=None,
            candidate=ignored_candidate,
            subject_id=context_subject_id,
            scope=MemoryScope.USER,
            slot_id=None,
        )
        await decision_logger.append(
            ignored_decision,
            worker=self._WORKER_ID,
            model=model_name,
            rule_version=self._RULE_VERSION,
            input_source={
                "type": "session_consolidation",
                "session_id": session_id,
                "agent_type": agent_type,
            },
        )
        persisted_counts["discard"] += 1
        continue

    # ... existing EXPIRE execution code unchanged
```

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/unit/memory/test_consolidation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/consolidation.py tests/unit/memory/test_consolidation.py
git commit -m "fix(memory): proposed_actions 非 EXPIRE 动作写 DISCARD 审计日志"
```

---

## Task 5: EXPIRE 0-Hit Trace (EXPIRE correctness)

**Files:**
- Modify: `sebastian/memory/profile_store.py`
- Modify: `sebastian/memory/write_router.py`
- Test: `tests/unit/memory/test_profile_store.py`

**Why:** `consolidation.md §1.1` says "memory_id 必须非空且指向 active 的 profile memory 记录；0 命中时记录 failed_expire"。Currently `profile_store.expire()` returns `None` — if the target ID doesn't exist, the update silently affects 0 rows and the EXPIRE decision log still shows success.

- [ ] **Step 1: Write failing rowcount test**

Add to `tests/unit/memory/test_profile_store.py`:

```python
async def test_expire_nonexistent_returns_zero(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    rowcount = await store.expire("does-not-exist")
    assert rowcount == 0


async def test_expire_existing_returns_one(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    artifact = _make_artifact(id="mem-expire-test")
    await store.add(artifact)
    rowcount = await store.expire("mem-expire-test")
    assert rowcount == 1
    # Verify status changed
    from sqlalchemy import select
    from sebastian.store.models import ProfileMemoryRecord
    row = await db_session.scalar(
        select(ProfileMemoryRecord).where(ProfileMemoryRecord.id == "mem-expire-test")
    )
    assert row.status == "expired"
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/unit/memory/test_profile_store.py -k "expire" -v
```

Expected: FAIL — `expire()` currently returns `None`, so `rowcount == 0` assertion fails on type mismatch.

- [ ] **Step 3: Make expire() return rowcount**

In `sebastian/memory/profile_store.py`, change `expire()`:

```python
async def expire(self, memory_id: str) -> int:
    """Mark a profile memory record as EXPIRED. Returns rowcount (0 = not found)."""
    now = datetime.now(UTC)
    result = await self._session.execute(
        update(ProfileMemoryRecord)
        .where(ProfileMemoryRecord.id == memory_id)
        .values(
            status=MemoryStatus.EXPIRED.value,
            updated_at=now,
        )
    )
    await self._session.flush()
    return result.rowcount
```

- [ ] **Step 4: Trace 0-hit in write_router**

In `sebastian/memory/write_router.py`, inside the EXPIRE branch:

```python
if decision.decision == MemoryDecisionType.EXPIRE:
    if decision.candidate.kind in (MemoryKind.FACT, MemoryKind.PREFERENCE):
        for memory_id in decision.old_memory_ids:
            rowcount = await profile_store.expire(memory_id)
            if rowcount == 0:
                trace(
                    "persist.expire_miss",
                    memory_id=memory_id,
                    subject_id=decision.subject_id,
                    reason="target memory_id not found or already inactive",
                )
        _trace_write("profile", decision)
        return
    trace(
        "persist.skip",
        decision=decision.decision,
        subject_id=decision.subject_id,
        scope=decision.scope,
        slot_id=decision.slot_id,
        old_memory_ids=decision.old_memory_ids,
    )
    return
```

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/unit/memory/test_profile_store.py tests/unit/memory/test_write_router.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/profile_store.py sebastian/memory/write_router.py tests/unit/memory/test_profile_store.py
git commit -m "fix(memory): expire() 返回 rowcount，write_router 对 0 命中记录 trace"
```

---

## Task 6: Profile Lane Confidence Sort (L2)

**Files:**
- Modify: `sebastian/memory/profile_store.py`
- Test: `tests/unit/memory/test_profile_store.py`

**Why:** `artifact-model.md §9` says high confidence should be prioritised. `search_active()` currently sorts by `created_at.desc()` only — a newly-inferred low-confidence record can displace an older but highly-trusted explicit preference.

- [ ] **Step 1: Write failing sort test**

Add to `tests/unit/memory/test_profile_store.py`:

```python
async def test_search_active_returns_high_confidence_first(db_session) -> None:
    store = ProfileMemoryStore(db_session)
    now = datetime.now(UTC)

    # Lower confidence, newer
    low = _make_artifact(
        id="mem-low-conf",
        slot_id="user.preference.response_style",
        confidence=0.4,
        recorded_at=now,
        content="低置信偏好",
    )
    # Higher confidence, older
    high = _make_artifact(
        id="mem-high-conf",
        slot_id="user.preference.language",
        confidence=0.95,
        recorded_at=now - timedelta(hours=1),
        content="高置信偏好",
    )
    await store.add(low)
    await store.add(high)

    results = await store.search_active(subject_id="owner", limit=10)
    ids = [r.id for r in results]
    assert ids.index("mem-high-conf") < ids.index("mem-low-conf")
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/memory/test_profile_store.py -k "confidence_first" -v
```

Expected: FAIL — current sort is `created_at.desc()` so the newer low-confidence record comes first.

- [ ] **Step 3: Update sort order in search_active**

In `sebastian/memory/profile_store.py`, change `search_active()`:

```python
statement = statement.order_by(
    ProfileMemoryRecord.confidence.desc(),
    ProfileMemoryRecord.created_at.desc(),
).limit(limit)
```

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/unit/memory/test_profile_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/profile_store.py tests/unit/memory/test_profile_store.py
git commit -m "fix(memory): search_active 改为置信度优先排序符合 artifact-model 优先级"
```

---

## Task 7: Relation Source Persistence (L3)

**Files:**
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/store/database.py`
- Modify: `sebastian/memory/write_router.py`
- Modify: `sebastian/capabilities/tools/memory_search/__init__.py`
- Test: `tests/unit/memory/test_write_router.py`

**Why:** `artifact-model.md §4` requires `source` to be preserved from Day 1. `RelationCandidateRecord` has no `source` column — `write_router` drops `artifact.source`, and `memory_search` hard-codes `"system_derived"` for all relation records regardless of actual origin.

- [ ] **Step 1: Write failing persistence test**

Add to `tests/unit/memory/test_write_router.py`:

```python
async def test_relation_artifact_source_is_persisted(db_session) -> None:
    from sebastian.store.models import RelationCandidateRecord
    from sqlalchemy import select

    artifact = _make_relation_artifact(
        source=MemorySource.INFERRED,  # not system_derived
    )
    decision = ResolveDecision(
        decision=MemoryDecisionType.ADD,
        reason="test",
        old_memory_ids=[],
        new_memory=artifact,
        candidate=_make_candidate(artifact),
        subject_id=artifact.subject_id,
        scope=artifact.scope,
        slot_id=None,
    )
    await persist_decision(
        decision,
        session=db_session,
        profile_store=ProfileMemoryStore(db_session),
        episode_store=EpisodeMemoryStore(db_session),
        entity_registry=EntityRegistry(db_session),
    )
    await db_session.flush()

    row = await db_session.scalar(
        select(RelationCandidateRecord).where(
            RelationCandidateRecord.id == artifact.id
        )
    )
    assert row is not None
    assert row.source == "inferred"
```

- [ ] **Step 2: Run failing test**

```bash
pytest tests/unit/memory/test_write_router.py -k "relation_source" -v
```

Expected: FAIL — `RelationCandidateRecord` has no `source` column.

- [ ] **Step 3: Add source column to RelationCandidateRecord**

In `sebastian/store/models.py`, inside `RelationCandidateRecord`, after the `confidence` column:

```python
source: Mapped[str] = mapped_column(String, default="system_derived")
```

- [ ] **Step 4: Add migration**

In `sebastian/store/database.py`, add to `patches`:

```python
("relation_candidates", "source", "VARCHAR DEFAULT 'system_derived'"),
```

- [ ] **Step 5: Persist source in write_router**

In `sebastian/memory/write_router.py`, inside the `MemoryKind.RELATION` branch:

```python
session.add(
    RelationCandidateRecord(
        id=artifact.id or str(uuid4()),
        subject_id=artifact.subject_id,
        predicate=payload.get("predicate", ""),
        source_entity_id=payload.get("source_entity_id"),
        target_entity_id=payload.get("target_entity_id"),
        content=artifact.content,
        structured_payload=payload,
        confidence=artifact.confidence,
        source=artifact.source.value,    # ADDED
        status=artifact.status.value,
        valid_from=artifact.valid_from,
        valid_until=artifact.valid_until,
        provenance=artifact.provenance,
        policy_tags=artifact.policy_tags,
        created_at=artifact.recorded_at,
        updated_at=artifact.recorded_at,
    )
)
```

- [ ] **Step 6: Read source from record in memory_search**

In `sebastian/capabilities/tools/memory_search/__init__.py`, in the relation items loop:

```python
for record in relation_records:
    items.append(
        {
            "lane": "relation",
            "kind": "relation",
            "content": record.content,
            "source": getattr(record, "source", MemorySource.SYSTEM_DERIVED.value),
            "confidence": record.confidence if record.confidence is not None else 1.0,
            "citation_type": "current_truth",
            "is_current": True,
        }
    )
```

- [ ] **Step 7: Run focused tests**

```bash
pytest tests/unit/memory/test_write_router.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py sebastian/memory/write_router.py sebastian/capabilities/tools/memory_search/__init__.py tests/unit/memory/test_write_router.py
git commit -m "fix(memory): RelationCandidateRecord 补 source 字段并在写入和检索链路持久化"
```

---

## Task 8: Final Verification

**Files:** No source changes expected.

- [ ] **Step 1: Run all memory unit tests**

```bash
pytest tests/unit/memory/ tests/unit/capabilities/test_memory_tools.py tests/unit/core/test_base_agent_memory.py -q
```

Expected: all PASS.

- [ ] **Step 2: Run memory integration tests**

```bash
pytest tests/integration/test_memory_consolidation.py tests/integration/test_memory_consolidation_lifecycle.py tests/integration/test_memory_consolidation_concurrency.py tests/integration/test_memory_supersede_chain.py tests/integration/test_memory_catchup_sweep.py tests/integration/test_memory_startup.py -q
```

Expected: all PASS.

- [ ] **Step 3: Lint and type check**

```bash
ruff check sebastian/memory/ sebastian/capabilities/tools/memory_save/ sebastian/capabilities/tools/memory_search/ sebastian/store/
mypy sebastian/memory/ sebastian/capabilities/tools/memory_save/ sebastian/capabilities/tools/memory_search/
```

Expected: no errors.

- [ ] **Step 4: Update CHANGELOG**

Under `## [Unreleased]`, add to `Fixed`:

```markdown
- Context Lane 改为 query-aware FTS 检索，用户问"今天项目 A 情况"不再随机返回近期事实
- `memory_search` 工具复用 Assembler 过滤逻辑，与自动注入路径行为一致
- `proposed_actions` 中非 EXPIRE 动作现在写入 DISCARD 审计日志，不再静默丢弃
- `profile_store.expire()` 返回 rowcount，write_router 对 0 命中记录 trace 告警
- Profile Lane 检索改为置信度优先排序，符合 artifact-model §9 可信度优先级原则
- `RelationCandidateRecord` 补 source 字段，写入和检索链路完整保留来源语义
```

```bash
git add CHANGELOG.md
git commit -m "docs(memory): 更新 CHANGELOG 记录 spec 二轮审查修复项"
```

- [ ] **Step 5: Handoff summary**

Confirm which tasks completed, which tests ran, any deviations from this plan.

**Deferred items (do not implement in this plan):**
- Cross-session consolidation
- Memory maintenance worker (degradation, dedup, index repair)
- Summary replacement policy
- Exclusive relation time-bound semantics
- Provider temperature support
- pending/needs_review candidate pool (spec not yet written)

# Memory Phase A Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Memory（记忆）system foundation: protocol models, slot registry, SQLite schema, FTS segmentation helpers, and decision log storage.

**Architecture:** This phase creates the stable non-LLM core. It does not integrate BaseAgent prompt injection and does not call LLMs. Existing `EpisodicMemory` remains a session history compatibility layer.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, SQLite + FTS5, jieba, pytest, pytest-asyncio.

---

## File Structure

Create:

- `sebastian/memory/types.py`
  - Pydantic models and enums: `MemoryKind`, `MemoryScope`, `MemoryStatus`, `MemorySource`, `MemoryDecisionType`, `MemoryArtifact`, `CandidateArtifact`, `ResolveDecision`, `SlotDefinition`.
- `sebastian/memory/slots.py`
  - Built-in slot definitions, `SlotRegistry`, and helper functions to validate slot IDs.
- `sebastian/memory/segmentation.py`
  - jieba setup, entity userdict support, `segment_for_fts()`, `terms_for_query()`.
- `sebastian/memory/decision_log.py`
  - `MemoryDecisionLogger` wrapper for writing decision log records.
- `tests/unit/memory/test_types.py`
- `tests/unit/memory/test_slots.py`
- `tests/unit/memory/test_segmentation.py`
- `tests/unit/memory/test_decision_log.py`

Modify:

- `sebastian/store/models.py`
  - Add ORM records for memory tables.
- `sebastian/store/database.py`
  - Add idempotent migrations for new columns only if needed. `Base.metadata.create_all()` should create new tables.
- `sebastian/memory/README.md`
  - Update module responsibility and file tree.
- `docs/architecture/spec/memory/storage.md`
  - Update if implementation discovers a schema naming correction.

Do not modify:

- `sebastian/core/base_agent.py`
- `sebastian/memory/episodic_memory.py`
- `sebastian/capabilities/tools/`

## Database Tables

Add these ORM records in `sebastian/store/models.py`:

- `MemorySlotRecord`
  - `slot_id: str PK`
  - `scope: str`
  - `subject_kind: str`
  - `cardinality: str`
  - `resolution_policy: str`
  - `kind_constraints: dict[str, Any]`
  - `description: str`
  - `is_builtin: bool`
  - `created_at: datetime`
  - `updated_at: datetime`

- `ProfileMemoryRecord`
  - `id: str PK`
  - `subject_id: str index`
  - `scope: str index`
  - `slot_id: str index`
  - `kind: str`
  - `content: str`
  - `structured_payload: dict[str, Any]`
  - `source: str`
  - `confidence: float`
  - `status: str index`
  - `valid_from: datetime | None`
  - `valid_until: datetime | None`
  - `provenance: dict[str, Any]`
  - `policy_tags: list[str]`
  - `created_at: datetime`
  - `updated_at: datetime`
  - `last_accessed_at: datetime | None`
  - `access_count: int`

- `EpisodeMemoryRecord`
  - `id: str PK`
  - `subject_id: str index`
  - `scope: str index`
  - `session_id: str | None index`
  - `kind: str`
  - `content: str`
  - `content_segmented: str`
  - `structured_payload: dict[str, Any]`
  - `source: str`
  - `confidence: float`
  - `status: str index`
  - `recorded_at: datetime index`
  - `provenance: dict[str, Any]`
  - `links: list[str]`
  - `policy_tags: list[str]`
  - `last_accessed_at: datetime | None`
  - `access_count: int`

- `EntityRecord`
  - `id: str PK`
  - `canonical_name: str index`
  - `entity_type: str index`
  - `aliases: list[str]`
  - `metadata: dict[str, Any]`
  - `created_at: datetime`
  - `updated_at: datetime`

- `RelationCandidateRecord`
  - `id: str PK`
  - `subject_id: str index`
  - `predicate: str index`
  - `source_entity_id: str | None`
  - `target_entity_id: str | None`
  - `content: str`
  - `structured_payload: dict[str, Any]`
  - `confidence: float`
  - `status: str index`
  - `provenance: dict[str, Any]`
  - `created_at: datetime`

- `MemoryDecisionLogRecord`
  - `id: str PK`
  - `decision: str index`
  - `subject_id: str index`
  - `scope: str index`
  - `slot_id: str | None index`
  - `candidate: dict[str, Any]`
  - `conflicts: list[dict[str, Any]]`
  - `reason: str`
  - `old_memory_ids: list[str]`
  - `new_memory_id: str | None`
  - `worker: str`
  - `model: str | None`
  - `rule_version: str`
  - `created_at: datetime index`

FTS5 table requirement:

- Phase A does not create the FTS5 virtual table.
- Phase A only provides `content_segmented` schema fields and `segmentation.py` helpers.
- Phase B `sebastian/memory/episode_store.py` owns the raw FTS5 DDL helper and startup initialization, because SQLAlchemy `Base.metadata.create_all()` does not create SQLite virtual tables.

## Task 1: Protocol Models

**Files:**

- Create: `sebastian/memory/types.py`
- Test: `tests/unit/memory/test_types.py`

- [ ] **Step 1: Write failing enum/model tests**

```python
from datetime import UTC, datetime

from pydantic import ValidationError

from sebastian.memory.types import CandidateArtifact, MemoryKind, MemorySource, MemoryStatus


def test_candidate_artifact_accepts_required_fields() -> None:
    artifact = CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="用户偏好简洁中文回复",
        structured_payload={"language": "zh-CN", "style": "concise"},
        subject_hint="owner",
        scope="user",
        slot_id="user.preference.response_style",
        cardinality="single",
        resolution_policy="supersede",
        confidence=0.96,
        source=MemorySource.EXPLICIT,
        evidence=[{"type": "message_span", "message_id": "msg_1", "text": "以后简洁中文"}],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )

    assert artifact.kind is MemoryKind.PREFERENCE
    assert artifact.confidence == 0.96


def test_candidate_artifact_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        CandidateArtifact(
            kind=MemoryKind.FACT,
            content="bad",
            structured_payload={},
            subject_hint=None,
            scope="user",
            slot_id=None,
            cardinality=None,
            resolution_policy=None,
            confidence=1.5,
            source=MemorySource.INFERRED,
            evidence=[],
            valid_from=None,
            valid_until=None,
            policy_tags=[],
            needs_review=True,
        )
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/memory/test_types.py -v`

Expected: FAIL because `sebastian.memory.types` does not exist.

- [ ] **Step 3: Implement `types.py`**

Implementation requirements:

- Use `from __future__ import annotations`.
- Use `enum.StrEnum`.
- Use Pydantic `BaseModel`.
- Validate `confidence` with `ge=0.0, le=1.0`.
- Keep field names exactly aligned with `docs/architecture/spec/memory/artifact-model.md`.

Required enums:

```python
class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    EPISODE = "episode"
    SUMMARY = "summary"
    ENTITY = "entity"
    RELATION = "relation"
```

Also define:

- `MemoryScope`
- `MemorySource`
- `MemoryStatus`
- `MemoryDecisionType`
- `Cardinality`
- `ResolutionPolicy`

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_types.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/types.py tests/unit/memory/test_types.py
git commit -m "feat(memory): 定义记忆协议类型" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 2: Slot Registry

**Files:**

- Create: `sebastian/memory/slots.py`
- Test: `tests/unit/memory/test_slots.py`

- [ ] **Step 1: Write failing slot tests**

Tests must cover:

- Built-in `user.preference.response_style` exists and is `single/supersede`.
- `SlotRegistry().get("unknown")` returns `None`.
- `SlotRegistry().require("unknown")` raises a specific error.
- `fact` and `preference` candidates without a slot are marked invalid by helper.
- Tests import `SlotRegistry` from `sebastian.memory.slots`; this type name is part of the Phase B resolver contract.

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/memory/test_slots.py -v`

Expected: FAIL because `slots.py` does not exist.

- [ ] **Step 3: Implement built-in slots and registry**

Minimum built-in slot IDs:

- `user.preference.response_style`
- `user.preference.language`
- `user.current_project_focus`
- `user.profile.timezone`
- `project.current_phase`
- `agent.current_assignment`

Do not overbuild a huge slot catalog in Phase A.

Required public API:

```python
class SlotRegistry:
    def __init__(self, slots: Iterable[SlotDefinition] | None = None) -> None: ...
    def get(self, slot_id: str) -> SlotDefinition | None: ...
    def require(self, slot_id: str) -> SlotDefinition: ...
    def validate_candidate(self, candidate: CandidateArtifact) -> list[str]: ...


DEFAULT_SLOT_REGISTRY = SlotRegistry()
```

Rules:

- `SlotRegistry` can be a thin dict-backed wrapper in Phase A.
- `validate_candidate()` should reject `fact` / `preference` candidates that require profile resolution but have no slot.
- Do not add dynamic slot mutation APIs until a concrete admin use case exists.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_slots.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/slots.py tests/unit/memory/test_slots.py
git commit -m "feat(memory): 新增语义槽位注册表" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 3: Chinese FTS Segmentation Helpers

**Files:**

- Create: `sebastian/memory/segmentation.py`
- Test: `tests/unit/memory/test_segmentation.py`
- Modify: `pyproject.toml` only if `jieba>=0.42` is not already present. It is currently present in `[project.optional-dependencies].memory`.

- [ ] **Step 1: Write failing segmentation tests**

Tests must cover:

- `segment_for_fts("用户偏好简洁中文回复")` contains `用户`, `偏好`, `中文`.
- `terms_for_query("用户偏好")` returns only terms with length greater than 1.
- `add_entity_terms(["小橘", "ForgeAgent"])` makes those names searchable.
- English tokens like `LLM` and `Memory Artifact` are preserved.

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/memory/test_segmentation.py -v`

Expected: FAIL because helper module does not exist.

- [ ] **Step 3: Implement segmentation helpers**

Required functions:

```python
def add_entity_terms(terms: Iterable[str]) -> None: ...
def segment_for_fts(text: str) -> str: ...
def terms_for_query(query: str) -> list[str]: ...
```

Rules:

- Use `jieba.cut_for_search()`.
- Strip whitespace.
- Filter empty tokens.
- `terms_for_query()` filters tokens with `len(token) <= 1`.
- Do not import jieba in module import path if memory extra is missing without raising a clear error. Raise `RuntimeError("jieba is required for memory FTS segmentation. Install sebastian[memory].")`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/memory/test_segmentation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/segmentation.py tests/unit/memory/test_segmentation.py
git commit -m "feat(memory): 新增中文 FTS 分词辅助" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 4: ORM Schema

**Files:**

- Modify: `sebastian/store/models.py`
- Test: `tests/unit/memory/test_schema.py`

- [ ] **Step 1: Write schema creation test**

Use a temporary SQLite URL and `Base.metadata.create_all()` to assert the following tables exist:

- `memory_slots`
- `profile_memories`
- `episode_memories`
- `entities`
- `relation_candidates`
- `memory_decision_log`

Do not require FTS5 virtual table in this ORM test.

- [ ] **Step 2: Run failing test**

Run: `pytest tests/unit/memory/test_schema.py -v`

Expected: FAIL because records do not exist.

- [ ] **Step 3: Add ORM records**

Add records exactly as listed in the “Database Tables” section above.

Important:

- Use `JSON` for list/dict fields.
- Use `DateTime` for time fields.
- Use indexes on `subject_id`, `scope`, `slot_id`, `status`, and `recorded_at` where specified.
- Avoid SQLAlchemy reserved attribute name `metadata`; use `entity_metadata` as Python attribute mapped to column `"metadata"` if needed.

- [ ] **Step 4: Run test**

Run: `pytest tests/unit/memory/test_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Run existing DB tests**

Run: `pytest tests/unit -q`

Expected: PASS or only unrelated failures already present before this change. Investigate any failure involving `store.models`.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/models.py tests/unit/memory/test_schema.py
git commit -m "feat(memory): 新增记忆系统数据库模型" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 5: Decision Log Writer

**Files:**

- Create: `sebastian/memory/decision_log.py`
- Test: `tests/unit/memory/test_decision_log.py`

- [ ] **Step 1: Write failing decision log test**

Test that `MemoryDecisionLogger.append()` writes a `MemoryDecisionLogRecord` with:

- `decision="ADD"`
- `subject_id="owner"`
- `slot_id="user.preference.response_style"`
- `candidate` payload preserved
- `worker="unit-test"`
- `rule_version="v1"`

- [ ] **Step 2: Run failing test**

Run: `pytest tests/unit/memory/test_decision_log.py -v`

Expected: FAIL because logger does not exist.

- [ ] **Step 3: Implement logger**

Constructor:

```python
class MemoryDecisionLogger:
    def __init__(self, db_session: AsyncSession) -> None: ...
```

Method:

```python
async def append(self, decision: ResolveDecision, *, worker: str, model: str | None, rule_version: str) -> MemoryDecisionLogRecord: ...
```

Rules:

- Add record to session.
- Flush before returning.
- Do not commit internally; caller controls transaction.

- [ ] **Step 4: Run test**

Run: `pytest tests/unit/memory/test_decision_log.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/decision_log.py tests/unit/memory/test_decision_log.py
git commit -m "feat(memory): 新增记忆决策日志写入器" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Task 6: README And Spec Sync

**Files:**

- Modify: `sebastian/memory/README.md`
- Modify: `docs/architecture/spec/memory/storage.md` only if implementation names differ from planned names.

- [ ] **Step 1: Update README**

README must state:

- Existing `episodic_memory.py` is session history compatibility layer.
- New foundation files: `types.py`, `slots.py`, `segmentation.py`, `decision_log.py`.
- True Episode Store is not implemented until Phase B.

- [ ] **Step 2: Run docs-only verification**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 3: Commit**

```bash
git add sebastian/memory/README.md docs/architecture/spec/memory/storage.md
git commit -m "docs(memory): 更新记忆基础设施说明" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

## Phase A Completion Criteria

- [ ] `pytest tests/unit/memory -q` passes.
- [ ] `pytest tests/unit -q` passes or unrelated pre-existing failures are documented.
- [ ] `ruff check sebastian/memory sebastian/store/models.py tests/unit/memory` passes.
- [ ] No BaseAgent behavior changes.
- [ ] No LLM calls introduced.
- [ ] No vector DB or embedding dependency introduced.

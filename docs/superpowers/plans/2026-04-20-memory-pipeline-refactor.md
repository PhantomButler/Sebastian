# Memory Pipeline Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 memory write pipeline 的核心 D→E→log 模式提取到 `pipeline.py::process_candidates()`，同时将 `memory_save` 工具改为 fire-and-forget + LLM 提取 slot，并修复所有因接口变更而破坏的测试。

**Architecture:** 新建 `sebastian/memory/pipeline.py` 提供 `process_candidates()` 函数，统一 validate→resolve→persist→log 流程。`memory_save` 工具接口简化为 `content: str`，在后台任务中调用 `MemoryExtractor` 分配 slot 后走 `process_candidates()`。`consolidation.py` 的 summaries 和 proposed_artifacts 两个循环合并为单次 `process_candidates()` 调用。

**Tech Stack:** Python 3.12+, SQLAlchemy async, pytest-asyncio, pydantic, asyncio.create_task

---

## 文件改动总览

| 操作 | 路径 |
|------|------|
| Create | `sebastian/memory/pipeline.py` |
| Create | `tests/unit/memory/test_pipeline.py` |
| Modify | `sebastian/gateway/state.py` |
| Modify | `sebastian/gateway/app.py` |
| Modify | `sebastian/capabilities/tools/memory_save/__init__.py` |
| Modify | `sebastian/memory/consolidation.py` |
| Modify | `tests/unit/capabilities/test_memory_tools.py` |

---

## Task 1: 创建 `sebastian/memory/pipeline.py`（TDD）

**Files:**
- Create: `sebastian/memory/pipeline.py`
- Create: `tests/unit/memory/test_pipeline.py`

- [ ] **Step 1: 写 failing 测试**

新建 `tests/unit/memory/test_pipeline.py`，内容如下：

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base

if TYPE_CHECKING:
    pass


async def _make_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    return async_sessionmaker(engine, expire_on_commit=False)


def _preference_candidate():
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )
    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="以后回答简洁中文",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def _bad_slot_candidate():
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )
    return CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="no.such.slot",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


@pytest.mark.asyncio
async def test_process_candidates_empty_list_returns_empty() -> None:
    from sebastian.memory.pipeline import process_candidates

    factory = await _make_db_factory()
    async with factory() as db_session:
        from sebastian.memory.decision_log import MemoryDecisionLogger
        from sebastian.memory.entity_registry import EntityRegistry
        from sebastian.memory.episode_store import EpisodeMemoryStore
        from sebastian.memory.profile_store import ProfileMemoryStore
        from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

        decisions = await process_candidates(
            [],
            session_id="s1",
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="test",
            model_name=None,
            rule_version="test_v1",
            input_source={"type": "test"},
        )
    assert decisions == []


@pytest.mark.asyncio
async def test_process_candidates_add_persists_profile_record() -> None:
    from sqlalchemy import select

    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.types import MemoryDecisionType
    from sebastian.store.models import ProfileMemoryRecord

    factory = await _make_db_factory()
    async with factory() as db_session:
        from sebastian.memory.decision_log import MemoryDecisionLogger
        from sebastian.memory.entity_registry import EntityRegistry
        from sebastian.memory.episode_store import EpisodeMemoryStore
        from sebastian.memory.profile_store import ProfileMemoryStore
        from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

        decisions = await process_candidates(
            [_preference_candidate()],
            session_id="s1",
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="test",
            model_name=None,
            rule_version="test_v1",
            input_source={"type": "test"},
        )
        await db_session.commit()

        rows = (await db_session.scalars(select(ProfileMemoryRecord))).all()

    assert len(decisions) == 1
    assert decisions[0].decision == MemoryDecisionType.ADD
    assert len(rows) == 1
    assert rows[0].content == "以后回答简洁中文"
    assert rows[0].slot_id == "user.preference.response_style"


@pytest.mark.asyncio
async def test_process_candidates_invalid_slot_logs_discard_no_db_record() -> None:
    from sqlalchemy import select

    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.types import MemoryDecisionType
    from sebastian.store.models import MemoryDecisionLogRecord, ProfileMemoryRecord

    factory = await _make_db_factory()
    async with factory() as db_session:
        from sebastian.memory.decision_log import MemoryDecisionLogger
        from sebastian.memory.entity_registry import EntityRegistry
        from sebastian.memory.episode_store import EpisodeMemoryStore
        from sebastian.memory.profile_store import ProfileMemoryStore
        from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

        decisions = await process_candidates(
            [_bad_slot_candidate()],
            session_id="s1",
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="test",
            model_name=None,
            rule_version="test_v1",
            input_source={"type": "test"},
        )
        await db_session.commit()

        profile_rows = (await db_session.scalars(select(ProfileMemoryRecord))).all()
        log_rows = (await db_session.scalars(select(MemoryDecisionLogRecord))).all()

    assert len(decisions) == 1
    assert decisions[0].decision == MemoryDecisionType.DISCARD
    assert len(profile_rows) == 0
    assert len(log_rows) == 1
    assert log_rows[0].decision == MemoryDecisionType.DISCARD.value


@pytest.mark.asyncio
async def test_process_candidates_input_source_in_decision_log() -> None:
    from sqlalchemy import select

    from sebastian.memory.pipeline import process_candidates
    from sebastian.store.models import MemoryDecisionLogRecord

    factory = await _make_db_factory()
    async with factory() as db_session:
        from sebastian.memory.decision_log import MemoryDecisionLogger
        from sebastian.memory.entity_registry import EntityRegistry
        from sebastian.memory.episode_store import EpisodeMemoryStore
        from sebastian.memory.profile_store import ProfileMemoryStore
        from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY

        await process_candidates(
            [_preference_candidate()],
            session_id="sess-99",
            agent_type="default",
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="my_worker",
            model_name=None,
            rule_version="test_v1",
            input_source={"type": "my_worker", "session_id": "sess-99"},
        )
        await db_session.commit()

        rows = (await db_session.scalars(select(MemoryDecisionLogRecord))).all()

    assert len(rows) == 1
    assert rows[0].input_source["type"] == "my_worker"
    assert rows[0].input_source["session_id"] == "sess-99"
```

- [ ] **Step 2: 运行确认测试 fail**

```bash
pytest tests/unit/memory/test_pipeline.py -v
```

期望输出：`ModuleNotFoundError: No module named 'sebastian.memory.pipeline'`

- [ ] **Step 3: 实现 `sebastian/memory/pipeline.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sebastian.memory.errors import InvalidCandidateError
from sebastian.memory.resolver import resolve_candidate
from sebastian.memory.subject import resolve_subject
from sebastian.memory.types import MemoryDecisionType, ResolveDecision
from sebastian.memory.write_router import persist_decision

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import SlotRegistry
    from sebastian.memory.types import CandidateArtifact


async def process_candidates(
    candidates: list[CandidateArtifact],
    *,
    session_id: str,
    agent_type: str,
    db_session: AsyncSession,
    profile_store: ProfileMemoryStore,
    episode_store: EpisodeMemoryStore,
    entity_registry: EntityRegistry,
    decision_logger: MemoryDecisionLogger,
    slot_registry: SlotRegistry,
    worker_id: str,
    model_name: str | None,
    rule_version: str,
    input_source: dict[str, Any],
) -> list[ResolveDecision]:
    """Process candidate artifacts through the full write pipeline.

    For each candidate:
    1. Resolve subject_id from candidate.scope + session context
    2. Validate against slot registry (DISCARD + log on failure)
    3. Resolve against existing memories (ADD/SUPERSEDE/MERGE/DISCARD)
    4. Persist non-DISCARD decisions
    5. Append to decision log

    Returns all ResolveDecision objects including DISCARDs.
    Does NOT handle EXPIRE actions — those stay inline in the caller.
    Does NOT commit the db_session — caller is responsible.
    """
    decisions: list[ResolveDecision] = []

    for candidate in candidates:
        subject_id = await resolve_subject(
            candidate.scope,
            session_id=session_id,
            agent_type=agent_type,
        )
        try:
            slot_registry.validate_candidate(candidate)
        except InvalidCandidateError as e:
            decision = ResolveDecision(
                decision=MemoryDecisionType.DISCARD,
                reason=f"validate: {e}",
                old_memory_ids=[],
                new_memory=None,
                candidate=candidate,
                subject_id=subject_id,
                scope=candidate.scope,
                slot_id=candidate.slot_id,
            )
            await decision_logger.append(
                decision,
                worker=worker_id,
                model=model_name,
                rule_version=rule_version,
                input_source=input_source,
            )
            decisions.append(decision)
            continue

        decision = await resolve_candidate(
            candidate,
            subject_id=subject_id,
            profile_store=profile_store,
            slot_registry=slot_registry,
            episode_store=episode_store,
        )

        if decision.decision != MemoryDecisionType.DISCARD and decision.new_memory is not None:
            await persist_decision(
                decision,
                session=db_session,
                profile_store=profile_store,
                episode_store=episode_store,
                entity_registry=entity_registry,
            )

        await decision_logger.append(
            decision,
            worker=worker_id,
            model=model_name,
            rule_version=rule_version,
            input_source=input_source,
        )
        decisions.append(decision)

    return decisions
```

- [ ] **Step 4: 运行确认测试 pass**

```bash
pytest tests/unit/memory/test_pipeline.py -v
```

期望输出：4 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/pipeline.py tests/unit/memory/test_pipeline.py
git commit -m "feat(memory): 新增 pipeline.py process_candidates() 统一 write pipeline

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 在 `state.py` 和 `app.py` 中暴露 `memory_extractor`

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: 修改 `state.py`，添加 `memory_extractor` 字段**

在 `sebastian/gateway/state.py` 的 `TYPE_CHECKING` 块中新增 import，并在模块级变量区新增字段。

在 `if TYPE_CHECKING:` 块末尾追加：
```python
    from sebastian.memory.extraction import MemoryExtractor
```

在 `consolidation_scheduler: MemoryConsolidationScheduler | None = None` 一行之后插入：
```python
memory_extractor: MemoryExtractor | None = None
```

- [ ] **Step 2: 修改 `app.py`，将 extractor 存入 state**

在 `sebastian/gateway/app.py` 中 `state.consolidation_scheduler = consolidation_scheduler` 这行之后插入：
```python
    state.memory_extractor = extractor
```

- [ ] **Step 3: 运行已有测试确认没有回归**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -v -k "disabled or no_db"
```

期望输出：`test_memory_save_disabled_returns_error` 和 `test_memory_save_no_db_returns_error` 通过（这两个测试不受此次改动影响）。

- [ ] **Step 4: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py
git commit -m "feat(memory): state 暴露 memory_extractor 供 memory_save 后台任务使用

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 重写 `memory_save/__init__.py`

**Files:**
- Modify: `sebastian/capabilities/tools/memory_save/__init__.py`

接口变更：`content: str` 唯一参数，fire-and-forget，后台调 `MemoryExtractor` + `process_candidates()`。增加 `_pending_tasks` set 和 `drain_pending_saves()` 供测试等待后台任务完成。

- [ ] **Step 1: 完整替换文件内容**

```python
from __future__ import annotations

import asyncio
import logging

import sebastian.gateway.state as state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.memory.trace import preview_text, trace
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pending task registry — used by drain_pending_saves() in tests
# ---------------------------------------------------------------------------

_pending_tasks: set[asyncio.Task[None]] = set()


async def drain_pending_saves() -> None:
    """Wait for all in-flight background save tasks to complete.

    This function is intended for use in tests only. In production code,
    background tasks complete independently and callers must not block on them.
    """
    pending = list(_pending_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ---------------------------------------------------------------------------
# Background save task
# ---------------------------------------------------------------------------


async def _do_save(content: str, session_id: str | None, agent_type: str) -> None:
    """Background task: extract candidate artifacts via LLM, then persist them."""
    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.extraction import ExtractorInput
    from sebastian.memory.pipeline import process_candidates
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
    from sebastian.memory.subject import resolve_subject
    from sebastian.memory.types import MemoryScope

    extractor = getattr(state, "memory_extractor", None)
    if extractor is None:
        trace("tool.memory_save.bg_skip", reason="no_extractor")
        return

    subject_id = await resolve_subject(
        MemoryScope.USER,
        session_id=session_id or "",
        agent_type=agent_type,
    )

    extractor_input = ExtractorInput(
        subject_context={"subject_id": subject_id, "agent_type": agent_type},
        conversation_window=[{"role": "user", "content": content}],
        known_slots=[s.model_dump() for s in DEFAULT_SLOT_REGISTRY.list_all()],
    )
    candidates = await extractor.extract(extractor_input)

    if not candidates:
        trace("tool.memory_save.bg_skip", reason="extractor_empty")
        return

    # Inject session evidence so provenance is traceable per session
    if session_id is not None:
        candidates = [
            c.model_copy(update={"evidence": [{"session_id": session_id}]})
            for c in candidates
        ]

    async with state.db_factory() as db_session:
        decisions = await process_candidates(
            candidates,
            session_id=session_id or "",
            agent_type=agent_type,
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            worker_id="memory_save_tool",
            model_name=None,
            rule_version="phase_b_v1",
            input_source={"type": "memory_save_tool", "session_id": session_id},
        )
        await db_session.commit()

    trace(
        "tool.memory_save.bg_done",
        decision_count=len(decisions),
    )


def _log_bg_error(t: asyncio.Task[None]) -> None:
    if t.cancelled():
        return
    exc = t.exception()
    if exc is not None:
        logger.error("memory_save background task failed: %s", exc, exc_info=exc)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool(
    name="memory_save",
    description=(
        "保存用户明确要求记住的内容。"
        "仅当用户直接要求你记住某件事时调用，例如"帮我记住……"。"
    ),
    permission_tier=PermissionTier.LOW,
)
async def memory_save(content: str) -> ToolResult:
    trace(
        "tool.memory_save.start",
        content_preview=preview_text(content),
    )

    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能当前已关闭，无法保存。")

    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储暂时不可用，无法保存，请稍后再试。")

    session_id: str | None = getattr(state, "current_session_id", None) or None
    agent_type: str = getattr(state, "current_agent_type", "default") or "default"

    task: asyncio.Task[None] = asyncio.create_task(
        _do_save(content, session_id, agent_type),
        name=f"memory_save_{session_id}",
    )
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    task.add_done_callback(_log_bg_error)

    trace("tool.memory_save.dispatched", session_id=session_id)
    return ToolResult(ok=True, output={"message": "已记住，正在后台保存。"})
```

- [ ] **Step 2: 运行不受破坏的测试确认依然通过**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -v -k "disabled or no_db"
```

期望输出：2 passed

- [ ] **Step 3: Commit**

```bash
git add sebastian/capabilities/tools/memory_save/__init__.py
git commit -m "refactor(memory): memory_save 改为 fire-and-forget，后台用 extractor 分配 slot

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 重构 `consolidation.py` 使用 `process_candidates()`

**Files:**
- Modify: `sebastian/memory/consolidation.py`

将 summaries 循环（约 302-351 行）和 proposed_artifacts 循环（约 353-416 行）合并为一次 `process_candidates()` 调用。EXPIRE 动作循环保持原样（约 421-514 行）不变。

- [ ] **Step 1: 读取 consolidation.py 的 import 区域（约 1-50 行）确认当前 import**

```bash
# 确认需要移除的 import：InvalidCandidateError, resolve_candidate（由 pipeline 内部使用）
```

Run: `head -50 sebastian/memory/consolidation.py`

- [ ] **Step 2: 修改 consolidation.py**

在 `_consolidate_session` 方法内找到以下三处 import（在方法内部 lazy import 区，约 197-206 行）：

原有（局部 import 中有）：
```python
            from sebastian.memory.errors import InvalidCandidateError
            from sebastian.memory.resolver import resolve_candidate
```

删除这两行（它们只在 summaries/artifacts 循环中使用，现在由 pipeline.py 封装）。

新增：
```python
            from sebastian.memory.pipeline import process_candidates
            from sebastian.memory.types import MemoryKind
```

然后将 **summaries 循环**（302-351 行）和 **proposed_artifacts 循环**（353-416 行）整体替换为：

```python
            # Build CandidateArtifact list from summaries + proposed_artifacts,
            # then run the unified write pipeline.
            summary_candidates: list[CandidateArtifact] = []
            for summary in result.summaries:
                summary_candidates.append(
                    CandidateArtifact(
                        kind=MemoryKind.SUMMARY,
                        content=summary.content,
                        structured_payload={},
                        subject_hint=context_subject_id,
                        scope=summary.scope,
                        slot_id=None,
                        cardinality=None,
                        resolution_policy=None,
                        confidence=0.8,
                        source=MemorySource.SYSTEM_DERIVED,
                        evidence=[{"session_id": session_id}],
                        valid_from=None,
                        valid_until=None,
                        policy_tags=[],
                        needs_review=False,
                    )
                )

            all_candidates = summary_candidates + result.proposed_artifacts
            all_decisions = await process_candidates(
                all_candidates,
                session_id=session_id,
                agent_type=agent_type,
                db_session=session,
                profile_store=profile_store,
                episode_store=episode_store,
                entity_registry=entity_registry,
                decision_logger=decision_logger,
                slot_registry=DEFAULT_SLOT_REGISTRY,
                worker_id=self._WORKER_ID,
                model_name=model_name,
                rule_version=self._RULE_VERSION,
                input_source={
                    "type": "session_consolidation",
                    "session_id": session_id,
                    "agent_type": agent_type,
                },
            )

            for d in all_decisions:
                if d.decision == MemoryDecisionType.DISCARD:
                    persisted_counts["discard"] += 1
                elif d.candidate.kind == MemoryKind.SUMMARY:
                    persisted_counts["summary"] += 1
                else:
                    persisted_counts["artifact"] += 1
```

- [ ] **Step 3: 运行 consolidation 单元测试确认通过**

```bash
pytest tests/unit/memory/test_consolidation.py -v
```

期望输出：all passed（无回归）

- [ ] **Step 4: Commit**

```bash
git add sebastian/memory/consolidation.py
git commit -m "refactor(memory): consolidation 用 process_candidates() 替换重复的 D→E→log 循环

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 修复 `tests/unit/capabilities/test_memory_tools.py` 中破坏的测试

**Files:**
- Modify: `tests/unit/capabilities/test_memory_tools.py`

**变更说明：**
- `memory_save` 接口已简化为 `content: str`，fire-and-forget 返回 `ok=True`
- 所有需要验证 DB 状态的测试必须先调用 `await drain_pending_saves()`
- 所有需要控制 pipeline 行为的测试需要通过 `state_module.memory_extractor` mock extractor
- monkeypatch 目标从 `sebastian.capabilities.tools.memory_save.resolve_candidate` 改为 `sebastian.memory.pipeline.resolve_candidate`
- 两个概念已失效的测试（同步校验 slot_id 参数）改为验证新的语义

- [ ] **Step 1: 运行当前测试确认哪些 fail**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -v -k "memory_save"
```

期望：多个 memory_save 测试 fail（`TypeError: memory_save() got an unexpected keyword argument 'slot_id'` 等）

- [ ] **Step 2: 替换所有 memory_save 测试（保留 memory_search 测试不动）**

将文件中 `# memory_save tests` 到 `# memory_search tests` 之间（约 84-149 行）的全部内容替换为以下内容：

```python
# ---------------------------------------------------------------------------
# memory_save tests
# ---------------------------------------------------------------------------


def _preference_candidate():
    """Valid CandidateArtifact for use in mocked extractor responses."""
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )
    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="以后回答简洁中文",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def _mock_extractor(monkeypatch, candidates):
    """Patch state.memory_extractor with an AsyncMock returning `candidates`."""
    from unittest.mock import AsyncMock, MagicMock
    mock = MagicMock()
    mock.extract = AsyncMock(return_value=candidates)
    monkeypatch.setattr(state_module, "memory_extractor", mock, raising=False)
    return mock


@pytest.mark.asyncio
async def test_memory_save_returns_ok(enabled_memory_state, monkeypatch, caplog) -> None:
    """memory_save 立即返回 ok=True，后台保存后 DB 有记录。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.memory.types import MemoryStatus
    from sebastian.store.models import ProfileMemoryRecord

    _mock_extractor(monkeypatch, [_preference_candidate()])
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")

    result = await memory_save(content="以后回答简洁中文")

    assert result.ok is True
    assert result.output == {"message": "已记住，正在后台保存。"}

    await drain_pending_saves()

    async with enabled_memory_state() as session:
        rows = (await session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].content == "以后回答简洁中文"
    assert rows[0].slot_id == "user.preference.response_style"
    assert rows[0].status == MemoryStatus.ACTIVE.value
    assert "MEMORY_TRACE tool.memory_save.bg_done" in caplog.text


@pytest.mark.asyncio
async def test_memory_save_extractor_empty_skips_save(
    enabled_memory_state, monkeypatch, caplog
) -> None:
    """extractor 返回空列表时，后台任务不写入任何记录。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.store.models import ProfileMemoryRecord

    _mock_extractor(monkeypatch, [])
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")

    result = await memory_save(content="用户喜欢深色主题")

    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as session:
        rows = (await session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 0
    assert "tool.memory_save.bg_skip" in caplog.text


@pytest.mark.asyncio
async def test_memory_save_disabled_returns_error(disabled_memory_state) -> None:
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(content="some content")

    assert result.ok is False
    assert "关闭" in (result.error or "")


@pytest.mark.asyncio
async def test_memory_save_no_db_returns_error(no_db_state) -> None:
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(content="some content")

    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_memory_save_invalid_slot_logs_discard(
    enabled_memory_state, monkeypatch
) -> None:
    """extractor 返回未知 slot 的 candidate → validate 失败 → DISCARD 进 decision log，无 DB 记录。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )
    from sebastian.store.models import MemoryDecisionLogRecord, ProfileMemoryRecord

    bad_candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="no.such.slot",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    _mock_extractor(monkeypatch, [bad_candidate])

    result = await memory_save(content="x")
    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as s:
        profile_rows = (await s.scalars(select(ProfileMemoryRecord))).all()
        log_rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(profile_rows) == 0
    assert len(log_rows) == 1
    assert log_rows[0].decision == "discard"


@pytest.mark.asyncio
async def test_memory_save_discard_writes_decision_log(
    enabled_memory_state, monkeypatch
) -> None:
    """resolver 返回 DISCARD 时 decision log 有记录。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    _mock_extractor(monkeypatch, [_preference_candidate()])

    async def fake_resolve(
        candidate,
        *,
        subject_id,
        profile_store,
        slot_registry,
        episode_store=None,
    ) -> ResolveDecision:
        return ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason="test",
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        )

    monkeypatch.setattr("sebastian.memory.pipeline.resolve_candidate", fake_resolve)

    result = await memory_save(content="x")
    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) == 1
    assert rows[0].decision == MemoryDecisionType.DISCARD.value


@pytest.mark.asyncio
async def test_memory_save_decision_log_has_input_source(
    enabled_memory_state, monkeypatch
) -> None:
    """decision log 的 input_source["type"] == "memory_save_tool"。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.store.models import MemoryDecisionLogRecord

    monkeypatch.setattr(_state, "current_session_id", "sess-tool-123", raising=False)
    _mock_extractor(monkeypatch, [_preference_candidate()])

    result = await memory_save(content="以后回答简洁中文")
    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) >= 1
    for row in rows:
        assert row.input_source is not None
        assert row.input_source["type"] == "memory_save_tool"


@pytest.mark.asyncio
async def test_memory_save_provenance_contains_session_id(
    enabled_memory_state, monkeypatch
) -> None:
    """保存的记忆 provenance 包含 session_id 和 evidence。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.store.models import ProfileMemoryRecord

    monkeypatch.setattr(_state, "current_session_id", "sess-memory-save", raising=False)
    _mock_extractor(monkeypatch, [_preference_candidate()])

    result = await memory_save(content="以后回答简洁中文")
    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    prov = rows[0].provenance
    assert prov is not None
    assert prov.get("session_id") == "sess-memory-save"
    assert prov.get("evidence") == [{"session_id": "sess-memory-save"}]


@pytest.mark.asyncio
async def test_memory_save_provenance_no_session_id_when_absent(
    enabled_memory_state, monkeypatch
) -> None:
    """未设置 session_id 时 provenance.evidence 为空列表，无 session_id 键。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.store.models import ProfileMemoryRecord

    monkeypatch.setattr(_state, "current_session_id", None, raising=False)
    _mock_extractor(monkeypatch, [_preference_candidate()])

    result = await memory_save(content="以后回答简洁中文")
    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    prov = rows[0].provenance
    assert prov is not None
    assert prov.get("evidence") == []
    assert "session_id" not in prov


@pytest.mark.asyncio
async def test_memory_save_discard_decision_log_has_input_source(
    enabled_memory_state, monkeypatch
) -> None:
    """DISCARD 路径下 decision log 也有 input_source["type"] == "memory_save_tool"。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import drain_pending_saves, memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    _mock_extractor(monkeypatch, [_preference_candidate()])

    async def fake_resolve(
        candidate,
        *,
        subject_id,
        profile_store,
        slot_registry,
        episode_store=None,
    ) -> ResolveDecision:
        return ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason="test-discard",
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        )

    monkeypatch.setattr("sebastian.memory.pipeline.resolve_candidate", fake_resolve)

    result = await memory_save(content="x")
    assert result.ok is True
    await drain_pending_saves()

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) == 1
    assert rows[0].input_source is not None
    assert rows[0].input_source["type"] == "memory_save_tool"
```

- [ ] **Step 3: 运行全部 memory_save 测试**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -v -k "memory_save"
```

期望输出：11 passed, 0 failed

- [ ] **Step 4: 运行全部 test_memory_tools.py 确认 memory_search 测试无回归**

```bash
pytest tests/unit/capabilities/test_memory_tools.py -v
```

期望输出：all passed

- [ ] **Step 5: 运行全量测试确认无回归**

```bash
pytest tests/unit/ -v
```

期望输出：all passed（本次改动不影响其他模块）

- [ ] **Step 6: Commit**

```bash
git add tests/unit/capabilities/test_memory_tools.py
git commit -m "test(memory): 修复 memory_save 测试以适配 fire-and-forget + extractor 接口

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 自检（Self-Review）

### Spec 覆盖度检查

| 需求 | 对应 Task |
|------|-----------|
| `memory_save` 接口只有 `content: str` | Task 3 |
| `memory_save` 使用 `MemoryExtractor` 分配 slot | Task 3 |
| `memory_save` fire-and-forget，立即返回 | Task 3 |
| extractor 返回空 → 跳过，不写 fallback | Task 3 |
| `process_candidates()` 统一 D→E→log | Task 1 |
| `consolidation.py` summaries+artifacts 用 `process_candidates()` | Task 4 |
| EXPIRE 保持 inline，不进 `process_candidates()` | Task 4（保留原有 EXPIRE 循环不改动） |
| decision log 有 input_source | Task 1 & Task 5 |
| 所有破坏的测试修复 | Task 5 |

### No-Placeholder 检查

所有任务均包含完整可运行代码，无 "TBD" / "similar to above" 等占位符。

### 类型一致性检查

- `process_candidates()` 参数 `db_session: AsyncSession` —— Task 4 调用处传 `session`（同类型，命名相同）✓
- Task 3 `_do_save` 调用 `process_candidates()` 时所有参数对齐 Task 1 定义 ✓
- `drain_pending_saves()` 在 Task 3 定义，Task 5 从 `sebastian.capabilities.tools.memory_save` import ✓
- `_mock_extractor` 在 Task 5 定义为模块级辅助函数，所有测试复用 ✓

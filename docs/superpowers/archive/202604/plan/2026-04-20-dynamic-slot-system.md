# Dynamic Slot System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Sebastian 记忆模块从"6 个硬编码 slot"升级为"可持久化、运行时可扩展"的 slot 系统，Extractor/Consolidator 可 LLM 驱动提议新 slot，memory_save tool 同步返回真实结果。

**Architecture:** 新增 `SlotProposalHandler` 共享组件（命名校验 + 字段校验 + 并发 race 处理），Extractor/Consolidator 共用。现有 `memory_slots` 表扩两列（proposed_by / proposed_in_session），走项目已有的 `_apply_idempotent_migrations()` patch 机制。启动时 `bootstrap_from_db()` 把 DB slot 灌入内存 registry；运行时 `register()` 保持 DB ↔ 内存同步。Pipeline `process_candidates()` 先处理 proposed_slots（savepoint 隔离 IntegrityError）后走现有 candidates 循环，共享同一事务。memory_save tool 由 fire-and-forget 改为同步 await + 超时 15s。

**Tech Stack:** Python 3.12+、SQLAlchemy async、Pydantic v2、pytest-asyncio、aiosqlite

**Spec:** `docs/superpowers/specs/2026-04-20-dynamic-slot-system-design.md`

---

## 现有代码盘点（实现前必读）

- **表已存在**：`memory_slots`（model `MemorySlotRecord` 在 `sebastian/store/models.py:107`），字段：`slot_id / scope / subject_kind / cardinality / resolution_policy / kind_constraints / description / is_builtin / created_at / updated_at`
- **无 Alembic**：项目用 `Base.metadata.create_all()` + `_apply_idempotent_migrations()`（`sebastian/store/database.py:68`）做 schema patch
- **seed 已存在**：`seed_builtin_slots()` 在 `sebastian/memory/startup.py:56`，gateway lifespan 已调用（`sebastian/gateway/app.py:83`）
- **SlotRegistry 单例**：`DEFAULT_SLOT_REGISTRY` 在 `sebastian/memory/slots.py:141`
- **Extractor/Consolidator**：均走 Pydantic `model_validate_json()` 解析 LLM 输出，已有 `max_retries` 机制
- **memory_save tool**：`sebastian/capabilities/tools/memory_save/__init__.py`，目前 fire-and-forget
- **Consolidator 输出**：`ConsolidationResult`（`sebastian/memory/consolidation.py:59`）含 summaries / proposed_artifacts / proposed_actions，无 proposed_slots

**关键偏离 spec 的现实调整**：
- spec §6 说"新建 `slot_definitions` 表" → **改为** 复用现有 `memory_slots` 表，仅 ALTER 加两列
- spec §6 写 Alembic migration → **改为** 在 `_apply_idempotent_migrations()` patches 列表追加两行
- spec §7 `SlotDefinitionStore` → 类名保留，但操作的表是 `memory_slots` / model 是 `MemorySlotRecord`（避免在 plan 里再换名导致引用混乱，实现里统一叫 `SlotDefinitionStore`）

---

## File Structure

**新建文件：**
- `sebastian/memory/slot_definition_store.py` — `SlotDefinitionStore`：`memory_slots` 表 CRUD + `MemorySlotRecord ↔ SlotDefinition` 互转
- `sebastian/memory/slot_proposals.py` — `ProposedSlot` 命名/字段校验器 + `SlotProposalHandler.register_or_reuse()`
- `sebastian/memory/prompts.py` — 共享 prompt 构造器（`build_slot_rules_section` / `build_extractor_prompt` / `build_consolidator_prompt`）
- `sebastian/memory/feedback.py` — `render_memory_save_summary(MemorySaveResult) -> str`
- `sebastian/memory/constants.py` — 常量（`MEMORY_SAVE_TIMEOUT_SECONDS = 15.0`）
- `tests/unit/memory/test_slot_definition_store.py`
- `tests/unit/memory/test_slot_proposals.py`
- `tests/unit/memory/test_slot_registry_bootstrap.py`
- `tests/unit/memory/test_prompts.py`
- `tests/unit/memory/test_feedback.py`
- `tests/unit/memory/test_extraction_with_proposed_slots.py`
- `tests/unit/memory/test_pipeline_proposed_slots_flow.py`
- `tests/integration/memory/test_memory_save_sync_result.py`
- `tests/integration/memory/test_memory_save_proposes_new_slot.py`
- `tests/integration/memory/test_session_consolidation_proposes_slots.py`

**修改文件：**
- `sebastian/memory/types.py` — 新增 `ProposedSlot`
- `sebastian/store/models.py:107-119` — `MemorySlotRecord` 加 `proposed_by` / `proposed_in_session` 两列
- `sebastian/store/database.py:73-84` — `_apply_idempotent_migrations()` patches 列表追加两行
- `sebastian/memory/slots.py` — 加 `register()` / `bootstrap_from_db()`；`_BUILTIN_SLOTS` 加 3 条
- `sebastian/memory/extraction.py` — `ExtractorOutput` 加 `proposed_slots`；`extract()` 返回 `ExtractorOutput`；新增 `extract_with_slot_retry()` 路径
- `sebastian/memory/consolidation.py` — `ConsolidationResult` 加 `proposed_slots`；Worker 适配新 pipeline 签名
- `sebastian/memory/pipeline.py` — `process_candidates()` 签名扩展 + proposed_slots 处理步骤
- `sebastian/memory/startup.py` — 新增 `bootstrap_slot_registry()` helper
- `sebastian/gateway/app.py` — lifespan 里调 `bootstrap_slot_registry()`
- `sebastian/capabilities/tools/memory_save/__init__.py` — 同步化 + `MemorySaveResult` + 超时

---

## Task 1: `ProposedSlot` 类型

**Files:**
- Modify: `sebastian/memory/types.py`
- Test: `tests/unit/memory/test_types.py`（如不存在则新建）

- [ ] **Step 1: 在 `tests/unit/memory/test_types.py` 追加 ProposedSlot 测试（文件不存在则创建）**

```python
# tests/unit/memory/test_types.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
)


def test_proposed_slot_minimum_valid() -> None:
    slot = ProposedSlot(
        slot_id="user.profile.location",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户居住地",
    )
    assert slot.slot_id == "user.profile.location"


def test_proposed_slot_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        ProposedSlot(
            slot_id="user.profile.x",
            scope=MemoryScope.USER,
            subject_kind="user",
            cardinality=Cardinality.SINGLE,
            resolution_policy=ResolutionPolicy.SUPERSEDE,
            kind_constraints=[MemoryKind.FACT],
            description="x",
            spurious="not allowed",  # type: ignore[call-arg]
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_types.py -v`
Expected: ImportError on `ProposedSlot`（未定义）

- [ ] **Step 3: 在 `sebastian/memory/types.py` 追加 `ProposedSlot`（紧跟 `SlotDefinition` 之后）**

```python
class ProposedSlot(BaseModel):
    """LLM 提议的新 slot，由 Extractor/Consolidator 产出，经 SlotProposalHandler 验证后注册。"""

    model_config = ConfigDict(extra="forbid")

    slot_id: str
    scope: MemoryScope
    subject_kind: str
    cardinality: Cardinality
    resolution_policy: ResolutionPolicy
    kind_constraints: list[MemoryKind]
    description: str
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_types.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/types.py tests/unit/memory/test_types.py
git commit -m "feat(memory): 新增 ProposedSlot 类型

Spec A Task 1: LLM 提议新 slot 的载体，extra=forbid 强制字段规范。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: `memory_slots` 表扩列（proposed_by / proposed_in_session）

**Files:**
- Modify: `sebastian/store/models.py:107-119`
- Modify: `sebastian/store/database.py:73-84`
- Test: `tests/unit/store/test_memory_slots_schema.py`（新建）

- [ ] **Step 1: 先写 schema 迁移测试**

```python
# tests/unit/store/test_memory_slots_schema.py
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sebastian.store.database import _apply_idempotent_migrations
from sebastian.store.models import Base


@pytest.mark.asyncio
async def test_memory_slots_has_new_columns_after_migration() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
        result = await conn.exec_driver_sql("PRAGMA table_info(memory_slots)")
        columns = {row[1] for row in result.fetchall()}
    assert "proposed_by" in columns
    assert "proposed_in_session" in columns


@pytest.mark.asyncio
async def test_migration_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
        await _apply_idempotent_migrations(conn)  # 二次调用不应抛
        result = await conn.exec_driver_sql("PRAGMA table_info(memory_slots)")
        columns = [row[1] for row in result.fetchall()]
    assert columns.count("proposed_by") == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/store/test_memory_slots_schema.py -v`
Expected: FAIL — 列不存在

- [ ] **Step 3: 修改 `sebastian/store/models.py` 的 `MemorySlotRecord`（line 107）**

```python
class MemorySlotRecord(Base):
    __tablename__ = "memory_slots"

    slot_id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)
    subject_kind: Mapped[str] = mapped_column(String)
    cardinality: Mapped[str] = mapped_column(String)
    resolution_policy: Mapped[str] = mapped_column(String)
    kind_constraints: Mapped[list[str]] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String)
    is_builtin: Mapped[bool] = mapped_column(Boolean)
    proposed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_in_session: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
```

- [ ] **Step 4: 修改 `sebastian/store/database.py:73-84` patches 列表，末尾追加两行**

```python
    patches: list[tuple[str, str, str]] = [
        ("llm_providers", "thinking_capability", "VARCHAR(20)"),
        ("agent_llm_bindings", "thinking_effort", "VARCHAR(16)"),
        ("memory_decision_log", "input_source", "TEXT"),
        ("profile_memories", "cardinality", "VARCHAR"),
        ("profile_memories", "resolution_policy", "VARCHAR"),
        ("profile_memories", "content_segmented", "VARCHAR DEFAULT ''"),
        ("episode_memories", "valid_from", "DATETIME"),
        ("episode_memories", "valid_until", "DATETIME"),
        ("relation_candidates", "policy_tags", "TEXT"),
        ("relation_candidates", "source", "VARCHAR DEFAULT 'system_derived'"),
        ("memory_slots", "proposed_by", "TEXT"),
        ("memory_slots", "proposed_in_session", "TEXT"),
    ]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/unit/store/test_memory_slots_schema.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py tests/unit/store/test_memory_slots_schema.py
git commit -m "feat(memory): memory_slots 表加 proposed_by / proposed_in_session

Spec A Task 2: 通过 _apply_idempotent_migrations patches 扩列，
保留 is_builtin 不动以最小化对现有 seed 流程影响。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: `SlotDefinitionStore`

**Files:**
- Create: `sebastian/memory/slot_definition_store.py`
- Test: `tests/unit/memory/test_slot_definition_store.py`

- [ ] **Step 1: 写单测**

```python
# tests/unit/memory/test_slot_definition_store.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.slot_definition_store import SlotDefinitionStore
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)
from sebastian.store.models import Base


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_schema() -> SlotDefinition:
    return SlotDefinition(
        slot_id="user.profile.hobby",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="用户爱好",
    )


@pytest.mark.asyncio
async def test_insert_and_get(session_factory) -> None:
    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        await store.insert(
            _make_schema(),
            is_builtin=False,
            proposed_by="extractor",
            proposed_in_session="sess-1",
            created_at=datetime.now(UTC),
        )
        await session.commit()

    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        row = await store.get("user.profile.hobby")
    assert row is not None
    assert row.slot_id == "user.profile.hobby"
    assert row.proposed_by == "extractor"
    assert row.proposed_in_session == "sess-1"


@pytest.mark.asyncio
async def test_duplicate_slot_id_raises(session_factory) -> None:
    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        schema = _make_schema()
        await store.insert(schema, is_builtin=False, proposed_by=None,
                           proposed_in_session=None, created_at=datetime.now(UTC))
        await session.commit()

    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        with pytest.raises(IntegrityError):
            await store.insert(_make_schema(), is_builtin=False, proposed_by=None,
                               proposed_in_session=None, created_at=datetime.now(UTC))
            await session.commit()


@pytest.mark.asyncio
async def test_list_all_returns_schemas(session_factory) -> None:
    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        await store.insert(_make_schema(), is_builtin=False, proposed_by=None,
                           proposed_in_session=None, created_at=datetime.now(UTC))
        await session.commit()

    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        rows = await store.list_all()
    assert len(rows) == 1
    assert rows[0].slot_id == "user.profile.hobby"
    assert rows[0].cardinality == Cardinality.MULTI
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_slot_definition_store.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 `sebastian/memory/slot_definition_store.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)
from sebastian.store.models import MemorySlotRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SlotDefinitionStore:
    """memory_slots 表的 CRUD 封装。纯 DB 层，不含业务逻辑。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        schema: SlotDefinition,
        *,
        is_builtin: bool,
        proposed_by: str | None,
        proposed_in_session: str | None,
        created_at: datetime,
    ) -> None:
        """INSERT 一行。slot_id 已存在时抛 sqlalchemy.exc.IntegrityError。"""
        record = MemorySlotRecord(
            slot_id=schema.slot_id,
            scope=schema.scope.value,
            subject_kind=schema.subject_kind,
            cardinality=schema.cardinality.value,
            resolution_policy=schema.resolution_policy.value,
            kind_constraints=[k.value for k in schema.kind_constraints],
            description=schema.description,
            is_builtin=is_builtin,
            proposed_by=proposed_by,
            proposed_in_session=proposed_in_session,
            created_at=created_at,
            updated_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()

    async def get(self, slot_id: str) -> MemorySlotRecord | None:
        """按 slot_id 查询，不存在返回 None。"""
        result = await self._session.execute(
            select(MemorySlotRecord).where(MemorySlotRecord.slot_id == slot_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[SlotDefinition]:
        """返回所有 slot 定义（转成 SlotDefinition schema）。"""
        result = await self._session.execute(select(MemorySlotRecord))
        return [_record_to_schema(row) for row in result.scalars().all()]


def _record_to_schema(record: MemorySlotRecord) -> SlotDefinition:
    return SlotDefinition(
        slot_id=record.slot_id,
        scope=MemoryScope(record.scope),
        subject_kind=record.subject_kind,
        cardinality=Cardinality(record.cardinality),
        resolution_policy=ResolutionPolicy(record.resolution_policy),
        kind_constraints=[MemoryKind(k) for k in record.kind_constraints],
        description=record.description,
    )
```

- [ ] **Step 4: 测试 get 断言 row 属性依赖 MemorySlotRecord 而非 SlotDefinition，修正 test 中的 assert**

重新检查上面 `test_insert_and_get`：`store.get()` 返回 `MemorySlotRecord`，`proposed_by` 是 record 字段 ✓。test 正确。

Run: `pytest tests/unit/memory/test_slot_definition_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/slot_definition_store.py tests/unit/memory/test_slot_definition_store.py
git commit -m "feat(memory): 新增 SlotDefinitionStore

Spec A Task 3: memory_slots 表的 CRUD 封装，提供 insert / get / list_all。
list_all 返回 SlotDefinition schema，get 返回 ORM record（并发冲突处理需字段细节）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: ProposedSlot 校验器（命名 + 字段组合）

**Files:**
- Create: `sebastian/memory/slot_proposals.py`（先只放校验器，handler 在 Task 5）
- Create: `sebastian/memory/errors.py`（如已存在则修改）追加 `InvalidSlotProposalError`
- Test: `tests/unit/memory/test_slot_proposals.py`

- [ ] **Step 1: 先在 `sebastian/memory/errors.py` 追加异常**

检查现有文件：

Run: `grep -n "class.*Error" sebastian/memory/errors.py`

追加：

```python
class InvalidSlotProposalError(SebastianError):
    """Slot proposal 违反命名规则 / 字段约束。"""
```

（如 `SebastianError` 不在 errors.py 而在其他地方，import 并继承同一基类，保持与 `InvalidCandidateError` / `UnknownSlotError` 一致。）

- [ ] **Step 2: 写校验器测试**

```python
# tests/unit/memory/test_slot_proposals.py
from __future__ import annotations

import pytest

from sebastian.memory.errors import InvalidSlotProposalError
from sebastian.memory.slot_proposals import validate_proposed_slot
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
)


def _make(
    *,
    slot_id: str = "user.profile.hobby",
    scope: MemoryScope = MemoryScope.USER,
    cardinality: Cardinality = Cardinality.MULTI,
    resolution_policy: ResolutionPolicy = ResolutionPolicy.APPEND_ONLY,
    kind_constraints: list[MemoryKind] | None = None,
) -> ProposedSlot:
    return ProposedSlot(
        slot_id=slot_id,
        scope=scope,
        subject_kind="user",
        cardinality=cardinality,
        resolution_policy=resolution_policy,
        kind_constraints=kind_constraints or [MemoryKind.PREFERENCE],
        description="x",
    )


def test_valid_slot_passes() -> None:
    validate_proposed_slot(_make())


@pytest.mark.parametrize(
    "bad_id",
    [
        "user.profile",                  # 段数不对
        "user.profile.like.book",        # 段数太多
        "User.profile.hobby",            # 大写
        "user.profile.like-book",        # 连字符
        "other.profile.hobby",           # 首段非合法 scope
        "a" * 70 + ".x.y",               # 超长
        ".profile.hobby",                # 空段
        "user..hobby",                   # 空段
        "user.profile.",                 # 尾空
    ],
)
def test_invalid_naming_rejected(bad_id: str) -> None:
    with pytest.raises(InvalidSlotProposalError, match="命名规则"):
        validate_proposed_slot(_make(slot_id=bad_id))


def test_scope_prefix_must_match_slot_id() -> None:
    with pytest.raises(InvalidSlotProposalError, match="scope"):
        validate_proposed_slot(_make(slot_id="user.profile.hobby", scope=MemoryScope.PROJECT))


def test_single_with_append_only_rejected() -> None:
    with pytest.raises(InvalidSlotProposalError, match="组合"):
        validate_proposed_slot(
            _make(cardinality=Cardinality.SINGLE, resolution_policy=ResolutionPolicy.APPEND_ONLY)
        )


def test_time_bound_requires_fact_or_preference() -> None:
    with pytest.raises(InvalidSlotProposalError, match="time_bound"):
        validate_proposed_slot(
            _make(
                resolution_policy=ResolutionPolicy.TIME_BOUND,
                kind_constraints=[MemoryKind.EPISODE],
            )
        )


def test_empty_kind_constraints_rejected() -> None:
    # Pydantic 允许 list 为空，校验器要把关
    with pytest.raises(InvalidSlotProposalError, match="kind_constraints"):
        validate_proposed_slot(_make(kind_constraints=[]))
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_slot_proposals.py -v`
Expected: ImportError on `validate_proposed_slot`

- [ ] **Step 4: 实现校验器 `sebastian/memory/slot_proposals.py`（只含 validate 部分）**

```python
from __future__ import annotations

import re

from sebastian.memory.errors import InvalidSlotProposalError
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ProposedSlot,
    ResolutionPolicy,
)

_SLOT_ID_PATTERN = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*\.[a-z][a-z_]*$")
_VALID_SCOPE_PREFIXES: frozenset[str] = frozenset(s.value for s in MemoryScope)
_MAX_SLOT_ID_LEN = 64


def validate_proposed_slot(proposed: ProposedSlot) -> None:
    """校验 ProposedSlot 的命名与字段组合。失败抛 InvalidSlotProposalError。"""
    _validate_naming(proposed.slot_id)
    _validate_scope_prefix(proposed.slot_id, proposed.scope)
    _validate_field_combination(proposed)


def _validate_naming(slot_id: str) -> None:
    if len(slot_id) > _MAX_SLOT_ID_LEN:
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 不符合命名规则：总长不得超过 {_MAX_SLOT_ID_LEN}"
        )
    if not _SLOT_ID_PATTERN.match(slot_id):
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 不符合命名规则：需三段 {{scope}}.{{category}}.{{attribute}}，"
            "纯小写 + 下划线"
        )
    first_segment = slot_id.split(".", 1)[0]
    if first_segment not in _VALID_SCOPE_PREFIXES:
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 不符合命名规则：首段 '{first_segment}' 必须 ∈ "
            f"{sorted(_VALID_SCOPE_PREFIXES)}"
        )


def _validate_scope_prefix(slot_id: str, scope: MemoryScope) -> None:
    first_segment = slot_id.split(".", 1)[0]
    if first_segment != scope.value:
        raise InvalidSlotProposalError(
            f"slot_id '{slot_id}' 首段 '{first_segment}' 与 scope '{scope.value}' 不一致"
        )


def _validate_field_combination(proposed: ProposedSlot) -> None:
    if not proposed.kind_constraints:
        raise InvalidSlotProposalError("kind_constraints 不得为空，至少 1 项")
    if (
        proposed.cardinality == Cardinality.SINGLE
        and proposed.resolution_policy == ResolutionPolicy.APPEND_ONLY
    ):
        raise InvalidSlotProposalError(
            "组合非法：cardinality=single + resolution_policy=append_only 矛盾"
        )
    if proposed.resolution_policy == ResolutionPolicy.TIME_BOUND:
        allowed = {MemoryKind.FACT, MemoryKind.PREFERENCE}
        if not set(proposed.kind_constraints) & allowed:
            raise InvalidSlotProposalError(
                "resolution_policy=time_bound 要求 kind_constraints 至少含 fact 或 preference"
            )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_slot_proposals.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/errors.py sebastian/memory/slot_proposals.py tests/unit/memory/test_slot_proposals.py
git commit -m "feat(memory): 新增 ProposedSlot 校验器

Spec A Task 4: 三段式命名 + scope 一致性 + 字段组合合法性检查。
handler 在 Task 5 里补齐，本 commit 只做纯函数校验。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: `SlotProposalHandler.register_or_reuse()`

**Files:**
- Modify: `sebastian/memory/slot_proposals.py`（追加 handler 类）
- Modify: `tests/unit/memory/test_slot_proposals.py`（追加 handler 测试）

- [ ] **Step 1: 追加 handler 测试到 `tests/unit/memory/test_slot_proposals.py`**

```python
# tests/unit/memory/test_slot_proposals.py 追加

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slot_proposals import SlotProposalHandler
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import SlotDefinition
from sebastian.memory.trace import MemoryTracer  # 若项目有 trace 模块
from sebastian.store.models import Base


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_register_new_slot_writes_db_and_registry(db) -> None:
    registry = SlotRegistry(slots=[])
    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        schema = await handler.register_or_reuse(
            _make(),
            proposed_by="extractor",
            proposed_in_session="sess-1",
        )
        await session.commit()
    assert schema.slot_id == "user.profile.hobby"
    assert registry.get("user.profile.hobby") is not None


@pytest.mark.asyncio
async def test_existing_slot_reused_not_overwritten(db) -> None:
    registry = SlotRegistry(slots=[])
    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        await handler.register_or_reuse(_make(), proposed_by="extractor", proposed_in_session=None)
        await session.commit()

    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        # 第二次提议同 id 但 description 不同
        schema = await handler.register_or_reuse(
            _make(),  # description="x"
            proposed_by="consolidator",
            proposed_in_session="sess-2",
        )
        await session.commit()

    # 返回的是已存在的 schema（description 仍是原 "x"，未覆盖）
    assert schema.description == "x"


@pytest.mark.asyncio
async def test_invalid_proposal_raises(db) -> None:
    registry = SlotRegistry(slots=[])
    async with db() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        bad = _make(slot_id="BAD.ID")
        with pytest.raises(InvalidSlotProposalError):
            await handler.register_or_reuse(bad, proposed_by="extractor", proposed_in_session=None)


@pytest.mark.asyncio
async def test_concurrent_race_reuses_winner(db) -> None:
    """模拟两个 session 几乎同时 insert 同一 slot_id，第二个撞 IntegrityError 后读赢家。"""
    registry = SlotRegistry(slots=[])
    # Worker A 先写入
    async with db() as session_a:
        store = SlotDefinitionStore(session_a)
        handler_a = SlotProposalHandler(store=store, registry=registry)
        await handler_a.register_or_reuse(
            _make(), proposed_by="extractor", proposed_in_session="sess-A"
        )
        await session_a.commit()

    # Worker B 清空内存 registry 后再跑，模拟"未感知已写入"
    registry_b = SlotRegistry(slots=[])
    async with db() as session_b:
        store = SlotDefinitionStore(session_b)
        handler_b = SlotProposalHandler(store=store, registry=registry_b)
        schema = await handler_b.register_or_reuse(
            _make(),  # 同 slot_id
            proposed_by="consolidator",
            proposed_in_session="sess-B",
        )
        await session_b.commit()
    # 复用赢家：拿到的是 A 写入的那行
    assert schema.slot_id == "user.profile.hobby"
    # registry_b 内存也同步了
    assert registry_b.get("user.profile.hobby") is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_slot_proposals.py -v -k handler or race or existing`
Expected: FAIL — SlotProposalHandler 未实现

- [ ] **Step 3: 追加 `SlotProposalHandler` 到 `sebastian/memory/slot_proposals.py`**

```python
# sebastian/memory/slot_proposals.py 底部追加

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy.exc import IntegrityError

from sebastian.memory.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slots import SlotRegistry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SlotProposalHandler:
    """共享组件：把 ProposedSlot 注册到系统（DB + in-memory registry）。

    不含 LLM 调用 / 不含重试循环 —— 重试策略由调用方（Extractor / Consolidator）掌控。
    """

    def __init__(self, store: SlotDefinitionStore, registry: SlotRegistry) -> None:
        self._store = store
        self._registry = registry

    async def register_or_reuse(
        self,
        proposed: ProposedSlot,
        *,
        proposed_by: Literal["extractor", "consolidator"],
        proposed_in_session: str | None,
    ) -> SlotDefinition:
        validate_proposed_slot(proposed)

        existing = self._registry.get(proposed.slot_id)
        if existing is not None:
            return existing

        schema = SlotDefinition(
            slot_id=proposed.slot_id,
            scope=proposed.scope,
            subject_kind=proposed.subject_kind,
            cardinality=proposed.cardinality,
            resolution_policy=proposed.resolution_policy,
            kind_constraints=list(proposed.kind_constraints),
            description=proposed.description,
        )

        session = self._store._session  # savepoint 作用于同一 session
        try:
            async with session.begin_nested():
                await self._store.insert(
                    schema,
                    is_builtin=False,
                    proposed_by=proposed_by,
                    proposed_in_session=proposed_in_session,
                    created_at=datetime.now(UTC),
                )
        except IntegrityError:
            # 并发 race：别的 session 已经写入
            winner_record = await self._store.get(proposed.slot_id)
            if winner_record is None:
                # 理论不可能：IntegrityError 说明冲突存在
                raise
            winner_schema = _record_to_schema_public(winner_record)
            self._registry.register(winner_schema)
            logger.info(
                "slot.proposal.concurrent_lost slot_id=%s winner_desc=%r loser_desc=%r proposed_by=%s",
                proposed.slot_id,
                winner_record.description,
                proposed.description,
                proposed_by,
            )
            return winner_schema

        self._registry.register(schema)
        logger.info(
            "slot.proposal.accepted slot_id=%s proposed_by=%s session=%s",
            proposed.slot_id,
            proposed_by,
            proposed_in_session,
        )
        return schema


def _record_to_schema_public(record) -> SlotDefinition:
    # 复用 slot_definition_store._record_to_schema 的逻辑。
    # 为避免循环 import，这里直接在本文件复刻最小映射：
    return SlotDefinition(
        slot_id=record.slot_id,
        scope=MemoryScope(record.scope),
        subject_kind=record.subject_kind,
        cardinality=Cardinality(record.cardinality),
        resolution_policy=ResolutionPolicy(record.resolution_policy),
        kind_constraints=[MemoryKind(k) for k in record.kind_constraints],
        description=record.description,
    )
```

**重要**：直接访问 `self._store._session` 有点 hacky。改为在 `SlotDefinitionStore` 加 `session` 公开属性：

```python
# sebastian/memory/slot_definition_store.py 加 property
class SlotDefinitionStore:
    ...
    @property
    def session(self):
        return self._session
```

然后在 handler 用 `self._store.session`。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_slot_proposals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/slot_proposals.py sebastian/memory/slot_definition_store.py tests/unit/memory/test_slot_proposals.py
git commit -m "feat(memory): SlotProposalHandler 注册/复用 + 并发 race 处理

Spec A Task 5: 用 session.begin_nested() savepoint 隔离 IntegrityError，
race 失败者自动读赢家并同步内存 registry。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: `SlotRegistry.bootstrap_from_db()` + `register()`

**Files:**
- Modify: `sebastian/memory/slots.py`
- Test: `tests/unit/memory/test_slot_registry_bootstrap.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/memory/test_slot_registry_bootstrap.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)
from sebastian.store.models import Base


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_bootstrap_loads_db_rows(db) -> None:
    async with db() as session:
        store = SlotDefinitionStore(session)
        await store.insert(
            SlotDefinition(
                slot_id="user.profile.hobby",
                scope=MemoryScope.USER,
                subject_kind="user",
                cardinality=Cardinality.MULTI,
                resolution_policy=ResolutionPolicy.APPEND_ONLY,
                kind_constraints=[MemoryKind.PREFERENCE],
                description="爱好",
            ),
            is_builtin=False,
            proposed_by="extractor",
            proposed_in_session=None,
            created_at=datetime.now(UTC),
        )
        await session.commit()

    registry = SlotRegistry(slots=[])
    assert registry.get("user.profile.hobby") is None

    async with db() as session:
        store = SlotDefinitionStore(session)
        await registry.bootstrap_from_db(store)

    assert registry.get("user.profile.hobby") is not None


def test_register_adds_to_memory() -> None:
    registry = SlotRegistry(slots=[])
    schema = SlotDefinition(
        slot_id="user.profile.x",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="x",
    )
    registry.register(schema)
    assert registry.get("user.profile.x") is schema


def test_register_overrides_existing() -> None:
    registry = SlotRegistry(slots=[])
    s1 = SlotDefinition(
        slot_id="user.profile.x", scope=MemoryScope.USER, subject_kind="user",
        cardinality=Cardinality.SINGLE, resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT], description="old",
    )
    s2 = s1.model_copy(update={"description": "new"})
    registry.register(s1)
    registry.register(s2)
    assert registry.get("user.profile.x").description == "new"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_slot_registry_bootstrap.py -v`
Expected: FAIL — `bootstrap_from_db` / `register` 不存在

- [ ] **Step 3: 修改 `sebastian/memory/slots.py` 的 `SlotRegistry` 类追加两个方法**

```python
# 在 SlotRegistry 类末尾（validate_candidate 之后）追加

    def register(self, schema: SlotDefinition) -> None:
        """运行时注册 / 覆盖 slot。被 SlotProposalHandler 调用。"""
        self._slots[schema.slot_id] = schema

    async def bootstrap_from_db(self, store: "SlotDefinitionStore") -> None:
        """服务启动时调用一次，把 DB 所有 slot 灌入内存。"""
        schemas = await store.list_all()
        for s in schemas:
            self._slots[s.slot_id] = s
```

在文件顶部 `if TYPE_CHECKING` 块追加：

```python
if TYPE_CHECKING:
    from sebastian.memory.slot_definition_store import SlotDefinitionStore
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_slot_registry_bootstrap.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/slots.py tests/unit/memory/test_slot_registry_bootstrap.py
git commit -m "feat(memory): SlotRegistry 加 register() / bootstrap_from_db()

Spec A Task 6: 支持运行时动态注册 + 启动时从 DB 灌入所有 slot，
解决进程重启后内存 registry 空状态问题。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 补齐 3 个 builtin seed slot

**Files:**
- Modify: `sebastian/memory/slots.py:18-73`（`_BUILTIN_SLOTS`）
- Test: `tests/unit/memory/test_builtin_slots.py`（新建）

- [ ] **Step 1: 写测试**

```python
# tests/unit/memory/test_builtin_slots.py
from __future__ import annotations

from sebastian.memory.slots import _BUILTIN_SLOTS


def test_builtin_slot_count() -> None:
    assert len(_BUILTIN_SLOTS) == 9  # 原 6 + 新 3


def test_new_seed_slots_present() -> None:
    ids = {s.slot_id for s in _BUILTIN_SLOTS}
    assert "user.profile.name" in ids
    assert "user.profile.location" in ids
    assert "user.profile.occupation" in ids
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_builtin_slots.py -v`
Expected: FAIL — 当前只有 6 条

- [ ] **Step 3: 修改 `sebastian/memory/slots.py` `_BUILTIN_SLOTS` 列表，在末尾追加 3 项**

```python
# 在现有 6 项的 closing "]" 之前追加：
    SlotDefinition(
        slot_id="user.profile.name",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户姓名",
    ),
    SlotDefinition(
        slot_id="user.profile.location",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户所在地",
    ),
    SlotDefinition(
        slot_id="user.profile.occupation",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="用户职业",
    ),
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/memory/test_builtin_slots.py -v
```

- [ ] **Step 5: 验证 seed_builtin_slots() 能把新 3 条写进 DB**

写 quick 集成测试：

```python
# tests/unit/memory/test_builtin_slots.py 追加
import pytest
from datetime import UTC
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.startup import seed_builtin_slots
from sebastian.store.models import Base, MemorySlotRecord
from sqlalchemy import select


@pytest.mark.asyncio
async def test_seed_writes_all_9_slots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_builtin_slots(session)
    async with factory() as session:
        result = await session.execute(select(MemorySlotRecord))
        ids = {row.slot_id for row in result.scalars().all()}
    assert {"user.profile.name", "user.profile.location", "user.profile.occupation"} <= ids
    assert len(ids) == 9
```

Run: `pytest tests/unit/memory/test_builtin_slots.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/slots.py tests/unit/memory/test_builtin_slots.py
git commit -m "feat(memory): _BUILTIN_SLOTS 补齐 name/location/occupation 3 个 seed

Spec A Task 7: 9 个 builtin slot 全集。seed_builtin_slots() 已 idempotent，
新增的 3 条会在下次启动时自动写入 memory_slots 表。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Prompts 模块

**Files:**
- Create: `sebastian/memory/prompts.py`
- Test: `tests/unit/memory/test_prompts.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/memory/test_prompts.py
from __future__ import annotations

import json

import pytest

from sebastian.memory.extraction import ExtractorOutput  # 会在 Task 9 扩展
from sebastian.memory.prompts import (
    build_consolidator_prompt,
    build_extractor_prompt,
    build_slot_rules_section,
    group_slots_by_kind,
)
from sebastian.memory.slots import _BUILTIN_SLOTS


def test_group_slots_by_kind_buckets_correctly() -> None:
    grouped = group_slots_by_kind(_BUILTIN_SLOTS)
    assert "fact" in grouped
    assert "preference" in grouped
    fact_ids = {s["slot_id"] for s in grouped["fact"]}
    assert "user.profile.name" in fact_ids


def test_extractor_prompt_contains_required_sections() -> None:
    prompt = build_extractor_prompt(group_slots_by_kind(_BUILTIN_SLOTS))
    assert "输出契约" in prompt
    assert "CandidateArtifact 字段" in prompt
    assert "ProposedSlot 字段" in prompt
    assert "Slot 选择规则" in prompt
    assert "Cardinality" in prompt
    assert "示例 1" in prompt
    assert "示例 2" in prompt
    assert "示例 3" in prompt


def test_consolidator_prompt_includes_extractor_sections_plus_summary() -> None:
    prompt = build_consolidator_prompt(group_slots_by_kind(_BUILTIN_SLOTS))
    assert "CandidateArtifact 字段" in prompt
    assert "Consolidator 额外任务" in prompt
    assert "summaries" in prompt
    assert "EXPIRE" in prompt


def test_embedded_examples_parse_as_extractor_output() -> None:
    """示例 JSON 必须能被 ExtractorOutput 解析，防止 prompt 示例随代码演进腐坏。"""
    from sebastian.memory.prompts import _EXAMPLE_1_JSON, _EXAMPLE_2_JSON, _EXAMPLE_3_JSON
    for example_json in (_EXAMPLE_1_JSON, _EXAMPLE_2_JSON, _EXAMPLE_3_JSON):
        parsed = ExtractorOutput.model_validate_json(example_json)
        assert isinstance(parsed.artifacts, list)
        assert isinstance(parsed.proposed_slots, list)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_prompts.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 `sebastian/memory/prompts.py`**

```python
from __future__ import annotations

from collections.abc import Iterable

from sebastian.memory.types import SlotDefinition


def group_slots_by_kind(slots: Iterable[SlotDefinition]) -> dict[str, list[dict]]:
    """按 kind_constraints 把 slot 分桶。一个 slot 含多个 kind 时复制到所有桶。"""
    grouped: dict[str, list[dict]] = {}
    for s in slots:
        entry = {
            "slot_id": s.slot_id,
            "cardinality": s.cardinality.value,
            "resolution_policy": s.resolution_policy.value,
            "description": s.description,
        }
        for kind in s.kind_constraints:
            grouped.setdefault(kind.value, []).append(entry)
    return grouped


_EXAMPLE_1_JSON = """\
{
  "artifacts": [
    {
      "kind": "preference",
      "content": "用户喜欢看《三体》",
      "structured_payload": {"title": "三体"},
      "subject_hint": null,
      "scope": "user",
      "slot_id": "user.profile.like_book",
      "cardinality": null,
      "resolution_policy": null,
      "confidence": 0.95,
      "source": "explicit",
      "evidence": [{"quote": "我喜欢看三体"}],
      "valid_from": null,
      "valid_until": null,
      "policy_tags": [],
      "needs_review": false
    }
  ],
  "proposed_slots": []
}"""

_EXAMPLE_2_JSON = """\
{
  "artifacts": [
    {
      "kind": "fact",
      "content": "用户居住在上海浦东",
      "structured_payload": {"city": "上海", "district": "浦东"},
      "subject_hint": null,
      "scope": "user",
      "slot_id": "user.profile.location",
      "cardinality": "single",
      "resolution_policy": "supersede",
      "confidence": 0.9,
      "source": "explicit",
      "evidence": [{"quote": "我住在上海浦东"}],
      "valid_from": null,
      "valid_until": null,
      "policy_tags": [],
      "needs_review": false
    }
  ],
  "proposed_slots": [
    {
      "slot_id": "user.profile.location",
      "scope": "user",
      "subject_kind": "user",
      "cardinality": "single",
      "resolution_policy": "supersede",
      "kind_constraints": ["fact"],
      "description": "用户居住地"
    }
  ]
}"""

_EXAMPLE_3_JSON = """{"artifacts": [], "proposed_slots": []}"""


def build_slot_rules_section(known_slots_by_kind: dict[str, list[dict]]) -> str:
    import json

    slots_block = json.dumps(known_slots_by_kind, ensure_ascii=False, indent=2)
    return f"""\
# 已注册 Slot（按 kind 分组）

```json
{slots_block}
```

# Slot 选择规则

1. 只有 kind=fact 和 kind=preference 必须 slot_id 非 null；其余 kind 可 slot_id=null。
2. 优先复用 known_slots 中语义匹配的 slot，description 相近即可复用。
3. 确实找不到才进 proposed_slots 数组。artifact.slot_id 必须和 proposed_slots[i].slot_id 一致。
4. 提议的 slot_id 禁止与 known_slots 中任何已存在重名。

# Cardinality / Resolution Policy 参照表

| 语义模式 | cardinality | resolution_policy | 举例 |
|---|---|---|---|
| 唯一属性（姓名 / 时区 / 当前焦点） | single | supersede | user.profile.name |
| 可枚举偏好（喜欢的书 / 音乐） | multi | append_only | user.profile.like_book |
| 可合并集合（擅长领域 / 技能列表） | multi | merge | user.profile.skill |
| 时效性状态（本周安排 / 季度目标） | single | time_bound | user.goal.current_quarter |
| 行为 / 事件流 | multi | append_only | user.behavior.login_event |

禁止组合：cardinality=single + resolution_policy=append_only。

# 示例

## 示例 1：复用已有 slot
{_EXAMPLE_1_JSON}

## 示例 2：提议新 slot + 同一轮落 artifact
{_EXAMPLE_2_JSON}

## 示例 3：无可提取内容
{_EXAMPLE_3_JSON}
"""


_EXTRACTOR_FIELD_TABLE = """\
# 输出契约

响应必须是纯 JSON，不能有解释文字 / Markdown 围栏 / 代码块。顶层结构：

{"artifacts": [ CandidateArtifact, ... ], "proposed_slots": [ ProposedSlot, ... ]}

两个数组允许为空 []。

## CandidateArtifact 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| kind | enum | fact / preference / episode / summary / entity / relation |
| content | string | 自然语言描述，≤ 200 字 |
| structured_payload | object | 结构化载荷；无则 {} |
| subject_hint | string \\| null | 一般 null |
| scope | enum | user / session / project / agent |
| slot_id | string \\| null | 见 Slot 选择规则 |
| cardinality | enum \\| null | single / multi / null |
| resolution_policy | enum \\| null | supersede / merge / append_only / time_bound / null |
| confidence | float | 0.0 ~ 1.0 |
| source | enum | explicit / inferred / observed |
| evidence | array | [{"quote": "..."}] |
| valid_from | ISO-8601 \\| null | 一般 null |
| valid_until | ISO-8601 \\| null | 一般 null |
| policy_tags | array<string> | 一般 []，不要主动设置任何值 |
| needs_review | bool | 不确定时 true |

## ProposedSlot 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| slot_id | string | 三段式 {scope}.{category}.{attribute}，≤ 64 |
| scope | enum | 与 slot_id 首段一致 |
| subject_kind | string | user / project / agent |
| cardinality | enum | single / multi |
| resolution_policy | enum | supersede / merge / append_only / time_bound |
| kind_constraints | array<enum> | 至少 1 项 |
| description | string | 中文，≤ 40 字 |
"""


def build_extractor_prompt(known_slots_by_kind: dict[str, list[dict]]) -> str:
    rules = build_slot_rules_section(known_slots_by_kind)
    return f"""\
你是记忆提取助手。分析给定的对话内容，抽取出有记忆价值的信息。

{_EXTRACTOR_FIELD_TABLE}

{rules}
"""


def build_consolidator_prompt(known_slots_by_kind: dict[str, list[dict]]) -> str:
    base = build_extractor_prompt(known_slots_by_kind)
    addendum = """\

# Consolidator 额外任务

除了抽取 artifacts 和 proposed_slots，你还需要：

1. summaries: 对整个会话生成 1 条中文摘要（≤ 300 字），加入输出 JSON
2. proposed_actions: 对与新信息冲突的既有 artifact 提出 EXPIRE 动作

完整输出 schema：
{
  "artifacts": [...],
  "proposed_slots": [...],
  "summaries": [{"content": "...", "scope": "session"}],
  "proposed_actions": [{"action": "EXPIRE", "memory_id": "...", "reason": "..."}]
}
"""
    return base + addendum
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_prompts.py -v`
Expected: PASS（示例 JSON 自验证依赖 Task 9 里的 ExtractorOutput 扩展，所以最后 1 个测试会在 Task 9 完成后才绿——如果当前 ExtractorOutput 没有 proposed_slots 字段，示例 2 会验证失败。）

如果失败只限于最后一个测试：标记为 `@pytest.mark.xfail(reason="depends on Task 9 ExtractorOutput extension")`，Task 9 后移除 xfail。

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/prompts.py tests/unit/memory/test_prompts.py
git commit -m "feat(memory): 新增 prompts 模块共享 Extractor/Consolidator 模板

Spec A Task 8: build_slot_rules_section / build_extractor_prompt /
build_consolidator_prompt + group_slots_by_kind。3 个示例 JSON
用常量嵌入，防 prompt 与代码演进脱节。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Extractor 契约扩展（ExtractorOutput + 返回类型）

**Files:**
- Modify: `sebastian/memory/extraction.py`
- Test: `tests/unit/memory/test_extraction_with_proposed_slots.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/memory/test_extraction_with_proposed_slots.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.memory.extraction import (
    ExtractorInput,
    ExtractorOutput,
    MemoryExtractor,
)


def test_extractor_output_has_proposed_slots() -> None:
    out = ExtractorOutput(artifacts=[], proposed_slots=[])
    assert out.proposed_slots == []


def test_extractor_output_parses_full_example() -> None:
    raw = """\
    {
      "artifacts": [],
      "proposed_slots": [
        {
          "slot_id": "user.profile.location",
          "scope": "user",
          "subject_kind": "user",
          "cardinality": "single",
          "resolution_policy": "supersede",
          "kind_constraints": ["fact"],
          "description": "用户居住地"
        }
      ]
    }"""
    out = ExtractorOutput.model_validate_json(raw)
    assert len(out.proposed_slots) == 1
    assert out.proposed_slots[0].slot_id == "user.profile.location"


@pytest.mark.asyncio
async def test_extract_returns_extractor_output() -> None:
    mock_provider = MagicMock()

    async def fake_stream(**kwargs):
        from sebastian.core.stream_events import TextDelta
        yield TextDelta(delta='{"artifacts": [], "proposed_slots": []}')

    mock_provider.stream = fake_stream

    mock_registry = MagicMock()
    resolved = MagicMock(provider=mock_provider, model="fake-model")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry)
    result = await extractor.extract(
        ExtractorInput(
            subject_context={"subject_id": "u1", "agent_type": "default"},
            conversation_window=[{"role": "user", "content": "hi"}],
            known_slots=[],
        )
    )
    assert isinstance(result, ExtractorOutput)
    assert result.artifacts == []
    assert result.proposed_slots == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_extraction_with_proposed_slots.py -v`
Expected: FAIL — `proposed_slots` 字段不存在 或 `extract()` 返回 list 而非 ExtractorOutput

- [ ] **Step 3: 修改 `sebastian/memory/extraction.py`**

```python
# 1. 扩展 ExtractorOutput
from sebastian.memory.types import CandidateArtifact, ProposedSlot  # 追加 ProposedSlot

class ExtractorOutput(BaseModel):
    artifacts: list[CandidateArtifact]
    proposed_slots: list[ProposedSlot] = []   # ← 新增

# 2. extract() 返回类型从 list[CandidateArtifact] 改为 ExtractorOutput
async def extract(self, input: ExtractorInput) -> ExtractorOutput:
    ...
    empty: ExtractorOutput = ExtractorOutput(artifacts=[], proposed_slots=[])

    for attempt in range(self._max_retries + 1):
        try:
            raw = await self._call_llm(resolved, system, messages)
            return ExtractorOutput.model_validate_json(raw)
        except Exception as exc:
            if attempt < self._max_retries:
                logger.warning("Extractor attempt %d failed: %s", attempt + 1, exc)
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            logger.warning("Extractor exhausted %d retries, returning empty: %s",
                           self._max_retries + 1, exc)
            return empty
    return empty
```

- [ ] **Step 4: 更新所有 `extractor.extract()` 调用处的类型假设**

搜索调用方（PyCharm Find Usages）：

```bash
grep -rn "extractor.extract\|MemoryExtractor" sebastian/ tests/ --include="*.py" | grep -v test_extraction
```

预期调用方：
- `sebastian/capabilities/tools/memory_save/__init__.py::_do_save()`
- `sebastian/memory/consolidation.py::SessionConsolidationWorker`

这两处在 Task 14 / Task 15 里统一改签名，本 task 只改 extraction.py 本身，可能导致这两处临时类型错误。**允许**：本 task 只跑 test_extraction_with_proposed_slots.py + test_prompts.py，不跑全量。

- [ ] **Step 5: 运行测试**

```bash
pytest tests/unit/memory/test_extraction_with_proposed_slots.py tests/unit/memory/test_prompts.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/extraction.py tests/unit/memory/test_extraction_with_proposed_slots.py
git commit -m "feat(memory): ExtractorOutput 扩展 proposed_slots + extract() 返回类型

Spec A Task 9: extract() 返回 ExtractorOutput（包含 artifacts + proposed_slots），
不再返回 list。memory_save / SessionConsolidationWorker 的适配见 Task 14/15。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: Extractor slot-rejection 重试路径 + 使用新 prompt

**Files:**
- Modify: `sebastian/memory/extraction.py`（扩展 `extract()` 使用新 prompt + 新增 `extract_with_slot_retry()`）
- Test: `tests/unit/memory/test_extraction_with_proposed_slots.py`

- [ ] **Step 1: 追加重试场景测试**

```python
# tests/unit/memory/test_extraction_with_proposed_slots.py 追加

from collections import deque

from sebastian.memory.extraction import MemoryExtractor
from sebastian.memory.slot_proposals import InvalidSlotProposalError


class _SeqProvider:
    def __init__(self, payloads: list[str]) -> None:
        self._payloads = deque(payloads)
        self.call_count = 0
        self.last_messages = None

    async def stream(self, *, system, messages, tools, model, max_tokens):
        from sebastian.core.stream_events import TextDelta
        self.call_count += 1
        self.last_messages = messages
        payload = self._payloads.popleft()
        yield TextDelta(delta=payload)


@pytest.mark.asyncio
async def test_slot_retry_succeeds_second_attempt() -> None:
    bad = '{"artifacts": [], "proposed_slots": [{"slot_id": "BAD", ' \
          '"scope": "user", "subject_kind": "user", "cardinality": "single", ' \
          '"resolution_policy": "supersede", "kind_constraints": ["fact"], "description": "x"}]}'
    good = '{"artifacts": [], "proposed_slots": [{"slot_id": "user.profile.hobby", ' \
           '"scope": "user", "subject_kind": "user", "cardinality": "multi", ' \
           '"resolution_policy": "append_only", "kind_constraints": ["preference"], "description": "爱好"}]}'
    provider = _SeqProvider([bad, good])

    mock_registry = MagicMock()
    resolved = MagicMock(provider=provider, model="fake")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry)
    failed_ids: list[str] = []

    async def attempt_register(output) -> list[str]:
        # 模拟"把 BAD 视为 InvalidSlotProposalError"
        rejected = [p.slot_id for p in output.proposed_slots if p.slot_id == "BAD"]
        return rejected

    result = await extractor.extract_with_slot_retry(
        ExtractorInput(subject_context={}, conversation_window=[], known_slots=[]),
        attempt_register=attempt_register,
    )
    assert provider.call_count == 2
    assert len(result.proposed_slots) == 1
    assert result.proposed_slots[0].slot_id == "user.profile.hobby"


@pytest.mark.asyncio
async def test_slot_retry_gives_up_after_one_retry() -> None:
    bad1 = '{"artifacts": [], "proposed_slots": [{"slot_id": "BAD", ' \
           '"scope": "user", "subject_kind": "user", "cardinality": "single", ' \
           '"resolution_policy": "supersede", "kind_constraints": ["fact"], "description": "x"}]}'
    bad2 = bad1  # 第二次还是不合规
    provider = _SeqProvider([bad1, bad2])
    mock_registry = MagicMock()
    resolved = MagicMock(provider=provider, model="fake")
    mock_registry.get_provider = AsyncMock(return_value=resolved)

    extractor = MemoryExtractor(mock_registry)

    async def attempt_register(output) -> list[str]:
        return [p.slot_id for p in output.proposed_slots if p.slot_id == "BAD"]

    result = await extractor.extract_with_slot_retry(
        ExtractorInput(subject_context={}, conversation_window=[], known_slots=[]),
        attempt_register=attempt_register,
    )
    # 重试耗尽，返回最后一次的输出（失败 slot 会在外层处理）
    assert provider.call_count == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_extraction_with_proposed_slots.py::test_slot_retry_succeeds_second_attempt -v`
Expected: FAIL — `extract_with_slot_retry` 不存在

- [ ] **Step 3: 修改 `sebastian/memory/extraction.py` 使用新 prompt + 加 `extract_with_slot_retry()`**

```python
# 文件顶部 import
from sebastian.memory.prompts import build_extractor_prompt, group_slots_by_kind
from collections.abc import Awaitable, Callable

# MemoryExtractor 内加

async def extract_with_slot_retry(
    self,
    input: ExtractorInput,
    *,
    attempt_register: Callable[[ExtractorOutput], Awaitable[list[str]]],
) -> ExtractorOutput:
    """与 extract() 的区别：
    - attempt_register 回调：调用方尝试 register_or_reuse，返回被拒的 slot_id 列表
    - 若有被拒：追加 assistant + user 消息反馈，再调一次 LLM（共最多 2 次）
    """
    # 把 known_slots 按 kind 分桶供 prompt 使用
    known_slots_by_kind = _group_known_slots(input.known_slots)
    system = build_extractor_prompt(known_slots_by_kind)
    user_content = input.model_dump_json()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

    resolved = await self._registry.get_provider(MEMORY_EXTRACTOR_BINDING)
    output = await self._try_once(resolved, system, messages)

    rejected = await attempt_register(output)
    if not rejected:
        return output

    # 追加 retry 反馈
    first_raw = output.model_dump_json()
    feedback = _build_slot_retry_feedback(rejected)
    messages.extend([
        {"role": "assistant", "content": first_raw},
        {"role": "user", "content": feedback},
    ])
    retry_output = await self._try_once(resolved, system, messages)
    return retry_output


async def _try_once(
    self,
    resolved: ResolvedProvider,
    system: str,
    messages: list[dict[str, Any]],
) -> ExtractorOutput:
    """单次 LLM 调用 + JSON 解析，失败走现有 retry（max_retries 次），仍失败返回空。"""
    empty = ExtractorOutput(artifacts=[], proposed_slots=[])
    for attempt in range(self._max_retries + 1):
        try:
            raw = await self._call_llm(resolved, system, messages)
            return ExtractorOutput.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            if attempt < self._max_retries:
                logger.warning("Extractor attempt %d failed: %s", attempt + 1, exc)
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            logger.warning("Extractor exhausted retries: %s", exc)
            return empty
    return empty


def _group_known_slots(known_slots: list[dict[str, Any]]) -> dict[str, list[dict]]:
    """把 known_slots（SlotDefinition.model_dump() 列表）按 kind 分桶。"""
    grouped: dict[str, list[dict]] = {}
    for s in known_slots:
        entry = {
            "slot_id": s["slot_id"],
            "cardinality": s["cardinality"],
            "resolution_policy": s["resolution_policy"],
            "description": s["description"],
        }
        for kind in s.get("kind_constraints", []):
            grouped.setdefault(kind, []).append(entry)
    return grouped


def _build_slot_retry_feedback(rejected_ids: list[str]) -> str:
    bullets = "\n".join(f"- \"{slot_id}\"" for slot_id in rejected_ids)
    return f"""\
上一轮提议的以下 slot 不合规，请重命名后再输出一轮完整 JSON（artifacts + proposed_slots）：

失败项：
{bullets}

约束提醒：
- 三段式命名，纯小写，下划线分隔，总长 ≤ 64
- 首段必须是 user / session / project / agent 之一
- 禁止与 known_slots 已有 slot_id 重名

请重新给出完整 JSON。被拒 slot 对应的 artifact 也请一并重新给出（slot_id 改为新名字）。"""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_extraction_with_proposed_slots.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/extraction.py tests/unit/memory/test_extraction_with_proposed_slots.py
git commit -m "feat(memory): Extractor 用新 prompt + slot-rejection 重试（方案 C）

Spec A Task 10: extract_with_slot_retry() 接受 attempt_register 回调，
根据其返回的被拒 slot_id 列表决定是否追加反馈再调一次 LLM。
保留原 extract() 供无 slot 判定场景兼容。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Consolidator `proposed_slots` + 新 prompt

**Files:**
- Modify: `sebastian/memory/consolidation.py`
- Test: 扩展 `tests/unit/memory/test_extraction_with_proposed_slots.py` 或新建 `tests/unit/memory/test_consolidator.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/memory/test_consolidator.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.memory.consolidation import (
    ConsolidationResult,
    ConsolidatorInput,
    MemoryConsolidator,
)


def test_consolidation_result_has_proposed_slots() -> None:
    result = ConsolidationResult()
    assert result.proposed_slots == []


@pytest.mark.asyncio
async def test_consolidate_parses_proposed_slots() -> None:
    raw = """{
      "summaries": [],
      "proposed_artifacts": [],
      "proposed_actions": [],
      "proposed_slots": [{
        "slot_id": "user.profile.hobby",
        "scope": "user",
        "subject_kind": "user",
        "cardinality": "multi",
        "resolution_policy": "append_only",
        "kind_constraints": ["preference"],
        "description": "爱好"
      }]
    }"""
    from sebastian.core.stream_events import TextDelta

    async def fake_stream(**kwargs):
        yield TextDelta(delta=raw)

    provider = MagicMock()
    provider.stream = fake_stream

    registry = MagicMock()
    registry.get_provider = AsyncMock(
        return_value=MagicMock(provider=provider, model="fake")
    )

    consolidator = MemoryConsolidator(registry)
    result = await consolidator.consolidate(
        ConsolidatorInput(
            session_messages=[],
            candidate_artifacts=[],
            active_memories_for_subject=[],
            recent_summaries=[],
            slot_definitions=[],
            entity_registry_snapshot=[],
        )
    )
    assert len(result.proposed_slots) == 1
    assert result.proposed_slots[0].slot_id == "user.profile.hobby"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_consolidator.py -v`
Expected: FAIL — `proposed_slots` 不存在

- [ ] **Step 3: 修改 `sebastian/memory/consolidation.py`**

```python
# import 追加
from sebastian.memory.types import ProposedSlot
from sebastian.memory.prompts import build_consolidator_prompt, group_slots_by_kind

# ConsolidationResult 扩展
class ConsolidationResult(BaseModel):
    summaries: list[MemorySummary] = []
    proposed_artifacts: list[CandidateArtifact] = []
    proposed_actions: list[ProposedAction] = []
    proposed_slots: list[ProposedSlot] = []   # ← 新增

# MemoryConsolidator.consolidate() 改用新 prompt
async def consolidate(self, consolidator_input: ConsolidatorInput) -> ConsolidationResult:
    resolved = await self._registry.get_provider(MEMORY_CONSOLIDATOR_BINDING)
    self.last_resolved = resolved

    # 从 slot_definitions 字段按 kind 分组
    grouped = {}
    for s in consolidator_input.slot_definitions:
        entry = {
            "slot_id": s["slot_id"],
            "cardinality": s["cardinality"],
            "resolution_policy": s["resolution_policy"],
            "description": s["description"],
        }
        for kind in s.get("kind_constraints", []):
            grouped.setdefault(kind, []).append(entry)
    system = build_consolidator_prompt(grouped)

    messages = [{"role": "user", "content": consolidator_input.model_dump_json()}]
    empty = ConsolidationResult()

    for attempt in range(self._max_retries + 1):
        try:
            raw = await self._call_llm(resolved, system, messages)
            return ConsolidationResult.model_validate_json(raw)
        except Exception as exc:
            if attempt < self._max_retries:
                logger.warning("Consolidator attempt %d failed: %s", attempt + 1, exc)
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            logger.warning("Consolidator exhausted retries: %s", exc)
            return empty
    return empty
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_consolidator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/consolidation.py tests/unit/memory/test_consolidator.py
git commit -m "feat(memory): ConsolidationResult 扩展 proposed_slots + 新 prompt

Spec A Task 11: Consolidator 产出 proposed_slots，prompt 使用共享 helper
build_consolidator_prompt。SessionConsolidationWorker 的消费改动见 Task 15。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 12: `feedback.py` — memory_save summary 渲染

**Files:**
- Create: `sebastian/memory/feedback.py`
- Test: `tests/unit/memory/test_feedback.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/memory/test_feedback.py
from __future__ import annotations

from sebastian.memory.feedback import MemorySaveResult, render_memory_save_summary


def _make(**kwargs) -> MemorySaveResult:
    defaults = dict(
        saved_count=0,
        discarded_count=0,
        proposed_slots_registered=[],
        proposed_slots_rejected=[],
    )
    defaults.update(kwargs)
    return MemorySaveResult(**defaults, summary="")  # summary will be regen


def test_summary_single_saved() -> None:
    r = _make(saved_count=1)
    assert "已记住 1 条" in render_memory_save_summary(r)


def test_summary_multi_plus_new_slot() -> None:
    r = _make(saved_count=2, proposed_slots_registered=["user.profile.like_book"])
    out = render_memory_save_summary(r)
    assert "已记住 2 条" in out
    assert "user.profile.like_book" in out


def test_summary_partial_discard() -> None:
    r = _make(saved_count=1, discarded_count=1)
    out = render_memory_save_summary(r)
    assert "已记住 1 条" in out
    assert "跳过" in out or "重复" in out


def test_summary_all_discarded() -> None:
    r = _make(saved_count=0, discarded_count=2)
    assert "没找到明确的记忆点" in render_memory_save_summary(r)


def test_summary_slot_all_rejected() -> None:
    r = _make(saved_count=0, proposed_slots_rejected=[
        {"slot_id": "bad", "reason": "命名违规"}
    ])
    assert "提议的新分类不合规" in render_memory_save_summary(r)


def test_summary_empty_extraction() -> None:
    r = _make()
    assert "暂无可保存的记忆价值" in render_memory_save_summary(r)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_feedback.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 `sebastian/memory/feedback.py`**

```python
from __future__ import annotations

from pydantic import BaseModel


class MemorySaveResult(BaseModel):
    saved_count: int
    discarded_count: int
    proposed_slots_registered: list[str]
    proposed_slots_rejected: list[dict]
    summary: str


def render_memory_save_summary(result: MemorySaveResult) -> str:
    """根据结构化结果渲染自然语言 summary。"""
    if result.saved_count == 0:
        if result.proposed_slots_rejected and not result.proposed_slots_registered:
            return "提议的新分类不合规，未保存对应内容。"
        if result.discarded_count > 0:
            return "内容里没找到明确的记忆点。"
        return "内容暂无可保存的记忆价值。"

    parts = [f"已记住 {result.saved_count} 条"]
    if result.proposed_slots_registered:
        slot_list = "、".join(result.proposed_slots_registered)
        parts.append(f"并新增了分类 {slot_list}")
    if result.discarded_count > 0:
        parts.append(f"另有 {result.discarded_count} 条因重复被跳过")
    return "，".join(parts) + "。"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/memory/test_feedback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/feedback.py tests/unit/memory/test_feedback.py
git commit -m "feat(memory): 新增 feedback 模块 (MemorySaveResult + 渲染)

Spec A Task 12: render_memory_save_summary 覆盖 6 种场景（成功/新 slot/
部分丢弃/全丢弃/slot 全拒/空）。memory_save tool 消费这一层。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 13: `process_candidates()` 集成 proposed_slots

**Files:**
- Modify: `sebastian/memory/pipeline.py`
- Test: `tests/unit/memory/test_pipeline_proposed_slots_flow.py`

- [ ] **Step 1: 读当前 `process_candidates()` 签名确认改动范围**

Run: `grep -n "async def process_candidates" sebastian/memory/pipeline.py`

读取全函数后在本 step 决定 dataclass 返回扩展：`PipelineResult` 增加 `proposed_slots_registered: list[str]` / `proposed_slots_rejected: list[dict]`。

- [ ] **Step 2: 写测试**

```python
# tests/unit/memory/test_pipeline_proposed_slots_flow.py
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.pipeline import process_candidates
from sebastian.memory.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slot_proposals import SlotProposalHandler
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import (
    Cardinality,
    CandidateArtifact,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ProposedSlot,
    ResolutionPolicy,
)
from sebastian.store.models import Base
# 以及 ProfileMemoryStore / EpisodeMemoryStore / EntityRegistry / MemoryDecisionLogger 等
# 实际引入按 pipeline.py 的 import 复制


@pytest.fixture
async def deps():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory


def _make_candidate(slot_id: str, kind: MemoryKind = MemoryKind.PREFERENCE) -> CandidateArtifact:
    return CandidateArtifact(
        kind=kind,
        content="test",
        structured_payload={},
        subject_hint=None,
        scope=MemoryScope.USER,
        slot_id=slot_id,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.EXPLICIT,
        evidence=[{"quote": "x"}],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


@pytest.mark.asyncio
async def test_proposed_slot_registered_before_candidate(deps) -> None:
    factory = deps
    registry = SlotRegistry(slots=[])
    async with factory() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        # 其他 deps 按 pipeline.py 构造
        ...
        proposed = ProposedSlot(
            slot_id="user.profile.hobby",
            scope=MemoryScope.USER, subject_kind="user",
            cardinality=Cardinality.MULTI, resolution_policy=ResolutionPolicy.APPEND_ONLY,
            kind_constraints=[MemoryKind.PREFERENCE], description="爱好",
        )
        candidate = _make_candidate("user.profile.hobby")
        result = await process_candidates(
            candidates=[candidate],
            proposed_slots=[proposed],
            ...  # 其余参数按实际 pipeline 签名填
            slot_registry=registry,
            slot_proposal_handler=handler,
            proposed_by="extractor",
        )
        await session.commit()
    # 验证 slot 已注册 + candidate 已 resolve（非 DISCARD）
    assert "user.profile.hobby" in result.proposed_slots_registered
    assert result.saved_count >= 1


@pytest.mark.asyncio
async def test_invalid_slot_triggers_candidate_downgrade(deps) -> None:
    """命名违规的 slot → 对应 candidate 的 slot_id 被置 None → validate 阶段 DISCARD"""
    factory = deps
    registry = SlotRegistry(slots=[])
    async with factory() as session:
        store = SlotDefinitionStore(session)
        handler = SlotProposalHandler(store=store, registry=registry)
        ...
        bad_slot = ProposedSlot(
            slot_id="BAD.ID",
            ...,
        )
        candidate = _make_candidate("BAD.ID")
        result = await process_candidates(
            candidates=[candidate],
            proposed_slots=[bad_slot],
            ...,
        )
    assert len(result.proposed_slots_rejected) == 1
    # fact/preference + slot_id=None → DISCARD
    assert result.saved_count == 0
```

（测试里的 `...` 省略部分：按 `pipeline.py` 实际签名填充 profile_store / episode_store 等，实现阶段补齐。）

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/unit/memory/test_pipeline_proposed_slots_flow.py -v`
Expected: FAIL — 签名不匹配

- [ ] **Step 4: 修改 `sebastian/memory/pipeline.py`**

在 `process_candidates()` 签名加两个参数 + proposed_by，在函数体最前面加 Step 1：

```python
from sebastian.memory.slot_proposals import (
    InvalidSlotProposalError,
    SlotProposalHandler,
)
from sebastian.memory.types import ProposedSlot


async def process_candidates(
    candidates: list[CandidateArtifact],
    proposed_slots: list[ProposedSlot],   # ← 新增
    *,
    session_id: str,
    agent_type: str,
    db_session: AsyncSession,
    profile_store: ProfileMemoryStore,
    episode_store: EpisodeMemoryStore,
    entity_registry: EntityRegistry,
    decision_logger: MemoryDecisionLogger,
    slot_registry: SlotRegistry,
    slot_proposal_handler: SlotProposalHandler,   # ← 新增
    worker_id: str,
    model_name: str | None,
    rule_version: str,
    input_source: dict[str, Any],
    proposed_by: Literal["extractor", "consolidator"],   # ← 新增
) -> PipelineResult:
    # Step 1: 先处理 proposed_slots
    registered: list[str] = []
    rejected: list[dict] = []
    failed_slot_ids: set[str] = set()

    for p in proposed_slots:
        try:
            schema = await slot_proposal_handler.register_or_reuse(
                p, proposed_by=proposed_by, proposed_in_session=session_id,
            )
            registered.append(schema.slot_id)
        except InvalidSlotProposalError as exc:
            rejected.append({"slot_id": p.slot_id, "reason": str(exc)})
            failed_slot_ids.add(p.slot_id)
            logger.warning(
                "slot.proposal.rejected slot_id=%s reason=%s proposed_by=%s",
                p.slot_id, exc, proposed_by,
            )

    # Step 2: 原有 candidates 循环；降级被拒 slot 的 candidate
    effective_candidates: list[CandidateArtifact] = []
    for c in candidates:
        if c.slot_id is not None and c.slot_id in failed_slot_ids:
            downgraded = c.model_copy(update={"slot_id": None})
            effective_candidates.append(downgraded)
            logger.info(
                "slot.proposal.candidate_downgrade slot_id=%s kind=%s",
                c.slot_id, c.kind.value,
            )
        else:
            effective_candidates.append(c)

    # 原有 candidates 处理逻辑（validate → resolve → persist → log）
    # ... 保持既有代码不变 ...

    return PipelineResult(
        saved_count=...,
        discarded_count=...,
        proposed_slots_registered=registered,
        proposed_slots_rejected=rejected,
    )
```

`PipelineResult` dataclass 对应扩展两个字段。

- [ ] **Step 5: 运行单测**

Run: `pytest tests/unit/memory/test_pipeline_proposed_slots_flow.py -v`
Expected: PASS

- [ ] **Step 6: 运行 memory 模块所有单测，确认其他 pipeline 测试未被破坏**

Run: `pytest tests/unit/memory/ -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add sebastian/memory/pipeline.py tests/unit/memory/test_pipeline_proposed_slots_flow.py
git commit -m "feat(memory): process_candidates 集成 proposed_slots 处理

Spec A Task 13: slot 先于 candidate 处理；被拒 slot 对应 candidate 降级
为 slot_id=None（fact/preference 后续会被 validate DISCARD，其他 kind 正常）。
PipelineResult 扩展 proposed_slots_registered / proposed_slots_rejected。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 14: `memory_save` tool 同步化

**Files:**
- Modify: `sebastian/capabilities/tools/memory_save/__init__.py`
- Create: `sebastian/memory/constants.py`
- Test: `tests/integration/memory/test_memory_save_sync_result.py`

- [ ] **Step 1: 创建常量文件**

```python
# sebastian/memory/constants.py
from __future__ import annotations

MEMORY_SAVE_TIMEOUT_SECONDS: float = 15.0
```

- [ ] **Step 2: 写集成测试**

```python
# tests/integration/memory/test_memory_save_sync_result.py
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from sebastian.capabilities.tools.memory_save import memory_save


@pytest.mark.asyncio
async def test_success_returns_structured_result(tmp_memory_env) -> None:
    """tmp_memory_env fixture：准备临时 DB + 注入 state 的依赖"""
    # 模拟 Extractor 返回 1 个 artifact
    ...
    result = await memory_save(content="帮我记住我喜欢咖啡")
    assert result.ok is True
    assert result.output["saved_count"] >= 1
    assert "summary" in result.output
    assert "已记住" in result.output["summary"]


@pytest.mark.asyncio
async def test_timeout_returns_ok_false(tmp_memory_env) -> None:
    # Patch Extractor 为长时间阻塞
    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(20)

    with patch("sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
               side_effect=slow_extract):
        # 用 patch 把 MEMORY_SAVE_TIMEOUT_SECONDS 改成 0.1s 加速测试
        with patch("sebastian.capabilities.tools.memory_save.MEMORY_SAVE_TIMEOUT_SECONDS", 0.1):
            result = await memory_save(content="x")
    assert result.ok is False
    assert "超时" in result.error


@pytest.mark.asyncio
async def test_extractor_empty_returns_empty_summary(tmp_memory_env) -> None:
    # Patch Extractor 返回空
    ...
    result = await memory_save(content="今天天气怎么样？")
    assert result.ok is True
    assert result.output["saved_count"] == 0
    assert "暂无可保存" in result.output["summary"]
```

（`tmp_memory_env` fixture 需要在 `tests/integration/memory/conftest.py` 创建，含临时 DB + mock state。实际内容参考现有 `tests/integration/memory/` 下已有的 fixture 约定。）

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/integration/memory/test_memory_save_sync_result.py -v`
Expected: FAIL

- [ ] **Step 4: 重构 `sebastian/capabilities/tools/memory_save/__init__.py`**

```python
# 完全替换 memory_save + _do_save，移除 _pending_tasks / drain_pending_saves / _log_bg_error

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sebastian.capabilities.tool_base import PermissionTier, ToolResult, tool
from sebastian.memory.constants import MEMORY_SAVE_TIMEOUT_SECONDS
from sebastian.memory.decision_log import MemoryDecisionLogger
from sebastian.memory.entity_registry import EntityRegistry
from sebastian.memory.episode_store import EpisodeMemoryStore
from sebastian.memory.extraction import ExtractorInput, ExtractorOutput, MemoryExtractor
from sebastian.memory.feedback import MemorySaveResult, render_memory_save_summary
from sebastian.memory.pipeline import process_candidates
from sebastian.memory.profile_store import ProfileMemoryStore
from sebastian.memory.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slot_proposals import SlotProposalHandler
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.trace import trace  # 按项目实际模块

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@tool(
    name="memory_save",
    description=(
        "保存用户明确要求记住的内容。仅当用户直接要求你记住某件事时调用，例如'帮我记住……'。"
    ),
    permission_tier=PermissionTier.LOW,
)
async def memory_save(content: str) -> ToolResult:
    from sebastian.capabilities.tool_base import state  # 运行时状态

    trace("tool.memory_save.start", content_preview=content[:80])

    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能当前已关闭，无法保存。")
    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储暂时不可用，无法保存，请稍后再试。")

    session_id = getattr(state, "current_session_id", None)
    agent_type = getattr(state, "current_agent_type", "default") or "default"

    try:
        result = await asyncio.wait_for(
            _do_save(content, session_id, agent_type),
            timeout=MEMORY_SAVE_TIMEOUT_SECONDS,
        )
        trace("tool.memory_save.done", saved=result.saved_count)
        return ToolResult(ok=True, output=result.model_dump())
    except asyncio.TimeoutError:
        trace("tool.memory_save.timeout")
        return ToolResult(ok=False, error="记忆处理超时，未能保存。")
    except Exception as exc:  # noqa: BLE001
        logger.exception("memory_save failed")
        trace("tool.memory_save.error", reason=str(exc))
        return ToolResult(ok=False, error=f"保存失败：{exc}")


async def _do_save(content: str, session_id: str | None, agent_type: str) -> MemorySaveResult:
    from sebastian.capabilities.tool_base import state
    from sebastian.memory.subject import resolve_subject_id

    extractor = MemoryExtractor(state.llm_registry)
    known_slots = [
        {
            "slot_id": s.slot_id,
            "scope": s.scope.value,
            "subject_kind": s.subject_kind,
            "cardinality": s.cardinality.value,
            "resolution_policy": s.resolution_policy.value,
            "kind_constraints": [k.value for k in s.kind_constraints],
            "description": s.description,
        }
        for s in DEFAULT_SLOT_REGISTRY.list_all()
    ]

    async with state.db_factory() as db_session:
        slot_store = SlotDefinitionStore(db_session)
        handler = SlotProposalHandler(store=slot_store, registry=DEFAULT_SLOT_REGISTRY)

        async def attempt_register(output: ExtractorOutput) -> list[str]:
            """回调：尝试登记 proposed_slots；返回被拒的 slot_id。

            注意：本回调只做校验，真正的注册在 process_candidates 里统一做（保证
            与 candidate 落库的事务一致性）。这里用 validate_proposed_slot 预检。
            """
            from sebastian.memory.slot_proposals import (
                InvalidSlotProposalError,
                validate_proposed_slot,
            )
            rejected: list[str] = []
            for p in output.proposed_slots:
                try:
                    validate_proposed_slot(p)
                except InvalidSlotProposalError:
                    rejected.append(p.slot_id)
            return rejected

        extractor_output = await extractor.extract_with_slot_retry(
            ExtractorInput(
                subject_context={"agent_type": agent_type},
                conversation_window=[{"role": "user", "content": content}],
                known_slots=known_slots,
            ),
            attempt_register=attempt_register,
        )

        result = await process_candidates(
            candidates=extractor_output.artifacts,
            proposed_slots=extractor_output.proposed_slots,
            session_id=session_id or "",
            agent_type=agent_type,
            db_session=db_session,
            profile_store=ProfileMemoryStore(db_session),
            episode_store=EpisodeMemoryStore(db_session),
            entity_registry=EntityRegistry(db_session),
            decision_logger=MemoryDecisionLogger(db_session),
            slot_registry=DEFAULT_SLOT_REGISTRY,
            slot_proposal_handler=handler,
            worker_id="memory_save_tool",
            model_name=None,
            rule_version="spec-a-v1",
            input_source={"tool": "memory_save"},
            proposed_by="extractor",
        )
        await db_session.commit()

    save_result = MemorySaveResult(
        saved_count=result.saved_count,
        discarded_count=result.discarded_count,
        proposed_slots_registered=result.proposed_slots_registered,
        proposed_slots_rejected=result.proposed_slots_rejected,
        summary="",  # 下面补
    )
    save_result.summary = render_memory_save_summary(save_result)
    return save_result
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/integration/memory/test_memory_save_sync_result.py -v`
Expected: PASS

- [ ] **Step 6: 运行 memory_save 相关现有测试确认未破坏**

```bash
pytest tests/ -k memory_save -v
```
Expected: 全部 PASS；若旧测试依赖 `drain_pending_saves()` 需就地修正为直接 await。

- [ ] **Step 7: Commit**

```bash
git add sebastian/capabilities/tools/memory_save/__init__.py sebastian/memory/constants.py tests/integration/memory/test_memory_save_sync_result.py
git commit -m "refactor(memory): memory_save tool 同步化 + 结构化返回

Spec A Task 14: 由 fire-and-forget 改为 await + 超时 15s。返回 MemorySaveResult
（saved_count / discarded_count / proposed_slots_registered/rejected / summary）。
移除 _pending_tasks / drain_pending_saves。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 15: `SessionConsolidationWorker` 适配新 pipeline

**Files:**
- Modify: `sebastian/memory/consolidation.py`（`SessionConsolidationWorker.consolidate_session()`）
- Test: `tests/integration/memory/test_session_consolidation_proposes_slots.py`

- [ ] **Step 1: 先读取当前 Worker 代码定位修改点**

Run: `grep -n "class SessionConsolidationWorker\|def consolidate_session\|process_candidates" sebastian/memory/consolidation.py`

- [ ] **Step 2: 写集成测试**

```python
# tests/integration/memory/test_session_consolidation_proposes_slots.py
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_consolidator_proposes_slot_and_worker_registers_it(tmp_memory_env) -> None:
    """会话结束触发 Consolidator，返回 proposed_slots，Worker 调 pipeline 注册 + 写 artifact。"""
    # Mock Consolidator 返回一条 proposed_slot + 对应 artifact
    ...
    # 调 SessionConsolidationWorker.consolidate_session(session_id=...)
    ...
    # 断言 memory_slots 表多一行、profile_memories 多一行、decision_log 记录完整
    ...
```

- [ ] **Step 3: 修改 `SessionConsolidationWorker.consolidate_session()`**

主要改动：
1. 从 `DEFAULT_SLOT_REGISTRY.list_all()` 注入 `known_slots` 到 Extractor 调用
2. 用 `extract_with_slot_retry` 替换 `extract`
3. 构造 `SlotProposalHandler`，传给 `process_candidates`
4. `process_candidates` 调用增加 `proposed_slots=consolidator_result.proposed_slots + extractor_output.proposed_slots`（合并两处提议）
5. `proposed_by="consolidator"`

具体示例（按当前 Worker 既有结构调整）：

```python
# 在 consolidate_session 里原本的 process_candidates 调用处

slot_store = SlotDefinitionStore(db_session)
handler = SlotProposalHandler(store=slot_store, registry=DEFAULT_SLOT_REGISTRY)

# 合并 Extractor 和 Consolidator 各自提议的 slot（可能重名，由 register_or_reuse 自然去重）
all_proposed_slots = list(extractor_output.proposed_slots) + list(result.proposed_slots)

pipeline_result = await process_candidates(
    candidates=summary_candidates + result.proposed_artifacts,
    proposed_slots=all_proposed_slots,
    ...
    slot_registry=DEFAULT_SLOT_REGISTRY,
    slot_proposal_handler=handler,
    proposed_by="consolidator",
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/integration/memory/test_session_consolidation_proposes_slots.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/consolidation.py tests/integration/memory/test_session_consolidation_proposes_slots.py
git commit -m "refactor(memory): SessionConsolidationWorker 适配 proposed_slots

Spec A Task 15: Worker 合并 Extractor+Consolidator 的 proposed_slots 一起
交给 process_candidates 注册。proposed_by=consolidator。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 16: Gateway startup hook 调 `bootstrap_from_db`

**Files:**
- Modify: `sebastian/memory/startup.py`（加 `bootstrap_slot_registry` helper）
- Modify: `sebastian/gateway/app.py`（lifespan 里调用）
- Test: `tests/integration/test_gateway_startup.py`（扩展或新建）

- [ ] **Step 1: 写测试**

```python
# tests/integration/test_gateway_startup.py 追加
import pytest

from sebastian.memory.slots import SlotRegistry
from sebastian.memory.startup import bootstrap_slot_registry


@pytest.mark.asyncio
async def test_bootstrap_slot_registry_loads_all_seeds(fresh_gateway_db):
    """fresh_gateway_db fixture：init_db + seed_builtin_slots 已完成的临时 DB factory"""
    registry = SlotRegistry(slots=[])
    async with fresh_gateway_db() as session:
        await bootstrap_slot_registry(session, registry)
    # 9 个 builtin slot 应全部在内存 registry 里
    assert len(registry.list_all()) == 9
    assert registry.get("user.profile.name") is not None
```

- [ ] **Step 2: 在 `sebastian/memory/startup.py` 追加 helper**

```python
# sebastian/memory/startup.py 追加

from sebastian.memory.slot_definition_store import SlotDefinitionStore


async def bootstrap_slot_registry(session, registry) -> None:
    """服务启动时调用：把 memory_slots 表全部数据灌入 registry。"""
    store = SlotDefinitionStore(session)
    await registry.bootstrap_from_db(store)
```

- [ ] **Step 3: 修改 `sebastian/gateway/app.py` lifespan**

在现有 `seed_builtin_slots` 调用之后追加：

```python
# sebastian/gateway/app.py line ~83 附近

from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.startup import (
    bootstrap_slot_registry,
    init_memory_storage,
    seed_builtin_slots,
)

# lifespan 内：
await init_memory_storage(get_engine())
async with _session_factory() as _seed_session:
    await seed_builtin_slots(_seed_session)
# ↓ 新增
async with _session_factory() as _bootstrap_session:
    await bootstrap_slot_registry(_bootstrap_session, DEFAULT_SLOT_REGISTRY)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/integration/test_gateway_startup.py -v`
Expected: PASS

- [ ] **Step 5: 运行全量测试确认无破坏**

```bash
pytest tests/ -x
```
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/memory/startup.py sebastian/gateway/app.py tests/integration/test_gateway_startup.py
git commit -m "feat(memory): gateway 启动时 bootstrap_from_db 灌入 SlotRegistry

Spec A Task 16: seed_builtin_slots 之后调 bootstrap_slot_registry，
保证进程内 DEFAULT_SLOT_REGISTRY 与 memory_slots 表一致。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 17: memory_save 集成测试 — 提议新 slot 并落库

**Files:**
- Test: `tests/integration/memory/test_memory_save_proposes_new_slot.py`

- [ ] **Step 1: 写 E2E 场景测试**

```python
# tests/integration/memory/test_memory_save_proposes_new_slot.py
from __future__ import annotations

from unittest.mock import patch

import pytest

from sebastian.capabilities.tools.memory_save import memory_save
from sebastian.memory.extraction import ExtractorOutput
from sebastian.memory.slots import DEFAULT_SLOT_REGISTRY
from sebastian.memory.types import (
    Cardinality, CandidateArtifact, MemoryKind, MemoryScope, MemorySource,
    ProposedSlot, ResolutionPolicy,
)


@pytest.mark.asyncio
async def test_memory_save_proposes_slot_and_reuses_on_second_call(tmp_memory_env) -> None:
    """第一次调用：Extractor 提议新 slot → slot 注册 → artifact 落库
    第二次调用：known_slots 已含该 slot → 仅落 artifact 不再提议"""

    # Mock Extractor 第一次输出（提议新 slot）
    new_slot = ProposedSlot(
        slot_id="user.profile.favorite_food",
        scope=MemoryScope.USER, subject_kind="user",
        cardinality=Cardinality.MULTI, resolution_policy=ResolutionPolicy.APPEND_ONLY,
        kind_constraints=[MemoryKind.PREFERENCE], description="喜欢的食物",
    )
    artifact_1 = CandidateArtifact(
        kind=MemoryKind.PREFERENCE, content="喜欢火锅", structured_payload={},
        subject_hint=None, scope=MemoryScope.USER, slot_id="user.profile.favorite_food",
        cardinality=None, resolution_policy=None, confidence=0.9,
        source=MemorySource.EXPLICIT, evidence=[{"quote": "喜欢火锅"}],
        valid_from=None, valid_until=None, policy_tags=[], needs_review=False,
    )
    first_output = ExtractorOutput(artifacts=[artifact_1], proposed_slots=[new_slot])

    with patch("sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
               return_value=first_output):
        r1 = await memory_save(content="我喜欢吃火锅")
    assert r1.ok
    assert "user.profile.favorite_food" in r1.output["proposed_slots_registered"]
    assert DEFAULT_SLOT_REGISTRY.get("user.profile.favorite_food") is not None

    # 第二次调用：Extractor 应能感知到 slot 已存在（通过 known_slots 注入）
    artifact_2 = artifact_1.model_copy(update={"content": "也喜欢烤肉"})
    second_output = ExtractorOutput(artifacts=[artifact_2], proposed_slots=[])

    with patch("sebastian.memory.extraction.MemoryExtractor.extract_with_slot_retry",
               return_value=second_output):
        r2 = await memory_save(content="也喜欢烤肉")
    assert r2.ok
    assert r2.output["proposed_slots_registered"] == []
    assert r2.output["saved_count"] == 1
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/integration/memory/test_memory_save_proposes_new_slot.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/memory/test_memory_save_proposes_new_slot.py
git commit -m "test(memory): memory_save 提议新 slot + 二次复用 E2E

Spec A Task 17: 验证整条链路 — Extractor 提议 → 注册到 DB 和内存 registry →
后续调用自动复用，不重复提议。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 18: 全量 lint + type check + 测试 + 更新 README

**Files:**
- Modify: `sebastian/memory/README.md`（记录新组件、新 flow）
- Modify: `CHANGELOG.md`（`[Unreleased]`）

- [ ] **Step 1: 跑 lint + format + type**

```bash
ruff check sebastian/memory/ sebastian/capabilities/tools/memory_save/ sebastian/store/ tests/
ruff format sebastian/memory/ sebastian/capabilities/tools/memory_save/ sebastian/store/ tests/
mypy sebastian/memory/ sebastian/capabilities/tools/memory_save/ sebastian/store/
```

Expected: 零 error / 零 warning

- [ ] **Step 2: 跑全量测试**

```bash
pytest -x
```

Expected: 全部 PASS

- [ ] **Step 3: 更新 `sebastian/memory/README.md` 的「修改导航」段**

在现有导航表里追加：
- 新增 slot 类型 → `slots.py`（`_BUILTIN_SLOTS` 加 seed）或 Extractor/Consolidator LLM 自动提议
- slot 定义的 DB 持久化 → `memory_slots` 表（`slot_definition_store.py` CRUD）
- 修改命名规则 / 字段组合校验 → `slot_proposals.py::validate_proposed_slot`
- 修改 Extractor / Consolidator prompt → `prompts.py`
- 修改 memory_save tool 反馈文案 → `feedback.py::render_memory_save_summary`

在「数据流」段增加 Proposed Slot 新流程图（链到 `data-flow.md` 或更新 data-flow）。

- [ ] **Step 4: 更新 `CHANGELOG.md` 的 `[Unreleased]` 段**

```markdown
## [Unreleased]

### Added
- 记忆模块支持动态 Slot 系统：LLM 可提议新 slot，经命名 + 字段校验后注册到 `memory_slots` 表并同步到内存 SlotRegistry
- 3 个新 builtin slot：`user.profile.name` / `user.profile.location` / `user.profile.occupation`
- Extractor / Consolidator prompt 共享模板（`sebastian/memory/prompts.py`），内含 slot 选择规则 + 3 个 JSON 示例

### Changed
- **Breaking**：`memory_save` tool 由 fire-and-forget 改为同步返回 `MemorySaveResult`（含 `saved_count / summary / proposed_slots_registered` 等字段），主 agent 可根据 summary 决定是否告知用户
- `MemoryExtractor.extract()` 返回类型由 `list[CandidateArtifact]` 改为 `ExtractorOutput`
- `process_candidates()` 签名新增 `proposed_slots` / `slot_proposal_handler` / `proposed_by` 参数；`PipelineResult` 新增 `proposed_slots_registered` / `proposed_slots_rejected`

### Removed
- `drain_pending_saves()` helper（memory_save 同步化后不再需要）
```

- [ ] **Step 5: Commit**

```bash
git add sebastian/memory/README.md CHANGELOG.md
git commit -m "docs(memory): 同步 README 修改导航 + CHANGELOG

Spec A Task 18: 记录动态 Slot 系统的新组件入口 + breaking change（memory_save）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

实现完成前自查：

1. **Spec §6 Schema** → Task 2 ✓（加 proposed_by / proposed_in_session，复用现有 memory_slots 表）
2. **Spec §7.1 SlotDefinitionStore** → Task 3 ✓
3. **Spec §7.2 SlotProposalHandler** → Task 4 + Task 5 ✓
4. **Spec §7.3 ProposedSlot 类型** → Task 1 ✓
5. **Spec §8 SlotRegistry 扩展** → Task 6 ✓
6. **Spec §9.1 Extractor 契约** → Task 9 ✓
7. **Spec §9.2 Consolidator 契约** → Task 11 ✓
8. **Spec §9.3 重试机制 (C + X)** → Task 10（Extractor 侧） + Task 13（降级路径在 pipeline） ✓
9. **Spec §9.4 Trace 事件** → Task 5 / Task 13（logger.info 落日志） ✓
10. **Spec §10.1 process_candidates 扩展** → Task 13 ✓
11. **Spec §10.2 并发冲突** → Task 5（handler 内部 savepoint） ✓
12. **Spec §10.3 事务边界** → Task 13（单 commit 由 memory_save / Worker 外层负责） + Task 5（savepoint） ✓
13. **Spec §11.1 known_slots 分桶** → Task 8（`group_slots_by_kind`） ✓
14. **Spec §11.2 Extractor prompt** → Task 8 ✓
15. **Spec §11.3 retry 反馈** → Task 10（`_build_slot_retry_feedback`） ✓
16. **Spec §11.4 Consolidator prompt** → Task 8（`build_consolidator_prompt`） + Task 11（使用） ✓
17. **Spec §12 memory_save 同步化** → Task 14 ✓
18. **Spec §13 3 个 seed slot** → Task 7 ✓
19. **Spec §15 测试期望** → Task 1~17 的测试覆盖 9 个期望项 ✓
20. **Spec §16 向后兼容** → Task 18 CHANGELOG ✓
21. **Spec §17 验收标准 11 项** → Task 1~17 + Task 18 全量验证 ✓

---

## Open Questions / 实现期可能遇到的决策

实现时遇到以下情况可原地判断，不阻塞主流程：

1. **`SlotDefinitionStore.session` 暴露方式**：Task 5 用 property，若 lint 不喜欢可改 `get_session()` 方法。
2. **`PipelineResult` 已有字段**：Task 13 改动前先读 pipeline.py 确认现有 dataclass 结构，新增字段不要破坏既有序列化。
3. **`attempt_register` 回调的职责边界**：Task 14 里只做 validate_proposed_slot 预检（不真正 register），真正注册在 pipeline 里。好处是 Extractor 层无需接触 DB session。
4. **集成测试 fixture**：`tmp_memory_env` / `fresh_gateway_db` 可能需要新建 conftest，Task 14/15/17 实施时参考已有 `tests/integration/memory/conftest.py`（若不存在则先建基础 fixture）。
5. **现有 `drain_pending_saves()` 的测试调用处**：Task 14 commit 前全局 grep 替换。


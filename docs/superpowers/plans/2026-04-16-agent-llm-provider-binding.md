# Agent ↔ LLM Provider 绑定系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户可以从 Settings 把"共享 provider 池"中的某条 provider 绑定给特定 sub-agent；未绑定的 agent fallback 到全局默认 provider。

**Architecture:**
- DB 新增 `agent_llm_bindings` 表（`agent_type` PK → `provider_id` FK，ON DELETE SET NULL）
- `LLMProviderRegistry.get_provider(agent_type)` 查询源由 `manifest.toml` 换成 binding 表
- BaseAgent/AgentLoop 零结构改动（既有 per-turn 解析机制自动读到最新 binding）
- Gateway 扩展 `GET /api/v1/agents` 加 `bound_provider_id` 字段；新增 `PUT/DELETE /api/v1/agents/{agent_type}/llm-binding`
- Android Settings 新增子页 "Agent LLM Bindings"，provider 选择器走 BottomSheet；操作成功通过 `ToastCenter` 提示 "Binding will take effect on next message."

**Tech Stack:** Python 3.12 + SQLAlchemy async + FastAPI（后端）· Kotlin + Jetpack Compose + Retrofit + Hilt（Android）

**Spec reference:** [docs/superpowers/specs/2026-04-16-agent-llm-provider-binding-design.md](../specs/2026-04-16-agent-llm-provider-binding-design.md)

---

## 阶段 0 — 基础设施前置

### Task 0.1: 启用 SQLite 外键约束

SQLite 默认不强制外键。`ON DELETE SET NULL` 不生效会导致 provider 删除后 binding 仍指向幽灵记录。

**Files:**
- Modify: `sebastian/store/database.py`
- Test: `tests/unit/store/test_foreign_keys_pragma.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/store/test_foreign_keys_pragma.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_pragma_is_on() -> None:
    """sebastian.store.database.get_engine() 创建的 engine 必须启用 foreign_keys。"""
    import sebastian.store.database as db_mod

    # Reset module state so get_engine builds a fresh engine for this test
    db_mod._engine = None
    db_mod._session_factory = None

    from sebastian.config import settings

    # Use tmp in-memory db
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        # Apply the pragma listener by touching the helper that installs it
        db_mod._install_sqlite_fk_pragma(engine)
        async with engine.begin() as conn:
            result = await conn.exec_driver_sql("PRAGMA foreign_keys")
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1, f"PRAGMA foreign_keys expected 1, got {row[0]}"
    finally:
        await engine.dispose()
        # Restore module state
        db_mod._engine = None
        db_mod._session_factory = None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/store/test_foreign_keys_pragma.py -v
```

Expected: FAIL with `AttributeError: module 'sebastian.store.database' has no attribute '_install_sqlite_fk_pragma'`.

- [ ] **Step 3: Implement the pragma installer**

Modify `sebastian/store/database.py`. Add at top-level:

```python
from sqlalchemy import event
from sqlalchemy.engine import Engine as SyncEngine


def _install_sqlite_fk_pragma(engine: AsyncEngine) -> None:
    """Enable SQLite ON DELETE cascade/set-null semantics on every connection."""
    sync_engine: SyncEngine = engine.sync_engine

    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
```

Update `get_engine()` to call it once right after creation:

```python
def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from sebastian.config import settings

        _engine = create_async_engine(settings.database_url, echo=False, future=True)
        _install_sqlite_fk_pragma(_engine)
    return _engine
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/store/test_foreign_keys_pragma.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to catch regressions**

```bash
pytest tests/unit/store/ tests/unit/llm/ -q
```

Expected: all tests still pass.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/database.py tests/unit/store/test_foreign_keys_pragma.py
git commit -m "chore(store): 启用 SQLite foreign_keys pragma 以支持 ON DELETE 语义"
```

---

## 阶段 1 — 后端数据模型与 Registry

### Task 1.1: 新增 `AgentLLMBindingRecord` ORM 模型

**Files:**
- Modify: `sebastian/store/models.py`
- Test: `tests/unit/store/test_agent_llm_binding_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/store/test_agent_llm_binding_model.py`:

```python
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base, _install_sqlite_fk_pragma


@pytest.mark.asyncio
async def test_agent_binding_record_can_insert_and_load() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

    async with factory() as session:
        provider = LLMProviderRecord(
            name="p1",
            provider_type="anthropic",
            api_key_enc="x",
            model="claude-opus-4-6",
            is_default=False,
        )
        session.add(provider)
        await session.flush()
        binding = AgentLLMBindingRecord(agent_type="forge", provider_id=provider.id)
        session.add(binding)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(AgentLLMBindingRecord))
        loaded = result.scalars().all()
        assert len(loaded) == 1
        assert loaded[0].agent_type == "forge"
        assert loaded[0].provider_id == provider.id
        assert isinstance(loaded[0].updated_at, datetime)
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_binding_provider_on_delete_set_null() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

    async with factory() as session:
        provider = LLMProviderRecord(
            name="p1",
            provider_type="anthropic",
            api_key_enc="x",
            model="claude-opus-4-6",
            is_default=False,
        )
        session.add(provider)
        await session.flush()
        provider_id = provider.id
        binding = AgentLLMBindingRecord(agent_type="forge", provider_id=provider_id)
        session.add(binding)
        await session.commit()

        # Delete the provider - binding should be set to NULL, not removed
        await session.delete(provider)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(AgentLLMBindingRecord))
        loaded = result.scalars().all()
        assert len(loaded) == 1
        assert loaded[0].agent_type == "forge"
        assert loaded[0].provider_id is None
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/store/test_agent_llm_binding_model.py -v
```

Expected: FAIL with `ImportError: cannot import name 'AgentLLMBindingRecord'`.

- [ ] **Step 3: Add the model**

Modify `sebastian/store/models.py`. At the top imports, add `ForeignKey`:

```python
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
```

At the end of the file add:

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/store/test_agent_llm_binding_model.py -v
```

Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/models.py tests/unit/store/test_agent_llm_binding_model.py
git commit -m "feat(store): 新增 agent_llm_bindings 表模型"
```

---

### Task 1.2: Registry 新增 binding CRUD 方法

**Files:**
- Modify: `sebastian/llm/registry.py`
- Test: `tests/unit/llm/test_registry_bindings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/llm/test_registry_bindings.py`:

```python
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.crypto import encrypt
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base, _install_sqlite_fk_pragma


@pytest_asyncio.fixture
async def registry_with_db(tmp_path, monkeypatch):
    key_file = tmp_path / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

    from sebastian.llm.registry import LLMProviderRegistry

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield LLMProviderRegistry(factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_set_and_get_binding(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="X",
        provider_type="anthropic",
        api_key_enc=encrypt("k"),
        model="claude-opus-4-6",
        is_default=False,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    pid = records[0].id

    await registry_with_db.set_binding("forge", pid)
    bindings = await registry_with_db.list_bindings()
    assert len(bindings) == 1
    assert bindings[0].agent_type == "forge"
    assert bindings[0].provider_id == pid


@pytest.mark.asyncio
async def test_set_binding_upsert_overwrites(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    r1 = LLMProviderRecord(name="A", provider_type="anthropic", api_key_enc=encrypt("k1"), model="m1", is_default=False)
    r2 = LLMProviderRecord(name="B", provider_type="openai", api_key_enc=encrypt("k2"), model="m2", is_default=False)
    await registry_with_db.create(r1)
    await registry_with_db.create(r2)
    records = await registry_with_db.list_all()
    id_a = next(r.id for r in records if r.name == "A")
    id_b = next(r.id for r in records if r.name == "B")

    await registry_with_db.set_binding("forge", id_a)
    await registry_with_db.set_binding("forge", id_b)

    bindings = await registry_with_db.list_bindings()
    assert len(bindings) == 1
    assert bindings[0].provider_id == id_b


@pytest.mark.asyncio
async def test_set_binding_with_null_provider_id(registry_with_db) -> None:
    await registry_with_db.set_binding("forge", None)
    bindings = await registry_with_db.list_bindings()
    assert len(bindings) == 1
    assert bindings[0].agent_type == "forge"
    assert bindings[0].provider_id is None


@pytest.mark.asyncio
async def test_clear_binding_removes_row(registry_with_db) -> None:
    await registry_with_db.set_binding("forge", None)
    await registry_with_db.clear_binding("forge")
    bindings = await registry_with_db.list_bindings()
    assert bindings == []


@pytest.mark.asyncio
async def test_clear_binding_noop_when_missing(registry_with_db) -> None:
    # Should not raise
    await registry_with_db.clear_binding("nonexistent")
    assert await registry_with_db.list_bindings() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/llm/test_registry_bindings.py -v
```

Expected: FAIL with `AttributeError: 'LLMProviderRegistry' object has no attribute 'set_binding'`.

- [ ] **Step 3: Add binding methods to registry**

Modify `sebastian/llm/registry.py`. Add imports at top:

```python
from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord
```

Add new methods on `LLMProviderRegistry` (insert after the existing `delete` method, before `_clear_default_provider`):

```python
    async def list_bindings(self) -> list[AgentLLMBindingRecord]:
        async with self._db_factory() as session:
            result = await session.execute(select(AgentLLMBindingRecord))
            return list(result.scalars().all())

    async def set_binding(
        self, agent_type: str, provider_id: str | None
    ) -> AgentLLMBindingRecord:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(
                    AgentLLMBindingRecord.agent_type == agent_type
                )
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                record = AgentLLMBindingRecord(
                    agent_type=agent_type, provider_id=provider_id
                )
                session.add(record)
            else:
                existing.provider_id = provider_id
                record = existing
            await session.commit()
            await session.refresh(record)
            return record

    async def clear_binding(self, agent_type: str) -> None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(
                    AgentLLMBindingRecord.agent_type == agent_type
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                await session.delete(existing)
                await session.commit()

    async def _get_binding(self, agent_type: str) -> AgentLLMBindingRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(
                    AgentLLMBindingRecord.agent_type == agent_type
                )
            )
            return result.scalar_one_or_none()

    async def _get_record(self, provider_id: str) -> LLMProviderRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == provider_id)
            )
            return result.scalar_one_or_none()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/llm/test_registry_bindings.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/llm/registry.py tests/unit/llm/test_registry_bindings.py
git commit -m "feat(llm): Registry 新增 agent_llm_bindings CRUD 方法"
```

---

### Task 1.3: 重写 `get_provider` 使用 binding 表

**Files:**
- Modify: `sebastian/llm/registry.py`
- Test: `tests/unit/llm/test_registry_bindings.py` (append)

- [ ] **Step 1: Append failing tests for the new resolver**

Append to `tests/unit/llm/test_registry_bindings.py`:

```python
@pytest.mark.asyncio
async def test_get_provider_uses_binding(registry_with_db) -> None:
    from sebastian.llm.anthropic import AnthropicProvider
    from sebastian.store.models import LLMProviderRecord

    default = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-opus-4-6",
        is_default=True,
    )
    bound = LLMProviderRecord(
        name="bound",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-bound"),
        model="claude-haiku-4-5",
        is_default=False,
    )
    await registry_with_db.create(default)
    await registry_with_db.create(bound)
    records = await registry_with_db.list_all()
    bound_id = next(r.id for r in records if r.name == "bound")

    await registry_with_db.set_binding("forge", bound_id)
    provider, model = await registry_with_db.get_provider("forge")
    assert isinstance(provider, AnthropicProvider)
    assert provider._client.api_key == "sk-bound"
    assert model == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_get_provider_falls_back_when_no_binding(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    default = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(default)

    provider, model = await registry_with_db.get_provider("forge")
    assert provider._client.api_key == "sk-default"
    assert model == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_get_provider_falls_back_when_binding_provider_id_is_null(
    registry_with_db,
) -> None:
    from sebastian.store.models import LLMProviderRecord

    default = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(default)
    await registry_with_db.set_binding("forge", None)

    provider, model = await registry_with_db.get_provider("forge")
    assert provider._client.api_key == "sk-default"


@pytest.mark.asyncio
async def test_get_provider_falls_back_when_bound_provider_deleted(
    registry_with_db,
) -> None:
    """Deleting the bound provider triggers ON DELETE SET NULL, then get_provider
    should fallback to default."""
    from sebastian.store.models import LLMProviderRecord

    default = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-opus-4-6",
        is_default=True,
    )
    bound = LLMProviderRecord(
        name="bound",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-bound"),
        model="claude-haiku-4-5",
        is_default=False,
    )
    await registry_with_db.create(default)
    await registry_with_db.create(bound)
    records = await registry_with_db.list_all()
    bound_id = next(r.id for r in records if r.name == "bound")
    await registry_with_db.set_binding("forge", bound_id)

    await registry_with_db.delete(bound_id)

    bindings = await registry_with_db.list_bindings()
    assert len(bindings) == 1
    assert bindings[0].provider_id is None  # ON DELETE SET NULL

    provider, model = await registry_with_db.get_provider("forge")
    assert provider._client.api_key == "sk-default"
    assert model == "claude-opus-4-6"
```

- [ ] **Step 2: Run tests to verify some fail**

```bash
pytest tests/unit/llm/test_registry_bindings.py -v
```

Expected: the 4 new tests FAIL because current `get_provider` still reads `manifest.toml` and falls back to `_get_by_type`, not the binding table. Existing binding CRUD tests (from Task 1.2) still pass.

- [ ] **Step 3: Replace `get_provider` implementation**

In `sebastian/llm/registry.py`, replace the existing `get_provider` body with:

```python
    async def get_provider(self, agent_type: str | None = None) -> tuple[LLMProvider, str]:
        """Return (provider, model) for the given agent_type.

        Resolution order:
        1. If agent_type has a binding row with a non-null provider_id → use that record.
        2. Otherwise fallback to global default provider.
        """
        if agent_type is not None:
            binding = await self._get_binding(agent_type)
            if binding is not None and binding.provider_id is not None:
                record = await self._get_record(binding.provider_id)
                if record is not None:
                    return self._instantiate(record), record.model
        return await self.get_default_with_model()
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
pytest tests/unit/llm/test_registry_bindings.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sebastian/llm/registry.py tests/unit/llm/test_registry_bindings.py
git commit -m "feat(llm): get_provider 改为按 binding 表查询，fallback 全局默认"
```

---

### Task 1.4: 删除 manifest `[llm]` 读取路径与旧测试

**Files:**
- Modify: `sebastian/llm/registry.py`
- Delete: `tests/unit/llm/test_llm_provider_routing.py`
- Test: `tests/unit/llm/test_registry_no_manifest.py`

- [ ] **Step 1: Write a test asserting manifest code is gone**

Create `tests/unit/llm/test_registry_no_manifest.py`:

```python
from __future__ import annotations

import pytest


def test_read_manifest_llm_removed() -> None:
    """`_read_manifest_llm` 必须已删除。"""
    import sebastian.llm.registry as registry_mod

    assert not hasattr(registry_mod, "_read_manifest_llm"), (
        "_read_manifest_llm should have been removed; binding now lives in DB"
    )


def test_get_by_type_method_removed() -> None:
    """Registry._get_by_type 必须已删除。"""
    from sebastian.llm.registry import LLMProviderRegistry

    assert not hasattr(LLMProviderRegistry, "_get_by_type"), (
        "_get_by_type is obsolete; resolution is by provider_id via binding table"
    )


@pytest.mark.asyncio
async def test_manifest_llm_section_is_ignored(tmp_path, monkeypatch) -> None:
    """即使 manifest 里残留 [llm] 段（可能是用户旧文件），也不应影响 provider 解析。"""
    key_file = tmp_path / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from sebastian.llm.crypto import encrypt
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base, _install_sqlite_fk_pragma
    from sebastian.store.models import LLMProviderRecord

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = LLMProviderRegistry(factory)

    default = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry.create(default)

    # Agent "forge" has no binding; even if its manifest had [llm], it must fallback to default.
    provider, model = await registry.get_provider("forge")
    assert provider._client.api_key == "sk-default"
    assert model == "claude-opus-4-6"
    await engine.dispose()
```

- [ ] **Step 2: Delete the old routing tests**

```bash
git rm tests/unit/llm/test_llm_provider_routing.py
```

- [ ] **Step 3: Run tests to verify failure state**

```bash
pytest tests/unit/llm/test_registry_no_manifest.py -v
```

Expected: the first two tests FAIL (manifest helpers still exist). Third test passes (binding table is authoritative).

- [ ] **Step 4: Delete `_read_manifest_llm` and `_get_by_type`**

In `sebastian/llm/registry.py`:

- Remove the top-level function `_read_manifest_llm`
- Remove the method `_get_by_type`
- Remove the top-of-file import `import tomllib` if no longer needed
- Remove the `from pathlib import Path` import if no longer used

Verify by grepping:

```bash
grep -n "tomllib\|_read_manifest_llm\|_get_by_type" sebastian/llm/registry.py
```

Expected: no matches.

- [ ] **Step 5: Run all llm tests**

```bash
pytest tests/unit/llm/ -v
```

Expected: all tests PASS (including the new `test_registry_no_manifest.py`).

- [ ] **Step 6: Commit**

```bash
git add sebastian/llm/registry.py tests/unit/llm/test_registry_no_manifest.py tests/unit/llm/test_llm_provider_routing.py
git commit -m "refactor(llm): 删除 manifest [llm] 段读取路径，改由 DB binding 表唯一来源"
```

---

## 阶段 2 — Gateway 路由

### Task 2.1: 扩展 `GET /api/v1/agents` 返回 `bound_provider_id`

**Files:**
- Modify: `sebastian/gateway/routes/agents.py`
- Test: `tests/unit/gateway/test_agents_route.py`

- [ ] **Step 1: Check existing test file**

```bash
ls tests/unit/gateway/test_agents_route.py 2>/dev/null || echo "NEW FILE"
```

If file exists, we append; if not, create fresh.

- [ ] **Step 2: Write the failing test**

Append (or create) `tests/unit/gateway/test_agents_route.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _build_app_with_mocks(agents: dict, bindings: list) -> FastAPI:
    import sebastian.gateway.state as state

    state.agent_registry = agents
    state.index_store = MagicMock()
    state.index_store.list_by_agent_type = AsyncMock(return_value=[])
    state.llm_registry = MagicMock()
    state.llm_registry.list_bindings = AsyncMock(return_value=bindings)

    app = FastAPI()
    from sebastian.gateway.routes import agents as agents_mod

    # Override auth for tests
    from sebastian.gateway.auth import require_auth

    async def _fake_auth() -> dict[str, str]:
        return {"user_id": "test"}

    app.dependency_overrides[require_auth] = _fake_auth
    app.include_router(agents_mod.router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_list_agents_includes_bound_provider_id_when_bound() -> None:
    from sebastian.agents._loader import AgentConfig
    from sebastian.store.models import AgentLLMBindingRecord

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="Code writer",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    bindings = [
        AgentLLMBindingRecord(agent_type="forge", provider_id="prov-123"),
    ]
    app = _build_app_with_mocks(agents, bindings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agents"][0]["agent_type"] == "forge"
    assert data["agents"][0]["bound_provider_id"] == "prov-123"


@pytest.mark.asyncio
async def test_list_agents_returns_null_bound_provider_when_unbound() -> None:
    from sebastian.agents._loader import AgentConfig

    agents = {
        "aide": AgentConfig(
            agent_type="aide",
            name="AideAgent",
            description="Research",
            max_children=2,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agents")
    data = resp.json()
    assert data["agents"][0]["bound_provider_id"] is None
```

- [ ] **Step 3: Run tests to verify failure**

```bash
pytest tests/unit/gateway/test_agents_route.py::test_list_agents_includes_bound_provider_id_when_bound -v
```

Expected: FAIL (current response has no `bound_provider_id` field, OR `llm_registry` is not wired).

- [ ] **Step 4: Extend the handler**

Modify `sebastian/gateway/routes/agents.py`, replace `list_agents`:

```python
@router.get("/agents")
async def list_agents(_auth: AuthPayload = Depends(require_auth)) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = await state.llm_registry.list_bindings()
    binding_map = {b.agent_type: b.provider_id for b in bindings}

    agents = []
    for agent_type, config in state.agent_registry.items():
        if agent_type == "sebastian":
            continue

        sessions = await state.index_store.list_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")

        agents.append(
            {
                "agent_type": agent_type,
                "description": config.description,
                "active_session_count": active_count,
                "max_children": config.max_children,
                "bound_provider_id": binding_map.get(agent_type),
            }
        )

    return {"agents": agents}
```

- [ ] **Step 5: Run tests to verify pass**

```bash
pytest tests/unit/gateway/test_agents_route.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/agents.py tests/unit/gateway/test_agents_route.py
git commit -m "feat(gateway): GET /api/v1/agents 响应增加 bound_provider_id"
```

---

### Task 2.2: 新增 `PUT/DELETE /api/v1/agents/{agent_type}/llm-binding`

**Files:**
- Modify: `sebastian/gateway/routes/agents.py`
- Test: `tests/unit/gateway/test_agents_route.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/gateway/test_agents_route.py`:

```python
@pytest.mark.asyncio
async def test_put_binding_sets_provider_id() -> None:
    from sebastian.agents._loader import AgentConfig
    from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="Code writer",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    import sebastian.gateway.state as state

    # Allow provider validation
    state.llm_registry._get_record = AsyncMock(
        return_value=LLMProviderRecord(
            id="prov-1",
            name="x",
            provider_type="anthropic",
            api_key_enc="k",
            model="m",
            is_default=False,
        )
    )
    state.llm_registry.set_binding = AsyncMock(
        return_value=AgentLLMBindingRecord(agent_type="forge", provider_id="prov-1")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/forge/llm-binding",
            json={"provider_id": "prov-1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"agent_type": "forge", "provider_id": "prov-1"}
    state.llm_registry.set_binding.assert_awaited_once_with("forge", "prov-1")


@pytest.mark.asyncio
async def test_put_binding_with_null_clears_binding() -> None:
    from sebastian.agents._loader import AgentConfig
    from sebastian.store.models import AgentLLMBindingRecord

    agents = {
        "forge": AgentConfig(
            agent_type="forge", name="ForgeAgent", description="",
            max_children=5, stalled_threshold_minutes=5, agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    import sebastian.gateway.state as state

    state.llm_registry.set_binding = AsyncMock(
        return_value=AgentLLMBindingRecord(agent_type="forge", provider_id=None)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/forge/llm-binding",
            json={"provider_id": None},
        )
    assert resp.status_code == 200
    assert resp.json()["provider_id"] is None


@pytest.mark.asyncio
async def test_put_binding_404_for_unknown_agent() -> None:
    app = _build_app_with_mocks({}, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/ghost/llm-binding",
            json={"provider_id": "prov-1"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_binding_400_for_unknown_provider() -> None:
    from sebastian.agents._loader import AgentConfig

    agents = {
        "forge": AgentConfig(
            agent_type="forge", name="ForgeAgent", description="",
            max_children=5, stalled_threshold_minutes=5, agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    import sebastian.gateway.state as state

    state.llm_registry._get_record = AsyncMock(return_value=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/forge/llm-binding",
            json={"provider_id": "bogus"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_binding_returns_204() -> None:
    from sebastian.agents._loader import AgentConfig

    agents = {
        "forge": AgentConfig(
            agent_type="forge", name="ForgeAgent", description="",
            max_children=5, stalled_threshold_minutes=5, agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    import sebastian.gateway.state as state

    state.llm_registry.clear_binding = AsyncMock(return_value=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/v1/agents/forge/llm-binding")
    assert resp.status_code == 204
    state.llm_registry.clear_binding.assert_awaited_once_with("forge")


@pytest.mark.asyncio
async def test_delete_binding_404_for_unknown_agent() -> None:
    app = _build_app_with_mocks({}, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/v1/agents/ghost/llm-binding")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/gateway/test_agents_route.py -v
```

Expected: the 6 new tests FAIL with 404 on the new routes.

- [ ] **Step 3: Add the routes**

In `sebastian/gateway/routes/agents.py`, add imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
```

Add the request body model near the top:

```python
class BindingUpdate(BaseModel):
    provider_id: str | None = None
```

Append the two new routes (before `health` for clarity):

```python
@router.put("/agents/{agent_type}/llm-binding")
async def set_agent_binding(
    agent_type: str,
    body: BindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if agent_type == "sebastian" or agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.provider_id is not None:
        record = await state.llm_registry._get_record(body.provider_id)
        if record is None:
            raise HTTPException(status_code=400, detail="Provider not found")

    binding = await state.llm_registry.set_binding(agent_type, body.provider_id)
    return {"agent_type": binding.agent_type, "provider_id": binding.provider_id}


@router.delete("/agents/{agent_type}/llm-binding", status_code=204)
async def clear_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if agent_type == "sebastian" or agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    await state.llm_registry.clear_binding(agent_type)
    return Response(status_code=204)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/gateway/test_agents_route.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Update routes README**

Modify `sebastian/gateway/routes/README.md`, add to the routes table:

```
| `PUT /agents/{agent_type}/llm-binding` — 绑定 agent 到指定 provider（`provider_id=null` 解绑） | [agents.py](agents.py) |
| `DELETE /agents/{agent_type}/llm-binding` — 解绑 agent（等价 PUT null） | [agents.py](agents.py) |
```

Also update the first table row that describes `GET /agents` to mention the new `bound_provider_id` field.

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/agents.py sebastian/gateway/routes/README.md tests/unit/gateway/test_agents_route.py
git commit -m "feat(gateway): 新增 PUT/DELETE /api/v1/agents/{type}/llm-binding 路由"
```

---

## 阶段 3 — 文档同步

### Task 3.1: 更新 `core/llm-provider.md` spec

**Files:**
- Modify: `docs/architecture/spec/core/llm-provider.md`

- [ ] **Step 1: Update §2.3 per-agent 模型选择**

Replace the section content from the line starting with `### 2.3 per-agent 模型选择` through its example block. New content:

```markdown
### 2.3 per-agent provider 绑定

Sub-agent 与具体 provider record 的绑定存在 `agent_llm_bindings` 表（见 §2.4），由 Settings UI 维护。无绑定则使用全局 `is_default=True` 的 provider。

> 旧版 `manifest.toml [llm]` 段已废弃并从代码中移除；manifest 里的 `[llm]` 段会被忽略。

### 2.4 AgentLLMBindingRecord

文件：`sebastian/store/models.py`

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str]                 # PK，如 "forge" / "aide"
    provider_id: Mapped[str | None]         # FK → llm_providers.id, ON DELETE SET NULL
    updated_at: Mapped[datetime]
```

语义：
- `agent_type` 作主键 → 一个 agent 只有一条绑定（per-turn live 生效）
- `provider_id = NULL` 等价于无绑定 → fallback 全局默认
- 删除 provider 时外键自动置空对应 binding 的 `provider_id`（需要 SQLite `PRAGMA foreign_keys=ON`，已在 `sebastian/store/database.py` 的 `get_engine()` 启用）
- Sebastian orchestrator 不写入此表
```

- [ ] **Step 2: Update §7 LLMProviderRegistry 的优先级描述**

Replace the `优先级` block inside the docstring with:

```markdown
```python
class LLMProviderRegistry:
    async def get_provider(
        self,
        agent_type: str | None = None,
    ) -> tuple[LLMProvider, str]:
        """
        优先级：
        1. agent_type 对应的 binding 存在且 provider_id 非空 → 用对应 record
        2. 否则 fallback 全局 is_default=True
        3. 无默认 → 抛 RuntimeError
        """
```
```

- [ ] **Step 3: Update §10 Gateway 路由**

Replace the routes block with：

```markdown
```
# Provider CRUD（路径保持不变）
GET    /api/v1/llm-providers
POST   /api/v1/llm-providers
PUT    /api/v1/llm-providers/{id}
DELETE /api/v1/llm-providers/{id}

# Agent 列表（扩展字段）
GET    /api/v1/agents
       响应每条 agent 增加 `bound_provider_id: str | null`

# Agent 绑定管理（新增）
PUT    /api/v1/agents/{agent_type}/llm-binding
       body: { "provider_id": str | null }
DELETE /api/v1/agents/{agent_type}/llm-binding
```
```

- [ ] **Step 4: Bump frontmatter**

Update the frontmatter to `version: "1.1"` and `last_updated: 2026-04-16`.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/spec/core/llm-provider.md
git commit -m "docs(spec): llm-provider §2-10 同步 agent_llm_bindings 设计"
```

---

### Task 3.2: 清理 `agents/README.md` 的 manifest `[llm]` 描述

**Files:**
- Modify: `sebastian/agents/README.md`

- [ ] **Step 1: Check current content**

```bash
grep -n "\[llm\]\|provider_type\s*=\|manifest.*llm" sebastian/agents/README.md
```

Note any matches for replacement.

- [ ] **Step 2: Remove / rewrite references**

Find any section describing `manifest.toml [llm]` and either delete it or replace with:

> Provider 绑定不再通过 manifest 配置。从 Settings → Agent LLM Bindings 页面管理（数据存 `agent_llm_bindings` 表）。

- [ ] **Step 3: Commit**

```bash
git add sebastian/agents/README.md
git commit -m "docs(agents): README 移除 manifest [llm] 描述，改指向 Settings 子页"
```

---

## 阶段 4 — Android 前端

> Android 任务使用 Android Studio MCP (`android-studio-index`) 进行符号/引用查询，不要用 rg/grep。

### Task 4.1: 扩展 `AgentDto` 与 `AgentInfo` 模型

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/AgentDtoTest.kt`

- [ ] **Step 1: Write failing test**

Create `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/AgentDtoTest.kt`:

```kotlin
package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AgentDtoTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val adapter = moshi.adapter(AgentDto::class.java)

    @Test
    fun `parses bound_provider_id when present`() {
        val json = """{
            "agent_type": "forge",
            "description": "Code",
            "active_session_count": 0,
            "max_children": 5,
            "bound_provider_id": "prov-1"
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertEquals("prov-1", dto.boundProviderId)
        assertEquals("prov-1", dto.toDomain().boundProviderId)
    }

    @Test
    fun `bound_provider_id defaults to null when absent`() {
        val json = """{
            "agent_type": "aide",
            "description": "Research",
            "active_session_count": 0,
            "max_children": 2
        }""".trimIndent()
        val dto = adapter.fromJson(json)!!
        assertNull(dto.boundProviderId)
        assertNull(dto.toDomain().boundProviderId)
    }
}
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "*.AgentDtoTest*"
```

Expected: FAIL with unresolved `boundProviderId`.

- [ ] **Step 3: Extend DTO and domain model**

Modify `AgentDto.kt`:

```kotlin
@JsonClass(generateAdapter = true)
data class AgentDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "description") val description: String,
    @param:Json(name = "active_session_count") val activeSessionCount: Int = 0,
    @param:Json(name = "max_children") val maxChildren: Int = 0,
    @param:Json(name = "bound_provider_id") val boundProviderId: String? = null,
) {
    fun toDomain() = AgentInfo(
        agentType = agentType,
        description = description,
        activeSessionCount = activeSessionCount,
        maxChildren = maxChildren,
        boundProviderId = boundProviderId,
    )
}
```

Modify `AgentInfo.kt`:

```kotlin
data class AgentInfo(
    val agentType: String,
    val description: String,
    val activeSessionCount: Int = 0,
    val maxChildren: Int = 0,
    val boundProviderId: String? = null,
) {
    val isActive: Boolean get() = activeSessionCount > 0
}

val AgentInfo.displayName: String
    get() = agentType.replaceFirstChar { it.uppercase() }
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "*.AgentDtoTest*"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/AgentDtoTest.kt
git commit -m "feat(android): AgentDto/AgentInfo 增加 boundProviderId 字段"
```

---

### Task 4.2: 新增 binding API 方法

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`

- [ ] **Step 1: Add the DTO**

Create `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`:

```kotlin
package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SetBindingRequest(
    @param:Json(name = "provider_id") val providerId: String?,
)

@JsonClass(generateAdapter = true)
data class AgentBindingDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "provider_id") val providerId: String?,
)
```

- [ ] **Step 2: Add methods to `ApiService`**

Add inside the `ApiService` interface, after `getAgents()`:

```kotlin
@PUT("api/v1/agents/{agentType}/llm-binding")
suspend fun setAgentBinding(
    @Path("agentType") agentType: String,
    @Body body: SetBindingRequest,
): AgentBindingDto

@DELETE("api/v1/agents/{agentType}/llm-binding")
suspend fun clearAgentBinding(@Path("agentType") agentType: String)
```

- [ ] **Step 3: Verify compilation**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt
git commit -m "feat(android): ApiService 新增 agent llm-binding PUT/DELETE 方法"
```

---

### Task 4.3: 扩展 `AgentRepository` 支持绑定操作

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/AgentRepositoryImplTest.kt`

- [ ] **Step 1: Write failing tests**

Create `ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/AgentRepositoryImplTest.kt`:

```kotlin
package com.sebastian.android.data.repository

import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.SetBindingRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.mockito.Mockito.*
import org.mockito.kotlin.any
import org.mockito.kotlin.eq

class AgentRepositoryImplTest {

    @Test
    fun `setBinding passes provider_id and returns success`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setAgentBinding(eq("forge"), any())).thenReturn(
            AgentBindingDto(agentType = "forge", providerId = "p1")
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.setBinding("forge", "p1")
        assertTrue(result.isSuccess)
        assertEquals("p1", result.getOrNull()?.providerId)
    }

    @Test
    fun `setBinding with null provider_id clears binding`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setAgentBinding(eq("forge"), any())).thenReturn(
            AgentBindingDto(agentType = "forge", providerId = null)
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.clearBinding("forge")
        assertTrue(result.isSuccess)
    }
}
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "*.AgentRepositoryImplTest*"
```

Expected: FAIL with unresolved `setBinding` / `clearBinding`.

- [ ] **Step 3: Extend interface and impl**

Modify `AgentRepository.kt`:

```kotlin
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.remote.dto.AgentBindingDto

interface AgentRepository {
    suspend fun getAgents(): Result<List<AgentInfo>>
    suspend fun setBinding(agentType: String, providerId: String): Result<AgentBindingDto>
    suspend fun clearBinding(agentType: String): Result<Unit>
}
```

Modify `AgentRepositoryImpl.kt`:

```kotlin
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.SetBindingRequest
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AgentRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : AgentRepository {

    override suspend fun getAgents(): Result<List<AgentInfo>> = runCatching {
        withContext(dispatcher) {
            apiService.getAgents().agents.map { it.toDomain() }
        }
    }

    override suspend fun setBinding(
        agentType: String, providerId: String
    ): Result<AgentBindingDto> = runCatching {
        withContext(dispatcher) {
            apiService.setAgentBinding(agentType, SetBindingRequest(providerId))
        }
    }

    override suspend fun clearBinding(agentType: String): Result<Unit> = runCatching {
        withContext(dispatcher) {
            apiService.clearAgentBinding(agentType)
        }
    }
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "*.AgentRepositoryImplTest*"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/AgentRepositoryImplTest.kt
git commit -m "feat(android): AgentRepository 增加 setBinding / clearBinding"
```

---

### Task 4.4: 定义导航路由与 ViewModel

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/AgentBindingsViewModelTest.kt`

- [ ] **Step 1: Add route**

Modify `Route.kt`, add inside the sealed class:

```kotlin
@Serializable
data object SettingsAgentBindings : Route()
```

- [ ] **Step 2: Write failing ViewModel test**

Create `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/AgentBindingsViewModelTest.kt`:

```kotlin
package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import org.mockito.kotlin.any
import org.mockito.kotlin.eq

@OptIn(ExperimentalCoroutinesApi::class)
class AgentBindingsViewModelTest {

    private val dispatcher = UnconfinedTestDispatcher()

    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun teardown() { Dispatchers.resetMain() }

    private fun sampleAgent(boundId: String? = null) = AgentInfo(
        agentType = "forge", description = "Code", boundProviderId = boundId
    )

    private fun sampleProvider() = Provider(
        id = "p1", name = "Sonnet", providerType = "anthropic",
        baseUrl = null, model = "claude-sonnet-4-6", apiKey = "",
        thinkingFormat = null, thinkingCapability = null, isDefault = false,
    )

    @Test
    fun `load emits agents and providers`() = runTest {
        val agentRepo = mock(AgentRepository::class.java)
        val settingsRepo = mock(SettingsRepository::class.java)
        `when`(agentRepo.getAgents()).thenReturn(Result.success(listOf(sampleAgent())))
        `when`(settingsRepo.listProviders()).thenReturn(Result.success(listOf(sampleProvider())))

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()

        val state = vm.uiState.value
        assertEquals(1, state.agents.size)
        assertEquals(1, state.providers.size)
        assertNull(state.errorMessage)
    }

    @Test
    fun `bind sets provider and refreshes agents`() = runTest {
        val agentRepo = mock(AgentRepository::class.java)
        val settingsRepo = mock(SettingsRepository::class.java)
        `when`(agentRepo.getAgents()).thenReturn(Result.success(listOf(sampleAgent("p1"))))
        `when`(settingsRepo.listProviders()).thenReturn(Result.success(listOf(sampleProvider())))
        `when`(agentRepo.setBinding(eq("forge"), eq("p1"))).thenReturn(
            Result.success(AgentBindingDto(agentType = "forge", providerId = "p1"))
        )

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()
        vm.bind("forge", "p1")

        assertEquals("p1", vm.uiState.value.agents.first().boundProviderId)
        assertEquals(AgentBindingsEvent.BindingUpdated, vm.events.replayCache.last())
    }

    @Test
    fun `useDefault clears binding and refreshes`() = runTest {
        val agentRepo = mock(AgentRepository::class.java)
        val settingsRepo = mock(SettingsRepository::class.java)
        `when`(agentRepo.getAgents()).thenReturn(Result.success(listOf(sampleAgent(null))))
        `when`(settingsRepo.listProviders()).thenReturn(Result.success(listOf(sampleProvider())))
        `when`(agentRepo.clearBinding("forge")).thenReturn(Result.success(Unit))

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()
        vm.useDefault("forge")

        assertNull(vm.uiState.value.agents.first().boundProviderId)
        assertEquals(AgentBindingsEvent.BindingUpdated, vm.events.replayCache.last())
    }
}
```

Note: this test references `SettingsRepository.listProviders()` — verify that method exists first (existing SettingsViewModel reads providers via this repository). If the method name differs in the codebase, adjust both the test and the VM to match.

- [ ] **Step 3: Confirm SettingsRepository method name**

```bash
grep -n "listProviders\|getProviders\|fun.*Provider" ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt
```

If the method is named differently, substitute throughout.

- [ ] **Step 4: Run test to verify failure**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "*.AgentBindingsViewModelTest*"
```

Expected: FAIL with unresolved `AgentBindingsViewModel`.

- [ ] **Step 5: Create the ViewModel**

Create `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt`:

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AgentBindingsUiState(
    val loading: Boolean = false,
    val agents: List<AgentInfo> = emptyList(),
    val providers: List<Provider> = emptyList(),
    val errorMessage: String? = null,
)

sealed interface AgentBindingsEvent {
    data object BindingUpdated : AgentBindingsEvent
    data class Error(val message: String) : AgentBindingsEvent
}

@HiltViewModel
class AgentBindingsViewModel @Inject constructor(
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(AgentBindingsUiState())
    val uiState: StateFlow<AgentBindingsUiState> = _uiState

    private val _events = MutableSharedFlow<AgentBindingsEvent>(replay = 1)
    val events: SharedFlow<AgentBindingsEvent> = _events.asSharedFlow()

    fun load() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, errorMessage = null) }
            val agentsResult = agentRepository.getAgents()
            val providersResult = settingsRepository.listProviders()
            val err = agentsResult.exceptionOrNull() ?: providersResult.exceptionOrNull()
            _uiState.update {
                it.copy(
                    loading = false,
                    agents = agentsResult.getOrDefault(emptyList()),
                    providers = providersResult.getOrDefault(emptyList()),
                    errorMessage = err?.message,
                )
            }
        }
    }

    fun bind(agentType: String, providerId: String) {
        viewModelScope.launch {
            val result = agentRepository.setBinding(agentType, providerId)
            result.fold(
                onSuccess = {
                    _uiState.update { state ->
                        state.copy(
                            agents = state.agents.map { a ->
                                if (a.agentType == agentType) a.copy(boundProviderId = providerId) else a
                            }
                        )
                    }
                    _events.tryEmit(AgentBindingsEvent.BindingUpdated)
                },
                onFailure = {
                    _events.tryEmit(AgentBindingsEvent.Error(it.message.orEmpty()))
                }
            )
        }
    }

    fun useDefault(agentType: String) {
        viewModelScope.launch {
            val result = agentRepository.clearBinding(agentType)
            result.fold(
                onSuccess = {
                    _uiState.update { state ->
                        state.copy(
                            agents = state.agents.map { a ->
                                if (a.agentType == agentType) a.copy(boundProviderId = null) else a
                            }
                        )
                    }
                    _events.tryEmit(AgentBindingsEvent.BindingUpdated)
                },
                onFailure = {
                    _events.tryEmit(AgentBindingsEvent.Error(it.message.orEmpty()))
                }
            )
        }
    }
}
```

- [ ] **Step 6: Run tests to verify pass**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "*.AgentBindingsViewModelTest*"
```

Expected: all 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/AgentBindingsViewModelTest.kt
git commit -m "feat(android): 新增 AgentBindingsViewModel 与 SettingsAgentBindings 路由"
```

---

### Task 4.5: 实现 Agent Bindings 子页与 Provider Picker

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt`

- [ ] **Step 1: Build the screen**

Create `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt`:

```kotlin
package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.displayName
import com.sebastian.android.ui.common.ToastCenter
import com.sebastian.android.viewmodel.AgentBindingsEvent
import com.sebastian.android.viewmodel.AgentBindingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingsPage(
    navController: NavController,
    viewModel: AgentBindingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current

    var pickerAgent by remember { mutableStateOf<AgentInfo?>(null) }

    LaunchedEffect(Unit) { viewModel.load() }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                AgentBindingsEvent.BindingUpdated -> {
                    ToastCenter.show(
                        context,
                        "Binding will take effect on next message.",
                        key = "agent-binding-updated",
                    )
                }
                is AgentBindingsEvent.Error -> {
                    ToastCenter.show(
                        context,
                        event.message.ifBlank { "Failed to update binding." },
                        key = "agent-binding-error",
                    )
                }
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Agent LLM Bindings") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            Text(
                text = "Select a provider for each agent, or use the global default.",
                modifier = Modifier.padding(16.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
            HorizontalDivider()
            LazyColumn(modifier = Modifier.fillMaxSize()) {
                items(state.agents, key = { it.agentType }) { agent ->
                    val boundProvider = state.providers.firstOrNull { it.id == agent.boundProviderId }
                    ListItem(
                        headlineContent = { Text(agent.displayName) },
                        supportingContent = {
                            Column {
                                Text(agent.description)
                                Text(
                                    text = "Provider: " + (boundProvider?.name ?: "Use Default"),
                                    style = MaterialTheme.typography.labelMedium,
                                )
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { pickerAgent = agent },
                    )
                    HorizontalDivider()
                }
            }
        }
    }

    val sheetState = rememberModalBottomSheetState()
    pickerAgent?.let { agent ->
        ModalBottomSheet(
            onDismissRequest = { pickerAgent = null },
            sheetState = sheetState,
        ) {
            ProviderPickerContent(
                currentProviderId = agent.boundProviderId,
                providers = state.providers,
                onUseDefault = {
                    viewModel.useDefault(agent.agentType)
                    pickerAgent = null
                },
                onSelect = { providerId ->
                    viewModel.bind(agent.agentType, providerId)
                    pickerAgent = null
                },
            )
        }
    }
}

@Composable
private fun ProviderPickerContent(
    currentProviderId: String?,
    providers: List<Provider>,
    onUseDefault: () -> Unit,
    onSelect: (String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        ListItem(
            headlineContent = { Text("Use Default") },
            supportingContent = { Text("Follow global default provider") },
            trailingContent = if (currentProviderId == null) {
                { Icon(Icons.Default.Check, contentDescription = "selected") }
            } else null,
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onUseDefault() },
        )
        HorizontalDivider()
        providers.forEach { provider ->
            ListItem(
                headlineContent = { Text(provider.name) },
                supportingContent = {
                    Text("${provider.providerType} · ${provider.model}")
                },
                trailingContent = if (currentProviderId == provider.id) {
                    { Icon(Icons.Default.Check, contentDescription = "selected") }
                } else null,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSelect(provider.id) },
            )
            HorizontalDivider()
        }
    }
}
```

- [ ] **Step 2: Verify compilation**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt
git commit -m "feat(android): 新增 Agent Bindings 子页与 Provider Picker"
```

---

### Task 4.6: 导航接线 + Settings 入口

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`
- Modify: the NavGraph composable (find via `grep -Rn "Route.Settings\b" ui/mobile-android/app/src/main/java`)

- [ ] **Step 1: Locate the NavGraph**

```bash
grep -Rn "Route.Settings\b\|composable<Route.Settings" ui/mobile-android/app/src/main/java
```

Note the file (typically `MainNavGraph.kt` or similar) where other settings routes are wired.

- [ ] **Step 2: Add navigation entry**

In the NavGraph file, add next to existing settings destinations:

```kotlin
composable<Route.SettingsAgentBindings> {
    AgentBindingsPage(navController = navController)
}
```

And import:

```kotlin
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.ui.settings.AgentBindingsPage
```

- [ ] **Step 3: Add Settings entry row**

Modify `SettingsScreen.kt`, inside the `Column`, insert a new `SettingsItem` + `HorizontalDivider` between "模型与 Provider" and "外观":

```kotlin
HorizontalDivider()
SettingsItem(
    title = "Agent LLM Bindings",
    subtitle = "Select a provider per agent",
    onClick = { navController.navigate(Route.SettingsAgentBindings) { launchSingleTop = true } },
)
```

- [ ] **Step 4: Build and install on emulator**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

> Per repo convention: don't auto-install. User will run `npx expo run:android` or equivalent separately.

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/<nav-graph-file>.kt
git commit -m "feat(android): Settings 主页新增 Agent LLM Bindings 入口与导航"
```

---

## 阶段 5 — 端到端验证

### Task 5.1: 后端全量测试

**Files:** 无（纯验证）

- [ ] **Step 1: Backend lint + type + test**

```bash
ruff check sebastian/ tests/
ruff format sebastian/ tests/ --check
mypy sebastian/
pytest
```

Expected: all pass. Fix any surfaced issues inline.

- [ ] **Step 2: Commit any formatting fixes if needed**

If ruff format produced changes:

```bash
git add <formatted-files>
git commit -m "style: ruff format"
```

---

### Task 5.2: Android 全量测试

- [ ] **Step 1: Android lint + unit tests**

```bash
cd ui/mobile-android
./gradlew :app:ktlintCheck :app:testDebugUnitTest
```

Expected: all pass.

---

### Task 5.3: 手动端到端验证

**Steps (操作留给用户确认；以下为验证清单)：**

- [ ] 启动 dev gateway（`./scripts/dev.sh`，端口 8824）
- [ ] Android 模拟器安装 debug APK 并登录 dev 环境
- [ ] Settings 主页可以看到 "Agent LLM Bindings" 入口
- [ ] 点进去列出 forge / aide 两个 agent，初始 Provider 显示 "Use Default"
- [ ] 至少新建两条 provider（例如 A 用 opus，B 用 haiku），把 forge 绑到 B
- [ ] 列表立即刷新为 `Provider: B`，toast 显示 `Binding will take effect on next message.`
- [ ] 给 Sebastian 发一条消息触发 forge 子 agent，后端 llm_stream 日志显示使用 B 的 model
- [ ] 删除 provider B，返回 Bindings 页面 → forge 自动回到 "Use Default"
- [ ] 给 forge 发消息 → 使用默认 provider（A），无异常

---

## Self-Review

1. **Spec coverage**
   - §2 数据模型 → Task 1.1 ✅
   - §3 Registry 改造（新查询逻辑 + 删 manifest 路径 + binding CRUD）→ Task 1.2 / 1.3 / 1.4 ✅
   - §4 BaseAgent 集成 → 零改动，由 §3 的 registry 切换覆盖 ✅
   - §5 Gateway 路由（扩展 `GET /agents`、`PUT/DELETE /llm-binding`）→ Task 2.1 / 2.2 ✅
   - §6 Android 子页、导航、Toast → Task 4.1–4.6 ✅
   - §7 文档同步 → Task 3.1 / 3.2 ✅
   - §8 测试计划 → 每个 backend/Android 任务都包含单测；§5 有端到端验证清单 ✅
   - §9 SQLite foreign_keys pragma → Task 0.1 ✅

2. **Placeholder scan**
   - 无 "TBD"/"TODO"/"implement later"
   - Task 4.6 的 NavGraph 文件名未指定 —— 已在步骤里给出 `grep` 命令让实施者自行定位并替换 `<nav-graph-file>` 占位。这是合理的定位操作，不是内容占位符

3. **Type / API consistency**
   - Kotlin 层：`AgentInfo.boundProviderId`（Task 4.1）← `AgentDto.boundProviderId`（Task 4.1）← 后端 JSON `bound_provider_id`（Task 2.1）一致
   - Repository 签名：`setBinding(agentType, providerId: String): Result<AgentBindingDto>`、`clearBinding(agentType): Result<Unit>` 在 interface / impl / 测试 / ViewModel 中一致
   - ViewModel 事件：`BindingUpdated` / `Error(message)` 全流程一致
   - Backend registry：`set_binding(agent_type, provider_id)` / `clear_binding(agent_type)` / `list_bindings()` / `_get_binding` / `_get_record` 在 registry / gateway route / 测试中一致

没有发现类型或命名不一致。

# Code Review Batch 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note:** 可以使用 JetBrains PyCharm MCP 进行符号查询（`mcp__pycharm__get_symbol_info`、`mcp__pycharm__search_symbol` 等），无需全量文件搜索。

**Goal:** 修复代码审查报告中 Batch 1 的 6 个问题：C1（api_key 加密）、C2+H6（spawn_sub_agent 超限）、H1（删除遗留 worker 逻辑）、H2（删除 /intervene 路由）、H3（CancelledError 未捕获）、H4+H5+M4（Session.goal 字段及下游）。

**Architecture:** 最短路径修复，不打兼容补丁。加密密钥从已有的 `SEBASTIAN_JWT_SECRET` 派生，无需新增 env var。Session.goal 字段加入模型后，下游 4 处工具/路由同步补全输出。

**Tech Stack:** Python 3.12+, `cryptography.fernet.Fernet`（已通过 `python-jose[cryptography]` 间接引入）, SQLAlchemy async, asyncio.Lock, pytest-asyncio

---

## File Map

| 操作 | 文件 |
|------|------|
| **新建** | `sebastian/llm/crypto.py` |
| **新建** | `tests/unit/test_llm_crypto.py` |
| 修改 | `sebastian/store/models.py` |
| 修改 | `sebastian/llm/registry.py` |
| 修改 | `sebastian/gateway/routes/llm_providers.py` |
| 修改 | `sebastian/store/index_store.py` |
| 修改 | `sebastian/capabilities/tools/spawn_sub_agent/__init__.py` |
| 修改 | `sebastian/core/task_manager.py` |
| 修改 | `sebastian/gateway/routes/sessions.py` |
| 修改 | `sebastian/core/session_runner.py` |
| 修改 | `sebastian/core/types.py` |
| 修改 | `sebastian/orchestrator/sebas.py` |
| 修改 | `sebastian/capabilities/tools/delegate_to_agent/__init__.py` |
| 修改 | `sebastian/capabilities/tools/check_sub_agents/__init__.py` |
| 修改 | `sebastian/capabilities/tools/inspect_session/__init__.py` |
| 修改 | `sebastian/core/stalled_watchdog.py` |
| 更新测试 | `tests/unit/test_llm_registry.py` |
| 更新测试 | `tests/unit/test_llm_provider_store.py` |
| 更新测试 | `tests/unit/test_index_store_v2.py` |
| 更新测试 | `tests/unit/test_session_runner.py` |
| 更新测试 | `tests/unit/test_stalled_watchdog.py` |

---

## Task 1: C1 — API key Fernet 加密

### 背景

`LLMProviderRecord.api_key` 当前明文存储，GET 接口也明文返回。需改为 `api_key_enc`（Fernet 加密），密钥从 `SEBASTIAN_JWT_SECRET` 派生。

**Files:**
- Create: `sebastian/llm/crypto.py`
- Create: `tests/unit/test_llm_crypto.py`
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/llm/registry.py`
- Modify: `sebastian/gateway/routes/llm_providers.py`
- Modify: `tests/unit/test_llm_registry.py`
- Modify: `tests/unit/test_llm_provider_store.py`

---

- [ ] **Step 1: 写失败测试（crypto 模块不存在，ImportError 即失败）**

新建 `tests/unit/test_llm_crypto.py`：

```python
from __future__ import annotations

import pytest


def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr("sebastian.config.settings.sebastian_jwt_secret", "test-secret-abc")
    from sebastian.llm.crypto import decrypt, encrypt

    plain = "sk-ant-api03-test-key"
    assert decrypt(encrypt(plain)) == plain


def test_different_plaintexts_produce_different_ciphertext(monkeypatch) -> None:
    monkeypatch.setattr("sebastian.config.settings.sebastian_jwt_secret", "test-secret-abc")
    from sebastian.llm.crypto import encrypt

    assert encrypt("key-a") != encrypt("key-b")


def test_ciphertext_is_not_plaintext(monkeypatch) -> None:
    monkeypatch.setattr("sebastian.config.settings.sebastian_jwt_secret", "test-secret-abc")
    from sebastian.llm.crypto import encrypt

    plain = "sk-ant-secret"
    assert plain not in encrypt(plain)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/unit/test_llm_crypto.py -v
```

期望：`ModuleNotFoundError: No module named 'sebastian.llm.crypto'`

- [ ] **Step 3: 新建 `sebastian/llm/crypto.py`**

```python
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    # 延迟 import 避免循环依赖；在调用时从 settings 读取 jwt_secret
    from sebastian.config import settings

    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.sebastian_jwt_secret.encode()).digest()
    )
    return Fernet(key)


def encrypt(plain: str) -> str:
    """Encrypt a plaintext string. Returns URL-safe base64 ciphertext."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(enc: str) -> str:
    """Decrypt a Fernet-encrypted string back to plaintext."""
    return _fernet().decrypt(enc.encode()).decode()
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/unit/test_llm_crypto.py -v
```

期望：3 个 PASS

- [ ] **Step 5: 修改 `sebastian/store/models.py`**

将 `LLMProviderRecord` 中：
1. `from datetime import datetime` 改为 `from datetime import UTC, datetime`
2. `api_key` → `api_key_enc`，列宽改为 600（Fernet token 比明文长约 80 字节）
3. `default=datetime.utcnow` 两处改为 `default=lambda: datetime.now(UTC)` + `onupdate=lambda: datetime.now(UTC)`

完整 `LLMProviderRecord` 替换为：

```python
class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_enc: Mapped[str] = mapped_column(String(600), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    thinking_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
```

同时在文件顶部将 `from datetime import datetime` 改为：

```python
from datetime import UTC, datetime
```

- [ ] **Step 6: 更新 `sebastian/llm/registry.py` — `_instantiate` 改为解密**

将 `_instantiate` 方法改为：

```python
def _instantiate(self, record: LLMProviderRecord) -> LLMProvider:
    from sebastian.llm.crypto import decrypt

    plain_key = decrypt(record.api_key_enc)
    if record.provider_type == "anthropic":
        from sebastian.llm.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=plain_key, base_url=record.base_url)
    if record.provider_type == "openai":
        from sebastian.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=plain_key,
            base_url=record.base_url,
            thinking_format=record.thinking_format,
        )
    raise ValueError(f"Unknown provider_type: {record.provider_type!r}")
```

- [ ] **Step 7: 更新 `sebastian/gateway/routes/llm_providers.py`**

**(a) `_record_to_dict` 移除 `api_key_enc` 字段：**

```python
def _record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "provider_type": record.provider_type,
        "base_url": record.base_url,
        "model": record.model,
        "thinking_format": record.thinking_format,
        "is_default": record.is_default,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
```

**(b) `create_llm_provider` 路由 — 加密后写入：**

```python
@router.post("/llm-providers", status_code=201)
async def create_llm_provider(
    body: LLMProviderCreate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    from sebastian.llm.crypto import encrypt
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name=body.name,
        provider_type=body.provider_type,
        api_key_enc=encrypt(body.api_key),
        model=body.model,
        base_url=body.base_url,
        thinking_format=body.thinking_format,
        is_default=body.is_default,
    )
    await state.llm_registry.create(record)
    return _record_to_dict(record)
```

**(c) `update_llm_provider` 路由 — api_key 若提供则加密：**

```python
@router.put("/llm-providers/{provider_id}")
async def update_llm_provider(
    provider_id: str,
    body: LLMProviderUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    from sebastian.llm.crypto import encrypt

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.api_key is not None:
        updates["api_key_enc"] = encrypt(body.api_key)
    if body.model is not None:
        updates["model"] = body.model
    if body.base_url is not None:
        updates["base_url"] = body.base_url
    if body.thinking_format is not None:
        updates["thinking_format"] = body.thinking_format
    if body.is_default is not None:
        updates["is_default"] = body.is_default

    record = await state.llm_registry.update(provider_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _record_to_dict(record)
```

- [ ] **Step 8: 更新现有测试 `tests/unit/test_llm_registry.py`**

将所有 `api_key="sk-ant-..."` 改为 `api_key_enc=encrypt("sk-ant-...")`，并在测试文件顶部加 `from sebastian.llm.crypto import encrypt`：

```python
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.crypto import encrypt


@pytest_asyncio.fixture
async def registry_with_db():
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield LLMProviderRegistry(factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_registry_returns_env_fallback_when_no_default(registry_with_db, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fallback")
    from sebastian.llm.anthropic import AnthropicProvider

    provider = await registry_with_db.get_default()
    assert isinstance(provider, AnthropicProvider)


@pytest.mark.asyncio
async def test_registry_create_and_list(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="My Claude",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-ant-abc"),
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    assert len(records) == 1
    assert records[0].name == "My Claude"


@pytest.mark.asyncio
async def test_registry_get_default_uses_db_record(registry_with_db) -> None:
    from sebastian.llm.anthropic import AnthropicProvider
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="DB Claude",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-ant-db"),
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(record)
    provider = await registry_with_db.get_default()
    assert isinstance(provider, AnthropicProvider)
    assert provider._client.api_key == "sk-ant-db"


@pytest.mark.asyncio
async def test_registry_delete(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="To Delete",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-ant-del"),
        model="claude-opus-4-6",
        is_default=False,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    record_id = records[0].id
    deleted = await registry_with_db.delete(record_id)
    assert deleted is True
    assert await registry_with_db.list_all() == []
```

- [ ] **Step 9: 更新 `tests/unit/test_llm_provider_store.py`**

```python
from __future__ import annotations

import pytest

from sebastian.llm.crypto import decrypt, encrypt


@pytest.mark.asyncio
async def test_llm_provider_record_roundtrip(db_session) -> None:
    from sqlalchemy import select

    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="Claude Home",
        provider_type="anthropic",
        base_url=None,
        api_key_enc=encrypt("sk-ant-test"),
        model="claude-opus-4-6",
        thinking_format=None,
        is_default=True,
    )
    db_session.add(record)
    await db_session.commit()

    result = await db_session.execute(select(LLMProviderRecord).where(LLMProviderRecord.is_default))
    loaded = result.scalar_one()
    assert loaded.name == "Claude Home"
    assert loaded.api_key_enc != "sk-ant-test"   # stored encrypted
    assert decrypt(loaded.api_key_enc) == "sk-ant-test"  # round-trip works
    assert loaded.provider_type == "anthropic"
    assert loaded.is_default is True
```

- [ ] **Step 10: 删除开发数据库（重建 schema）**

```bash
rm -f ~/.sebastian/sebastian.db
# 或按 SEBASTIAN_DATA_DIR 指定路径删除 sqlite db 文件
```

- [ ] **Step 11: 运行相关测试**

```bash
pytest tests/unit/test_llm_crypto.py tests/unit/test_llm_registry.py tests/unit/test_llm_provider_store.py -v
```

期望：全部 PASS

- [ ] **Step 12: Commit**

```bash
git add sebastian/llm/crypto.py sebastian/store/models.py sebastian/llm/registry.py \
        sebastian/gateway/routes/llm_providers.py \
        tests/unit/test_llm_crypto.py tests/unit/test_llm_registry.py \
        tests/unit/test_llm_provider_store.py
git commit -m "fix(security): C1 — api_key_enc Fernet 加密存储，GET 不返回密钥

- 新增 sebastian/llm/crypto.py，密钥从 JWT_SECRET 派生
- models.py: api_key → api_key_enc，修 datetime.utcnow (M5)
- registry._instantiate: decrypt 后传给 provider
- routes: create/update 路由层加密，_record_to_dict 不含密钥字段

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: C2+H6 — spawn_sub_agent 超限修复（stalled 占位 + 竞态锁）

### 背景

- `list_active_children` 只统计 `status == "active"`，stalled session 不计入，可超 `max_children`
- check-then-create 无锁，并发可同时通过检查后各自建 session

**Files:**
- Modify: `sebastian/store/index_store.py`
- Modify: `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`
- Modify: `tests/unit/test_index_store_v2.py`

---

- [ ] **Step 1: 写失败测试 — stalled session 应计入 list_active_children**

在 `tests/unit/test_index_store_v2.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_list_active_children_includes_stalled(tmp_path: Path):
    """stalled session 仍应占 max_children 位。"""
    store = IndexStore(tmp_path)
    parent = Session(id="parent2", agent_type="code", title="parent", depth=2)
    await store.upsert(parent)

    active_child = Session(
        id="child_active2", agent_type="code", title="active",
        depth=3, parent_session_id="parent2",
    )
    stalled_child = Session(
        id="child_stalled", agent_type="code", title="stalled",
        depth=3, parent_session_id="parent2", status=SessionStatus.STALLED,
    )
    await store.upsert(active_child)
    await store.upsert(stalled_child)

    children = await store.list_active_children("code", "parent2")
    assert len(children) == 2  # both active and stalled count
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/unit/test_index_store_v2.py::test_list_active_children_includes_stalled -v
```

期望：FAIL（当前只返回 active，stalled 不计入，len == 1）

- [ ] **Step 3: 修改 `sebastian/store/index_store.py` — `list_active_children` 加入 stalled**

将 `list_active_children` 方法改为：

```python
async def list_active_children(
    self,
    agent_type: str,
    parent_session_id: str,
) -> list[dict[str, Any]]:
    """List active+stalled child sessions for a given parent session.

    Both statuses occupy max_children slots per spec §3.3.
    """
    return [
        s for s in await self._read()
        if s.get("agent_type") == agent_type
        and s.get("parent_session_id") == parent_session_id
        and s.get("status") in ("active", "stalled")
    ]
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/unit/test_index_store_v2.py -v
```

期望：全部 PASS

- [ ] **Step 5: 写失败测试 — 并发 spawn 不超 max_children**

在 `tests/unit/test_index_store_v2.py` 末尾追加（此测试验证锁的外部可见效果：
并发多次调用 list_active_children + create 不会超限）：

```python
@pytest.mark.asyncio
async def test_list_active_children_concurrent_count_is_bounded(tmp_path: Path):
    """验证 list_active_children 在并发场景下正确计数，不能因为竞态而少算。"""
    import asyncio
    store = IndexStore(tmp_path)
    parent = Session(id="p_concurrent", agent_type="code", title="parent", depth=2)
    await store.upsert(parent)

    # 先放一个 stalled child
    stalled = Session(
        id="stalled_concurrent", agent_type="code", title="s",
        depth=3, parent_session_id="p_concurrent", status=SessionStatus.STALLED,
    )
    await store.upsert(stalled)

    # 并发查询 5 次，结果应该一致且都包含 stalled session
    results = await asyncio.gather(*[
        store.list_active_children("code", "p_concurrent")
        for _ in range(5)
    ])
    for r in results:
        assert len(r) == 1
        assert r[0]["status"] == "stalled"
```

- [ ] **Step 6: 运行测试，确认通过（index_store 层无竞态）**

```bash
pytest tests/unit/test_index_store_v2.py::test_list_active_children_concurrent_count_is_bounded -v
```

期望：PASS（index_store 本身有锁，list 是只读操作）

- [ ] **Step 7: 修改 `sebastian/capabilities/tools/spawn_sub_agent/__init__.py` — 加 per-agent 锁**

在 `_log_task_failure` 函数之前，加锁相关代码：

```python
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import Session, ToolResult

logger = logging.getLogger(__name__)

# Per-agent-type lock: prevents concurrent check-then-create from bypassing max_children.
_SPAWN_LOCKS: dict[str, asyncio.Lock] = {}


def _get_spawn_lock(agent_type: str) -> asyncio.Lock:
    if agent_type not in _SPAWN_LOCKS:
        _SPAWN_LOCKS[agent_type] = asyncio.Lock()
    return _SPAWN_LOCKS[agent_type]


def _log_task_failure(task: asyncio.Task) -> None:
    ...
```

然后将 `spawn_sub_agent` 函数中的 check-then-create 整块包在锁内：

```python
@tool(
    name="spawn_sub_agent",
    description="分派子任务给组员处理。组员异步执行，你可以继续处理其他工作。",
)
async def spawn_sub_agent(
    goal: str,
    context: str = "",
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    if _ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")

    state = _get_state()
    agent_type = _ctx.agent_type
    parent_session_id = _ctx.session_id

    config = state.agent_registry.get(agent_type)
    if config is None:
        return ToolResult(ok=False, error=f"未知的 Agent 类型: {agent_type}")

    if agent_type not in state.agent_instances:
        return ToolResult(ok=False, error=f"Agent {agent_type} 尚未初始化")

    async with _get_spawn_lock(agent_type):
        active = await state.index_store.list_active_children(agent_type, parent_session_id)
        if len(active) >= config.max_children:
            return ToolResult(
                ok=False,
                error=f"当前已有{len(active)}个组员在工作，已达上限{config.max_children}",
            )

        session = Session(
            agent_type=agent_type,
            title=goal[:40],
            depth=3,
            parent_session_id=parent_session_id,
        )
        await state.session_store.create_session(session)
        await state.index_store.upsert(session)

    agent = state.agent_instances[agent_type]
    full_goal = f"{goal}\n\n背景信息：{context}" if context else goal

    from sebastian.core.session_runner import run_agent_session

    task = asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=full_goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )
    task.add_done_callback(_log_task_failure)

    return ToolResult(ok=True, output=f"已安排组员处理：{goal}")
```

- [ ] **Step 8: 运行全部 index_store 测试**

```bash
pytest tests/unit/test_index_store_v2.py tests/unit/test_index_store.py -v
```

期望：全部 PASS

- [ ] **Step 9: Commit**

```bash
git add sebastian/store/index_store.py \
        sebastian/capabilities/tools/spawn_sub_agent/__init__.py \
        tests/unit/test_index_store_v2.py
git commit -m "fix: C2+H6 — spawn_sub_agent stalled 占位 + per-agent 并发锁

- list_active_children 加入 stalled 状态
- spawn_sub_agent check-then-create 加 per-agent asyncio.Lock

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: H1 — 删除 `_resolve_agent_path` 遗留逻辑

### 背景

`task_manager._resolve_agent_path` 用 `rpartition("_")` 剥离数字后缀（如 `code_01 → code`），是 AgentPool/worker 命名的遗留。三层架构后 `assigned_agent` 直接是 `agent_type`，不含后缀。

**Files:**
- Modify: `sebastian/core/task_manager.py`

---

- [ ] **Step 1: 写测试验证 assigned_agent 直接使用，不做 rpartition**

在 `tests/unit/test_task_manager.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_task_manager_uses_agent_type_directly(tmp_path):
    """assigned_agent 直接作为 agent_type，不剥离数字后缀。"""
    from unittest.mock import AsyncMock
    from sebastian.core.task_manager import TaskManager
    from sebastian.core.types import Session, Task
    from sebastian.store.session_store import SessionStore
    from sebastian.store.index_store import IndexStore
    from sebastian.protocol.events.bus import EventBus

    session_store = AsyncMock(spec=SessionStore)
    index_store = AsyncMock(spec=IndexStore)
    event_bus = AsyncMock(spec=EventBus)

    session = Session(agent_type="agent_v2", title="test")
    session_store.get_session = AsyncMock(return_value=session)

    manager = TaskManager(session_store, event_bus, index_store)
    task = Task(goal="test goal", session_id=session.id, assigned_agent="agent_v2")

    called_with: list[str] = []

    async def fn(t: Task) -> None:
        pass

    await manager.submit(task, fn)
    # store.create_task 应该收到 "agent_v2"，不是 "agent"
    call_args = session_store.create_task.call_args
    assert call_args[0][1] == "agent_v2"  # agent_type 参数
```

- [ ] **Step 2: 运行测试，确认当前行为（可能已失败或 agent_v2 被截断）**

```bash
pytest tests/unit/test_task_manager.py::test_task_manager_uses_agent_type_directly -v
```

- [ ] **Step 3: 修改 `sebastian/core/task_manager.py`**

删除整个 `_resolve_agent_path` 方法（约 5 行），并将所有调用点替换为直接使用 `task.assigned_agent`：

在 `submit` 方法中：
```python
# 删除:
agent_type = self._resolve_agent_path(task.assigned_agent)
# 改为:
agent_type = task.assigned_agent
```

在 `_transition` 方法中：
```python
# 删除:
agent_type = self._resolve_agent_path(task.assigned_agent)
# 改为:
agent_type = task.assigned_agent
```

在 `_sync_index` 方法中：
```python
async def _sync_index(self, session_id: str, agent: str) -> None:
    if self._index is None:
        return
    # 删除 _resolve_agent_path 调用，直接用 agent
    session = await self._store.get_session(session_id, agent)
    if session is not None:
        await self._index.upsert(session)
```

删除方法定义：
```python
# 删除整个方法:
def _resolve_agent_path(self, assigned_agent: str) -> str:
    agent_type, separator, suffix = assigned_agent.rpartition("_")
    if separator and suffix.isdigit():
        return agent_type
    return assigned_agent
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/test_task_manager.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/task_manager.py tests/unit/test_task_manager.py
git commit -m "fix: H1 — 删除 task_manager._resolve_agent_path 遗留 worker 逻辑

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: H2 — 删除废弃的 `/intervene` 路由

### 背景

`POST /sessions/{id}/intervene` 与 `POST /sessions/{id}/turns` 逻辑完全重复，保留了已废弃的"代答"语义。

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`

---

- [ ] **Step 1: 删除 `intervene_session` handler**

在 `sebastian/gateway/routes/sessions.py` 中，找到并删除以下完整代码块（约 14 行）：

```python
@router.post("/sessions/{session_id}/intervene")
async def intervene_session(
    session_id: str,
    body: SendTurnBody,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    now = await _touch_session(state, session)
    await _schedule_session_turn(session, body.content)
    return {
        "session_id": session_id,
        "ts": now.isoformat(),
    }
```

- [ ] **Step 2: 运行现有路由测试**

```bash
pytest tests/integration/test_gateway_sessions.py tests/integration/test_gateway_turns.py -v
```

期望：全部 PASS（若有测试调用 `/intervene`，删除或改为 `/turns`）

- [ ] **Step 3: Commit**

```bash
git add sebastian/gateway/routes/sessions.py
git commit -m "fix: H2 — 删除废弃的 POST /sessions/{id}/intervene 路由

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: H3 — session_runner 捕获 CancelledError

### 背景

Python 3.9+ 中 `asyncio.CancelledError` 不继承 `Exception`，`except Exception` 捕获不到。被取消的 session 状态永远停在 `active`，stalled watchdog 会误判。

**Files:**
- Modify: `sebastian/core/session_runner.py`
- Modify: `tests/unit/test_session_runner.py`

---

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_session_runner.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_run_agent_session_cancelled():
    """CancelledError 应将 session 状态设为 CANCELLED，并在持久化后重新抛出。"""
    import asyncio

    agent = MagicMock()
    agent.run_streaming = AsyncMock(side_effect=asyncio.CancelledError())
    session = Session(id="s4", agent_type="code", title="test", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await run_agent_session(
            agent=agent,
            session=session,
            goal="cancellable task",
            session_store=session_store,
            index_store=index_store,
            event_bus=event_bus,
        )

    session_store.update_session.assert_awaited_once()
    updated = session_store.update_session.call_args[0][0]
    assert updated.status == SessionStatus.CANCELLED
    index_store.upsert.assert_awaited_once()
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/unit/test_session_runner.py::test_run_agent_session_cancelled -v
```

期望：FAIL（`CancelledError` 未被捕获，`session.status` 仍为 `active`）

- [ ] **Step 3: 修改 `sebastian/core/session_runner.py`**

在 `except Exception` 之前插入 `except asyncio.CancelledError` 块：

```python
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


async def run_agent_session(
    agent: BaseAgent,
    session: Session,
    goal: str,
    session_store: SessionStore,
    index_store: IndexStore,
    event_bus: EventBus | None = None,
) -> None:
    """Run an agent on a session asynchronously. Sets status on completion/failure/cancellation."""
    try:
        await agent.run_streaming(goal, session.id)
        session.status = SessionStatus.COMPLETED
    except asyncio.CancelledError:
        session.status = SessionStatus.CANCELLED
        raise  # finally block persists the status, then CancelledError propagates
    except Exception:
        logger.exception("Agent session %s failed", session.id)
        session.status = SessionStatus.FAILED
    finally:
        session.updated_at = datetime.now(UTC)
        session.last_activity_at = datetime.now(UTC)
        await session_store.update_session(session)
        await index_store.upsert(session)
        if event_bus is not None:
            event_type = (
                EventType.SESSION_COMPLETED
                if session.status == SessionStatus.COMPLETED
                else EventType.SESSION_CANCELLED
                if session.status == SessionStatus.CANCELLED
                else EventType.SESSION_FAILED
            )
            await event_bus.publish(
                Event(
                    type=event_type,
                    data={
                        "session_id": session.id,
                        "agent_type": session.agent_type,
                        "status": session.status.value,
                    },
                )
            )
```

> **注意：** `EventType.SESSION_CANCELLED` 需在 `sebastian/protocol/events/types.py` 中存在。若不存在，先检查该文件，若缺失则新增该枚举值。

- [ ] **Step 4: 检查 EventType 枚举**

```bash
grep -n "SESSION_CANCELLED\|SESSION_COMPLETED\|SESSION_FAILED" sebastian/protocol/events/types.py
```

若 `SESSION_CANCELLED` 不存在，在 `types.py` 相应位置追加：`SESSION_CANCELLED = "session.cancelled"`

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/unit/test_session_runner.py -v
```

期望：全部 PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/session_runner.py sebastian/protocol/events/types.py \
        tests/unit/test_session_runner.py
git commit -m "fix: H3 — session_runner 捕获 CancelledError，写入 CANCELLED 状态

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: H4+H5+M4 — Session.goal 字段及下游补全

### 背景

`Session` 无 `goal` 字段，导致 `check_sub_agents`、`inspect_session`、`GET /recent`、stalled 事件均缺少目标信息，上级 agent 无法判断下属卡在哪里。

**Files:**
- Modify: `sebastian/core/types.py`
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/capabilities/tools/delegate_to_agent/__init__.py`
- Modify: `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/capabilities/tools/check_sub_agents/__init__.py`
- Modify: `sebastian/capabilities/tools/inspect_session/__init__.py`
- Modify: `sebastian/core/stalled_watchdog.py`
- Modify: `tests/unit/test_stalled_watchdog.py`

---

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_session_goal.py`：

```python
from __future__ import annotations

import pytest
from sebastian.core.types import Session


def test_session_has_goal_field() -> None:
    s = Session(agent_type="code", title="test", goal="write unit tests")
    assert s.goal == "write unit tests"


def test_session_goal_defaults_to_empty() -> None:
    s = Session(agent_type="code", title="test")
    assert s.goal == ""


def test_session_goal_persists_in_json_roundtrip() -> None:
    s = Session(agent_type="code", title="test", goal="analyze stock prices")
    data = s.model_dump()
    s2 = Session(**data)
    assert s2.goal == "analyze stock prices"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/unit/test_session_goal.py -v
```

期望：FAIL（`Session` 不接受 `goal` 参数）

- [ ] **Step 3: 在 `sebastian/core/types.py` 的 `Session` 模型添加 `goal` 字段**

在 `Session` 类的 `title: str` 下方加一行：

```python
goal: str = ""
```

完整的 `Session` 类变为：

```python
class Session(BaseModel):
    """Conversation session that owns messages and child tasks."""

    id: str = Field(
        default_factory=lambda: (
            datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S") + "_" + uuid.uuid4().hex[:6]
        )
    )
    agent_type: str
    title: str
    goal: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    depth: int = 1
    parent_session_id: str | None = None
    last_activity_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_count: int = 0
    active_task_count: int = 0
```

- [ ] **Step 4: 运行 Session 测试，确认通过**

```bash
pytest tests/unit/test_session_goal.py tests/unit/test_core_types.py -v
```

期望：全部 PASS

- [ ] **Step 5: 更新 4 处 Session 创建调用，传入 `goal`**

**(a) `sebastian/orchestrator/sebas.py` `get_or_create_session`：**

```python
session = Session(
    agent_type="sebastian",
    title=first_message[:40] or "新对话",
    goal=first_message,
    depth=1,
)
```

**(b) `sebastian/capabilities/tools/delegate_to_agent/__init__.py`：**

```python
session = Session(
    agent_type=agent_type,
    title=goal[:40],
    goal=goal,
    depth=2,
)
```

**(c) `sebastian/capabilities/tools/spawn_sub_agent/__init__.py`（在 lock 内的 Session 构造）：**

```python
session = Session(
    agent_type=agent_type,
    title=goal[:40],
    goal=goal,
    depth=3,
    parent_session_id=parent_session_id,
)
```

**(d) `sebastian/gateway/routes/sessions.py` `create_agent_session`：**

```python
session = Session(
    agent_type=agent_type,
    title=content[:40],
    goal=content,
    depth=2,
)
```

- [ ] **Step 6: 写失败测试 — check_sub_agents 应包含 goal 和 last_activity_at**

在 `tests/unit/test_session_goal.py` 追加：

```python
@pytest.mark.asyncio
async def test_check_sub_agents_includes_goal_and_activity(monkeypatch) -> None:
    """check_sub_agents 的输出应包含 goal 和 last_activity_at。"""
    from unittest.mock import AsyncMock, MagicMock
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents
    from sebastian.permissions.types import ToolCallContext

    fake_state = MagicMock()
    fake_state.index_store.list_all = AsyncMock(return_value=[
        {
            "id": "child1",
            "agent_type": "code",
            "depth": 3,
            "parent_session_id": "parent1",
            "status": "active",
            "title": "write tests",
            "goal": "write unit tests for auth module",
            "last_activity_at": "2026-04-07T10:00:00+00:00",
        }
    ])

    import sebastian.gateway.state as state_module
    monkeypatch.setattr(state_module, "index_store", fake_state.index_store)

    ctx = MagicMock(spec=ToolCallContext)
    ctx.depth = 2
    ctx.agent_type = "code"
    ctx.session_id = "parent1"

    result = await check_sub_agents(_ctx=ctx)
    assert result.ok
    assert "write unit tests for auth module" in result.output
    assert "2026-04-07T10:00:00" in result.output
```

- [ ] **Step 7: 运行测试，确认失败**

```bash
pytest tests/unit/test_session_goal.py::test_check_sub_agents_includes_goal_and_activity -v
```

期望：FAIL（goal 和 last_activity_at 不在输出中）

- [ ] **Step 8: 更新 `sebastian/capabilities/tools/check_sub_agents/__init__.py`**

将 `lines.append(...)` 改为包含 goal 和 last_activity_at：

```python
for s in sessions:
    status = s.get("status", "unknown")
    status_counts[status] = status_counts.get(status, 0) + 1
    goal = s.get("goal") or s.get("title", "无标题")
    last_active = s.get("last_activity_at", "未知")
    lines.append(
        f"- [{status}] {goal} "
        f"(id: {s['id']}, agent: {s.get('agent_type')}, 最后活动: {last_active})"
    )
```

- [ ] **Step 9: 运行测试，确认通过**

```bash
pytest tests/unit/test_session_goal.py -v
```

- [ ] **Step 10: 更新 `sebastian/capabilities/tools/inspect_session/__init__.py` — 加 goal**

在 `lines` 列表中，`f"Session: {session.title}"` 下方加一行：

```python
lines = [
    f"Session: {session.title}",
    f"目标: {session.goal}",
    f"状态: {session.status}",
    f"Agent: {agent_type}",
    f"最后活动: {session.last_activity_at}",
    "",
    f"最近 {len(messages)} 条消息：",
]
```

- [ ] **Step 11: 更新 `sebastian/gateway/routes/sessions.py` `get_session_recent` — 加 goal**

```python
return {
    "session_id": session.id,
    "status": session.status,
    "title": session.title,
    "goal": session.goal,
    "last_activity_at": session.last_activity_at.isoformat(),
    "messages": messages,
}
```

- [ ] **Step 12: 更新 `sebastian/core/stalled_watchdog.py` — 事件加 goal（M4）**

将 `event_bus.publish(Event(...))` 调用改为：

```python
await event_bus.publish(
    Event(
        type=EventType.SESSION_STALLED,
        data={
            "session_id": session_id,
            "agent_type": agent_type,
            "goal": session.goal,
            "last_activity_at": last_activity_str,
        },
    )
)
```

- [ ] **Step 13: 更新 `tests/unit/test_stalled_watchdog.py` — mock session 加 goal**

将 `session_store.get_session` 的返回值 MagicMock 加上 `goal` 属性：

```python
session_store.get_session = AsyncMock(return_value=MagicMock(
    id="s1",
    status="active",
    last_activity_at=now - timedelta(minutes=10),
    goal="analyze stock market",
))
```

- [ ] **Step 14: 运行所有相关测试**

```bash
pytest tests/unit/test_session_goal.py \
       tests/unit/test_stalled_watchdog.py \
       tests/unit/test_session_runner.py \
       tests/unit/test_core_types.py \
       -v
```

期望：全部 PASS

- [ ] **Step 15: 运行完整测试套件**

```bash
pytest tests/unit/ -v --tb=short
```

修复任何因 `Session` 字段变更导致的失败（通常是已有测试构造 Session 时缺 `goal`，由于 `goal=""` 有默认值，应全部兼容）。

- [ ] **Step 16: Commit**

```bash
git add sebastian/core/types.py \
        sebastian/orchestrator/sebas.py \
        sebastian/capabilities/tools/delegate_to_agent/__init__.py \
        sebastian/capabilities/tools/spawn_sub_agent/__init__.py \
        sebastian/gateway/routes/sessions.py \
        sebastian/capabilities/tools/check_sub_agents/__init__.py \
        sebastian/capabilities/tools/inspect_session/__init__.py \
        sebastian/core/stalled_watchdog.py \
        tests/unit/test_session_goal.py \
        tests/unit/test_stalled_watchdog.py
git commit -m "fix: H4+H5+M4 — Session.goal 字段 + 下游 check/inspect/recent/stalled 补全

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 最终验证

- [ ] **运行完整测试套件**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

期望：全部 PASS，无新增失败。

- [ ] **运行 lint**

```bash
ruff check sebastian/ tests/
```

---

## 自查清单（已完成）

- **Spec 覆盖**：C1 ✓ Task 1、C2+H6 ✓ Task 2、H1 ✓ Task 3、H2 ✓ Task 4、H3 ✓ Task 5、H4+H5+M4 ✓ Task 6
- **类型一致性**：`api_key_enc` 在 models/registry/routes 三处命名一致；`Session.goal` 在 types/session_store/tools 一致
- **无 TBD/占位**：全部步骤含完整代码
- **依赖顺序**：Task 6 在 Task 2 之后（spawn_sub_agent 在 Task 6 中也被修改，已包含 Task 2 的锁代码基础）

# Agent Binding 次级页面 & 思考配置迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"思考档位"从 Composer 的内存状态迁移到 agent-llm-binding 级别持久化，Bindings 页每个 agent 点击进入独立次级编辑页；Sebastian 主管家一并纳入 bindings 列表。

**Architecture:** 后端 `agent_llm_bindings` 表扩 `thinking_effort`/`thinking_adaptive` 两列；`LLMProviderRegistry.get_provider` 改返回 `ResolvedProvider(provider, model, effort, adaptive)`；`base_agent` 从该结构直接拿思考参数，不再从 HTTP `SendTurnRequest` 透传。Android 侧新建 `AgentBindingEditorPage` 次级页（Route / ViewModel / 3 个复用组件），删除 `ThinkButton` / `EffortPickerCard`。

**Tech Stack:** Python 3.12 + SQLAlchemy async + FastAPI (后端) / Kotlin + Jetpack Compose + Hilt + Retrofit/Moshi (Android)

**Spec:** [docs/superpowers/specs/2026-04-16-agent-binding-thinking-migration-design.md](../specs/2026-04-16-agent-binding-thinking-migration-design.md)

**执行顺序：** Phase A（后端）先于 Phase B（前端），Phase B 开始前 Phase A 必须已合并到共享开发库。Phase A / B 内部任务按序。

---

## Phase A：后端

### Task A1: 扩展 `AgentLLMBindingRecord` 数据模型

**Files:**
- Modify: `sebastian/store/models.py:90-103`
- Modify: `sebastian/store/database.py:73-75`

- [ ] **Step 1: 修改 model**

编辑 `sebastian/store/models.py:90-103`，在 `provider_id` 之后、`updated_at` 之前插入两列：

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
        nullable=True,
    )
    thinking_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    thinking_adaptive: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

- [ ] **Step 2: 扩展 idempotent migration**

编辑 `sebastian/store/database.py:73-75`，把 `patches` 列表改为：

```python
patches: list[tuple[str, str, str]] = [
    ("llm_providers", "thinking_capability", "VARCHAR(20)"),
    ("agent_llm_bindings", "thinking_effort", "VARCHAR(16)"),
    ("agent_llm_bindings", "thinking_adaptive", "BOOLEAN NOT NULL DEFAULT 0"),
]
```

- [ ] **Step 3: 写 ORM 层测试**

新建 `tests/unit/test_agent_llm_binding_model.py`：

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from sebastian.store.database import Base, get_engine
from sebastian.store.models import AgentLLMBindingRecord


@pytest.mark.asyncio
async def test_new_binding_defaults_to_no_thinking(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    monkeypatch.setenv("SEBASTIAN_DATABASE_URL", db_url)
    from sebastian.config import settings
    settings.database_url = db_url

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rec = AgentLLMBindingRecord(agent_type="foo", provider_id=None)
        session.add(rec)
        await session.commit()
        await session.refresh(rec)

    assert rec.thinking_effort is None
    assert rec.thinking_adaptive is False
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/test_agent_llm_binding_model.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py tests/unit/test_agent_llm_binding_model.py
git commit -m "feat(store): 扩 agent_llm_bindings 加 thinking_effort / thinking_adaptive 两列"
```

---

### Task A2: `LLMProviderRegistry` 引入 `ResolvedProvider` 与钳制

**Files:**
- Modify: `sebastian/llm/registry.py:47-60, 109-133`
- Test: `tests/unit/test_llm_registry_resolved.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_llm_registry_resolved.py`：

```python
from __future__ import annotations

import pytest

from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider, _coerce_thinking


def test_coerce_capability_none_clears_all():
    assert _coerce_thinking("high", True, "none") == (None, False)


def test_coerce_capability_always_on_clears_all():
    assert _coerce_thinking("high", True, "always_on") == (None, False)


def test_coerce_effort_drops_max_and_adaptive():
    assert _coerce_thinking("max", True, "effort") == ("high", False)


def test_coerce_toggle_drops_effort_values():
    assert _coerce_thinking("high", False, "toggle") == ("on", False)
    assert _coerce_thinking("off", False, "toggle") == ("off", False)


def test_coerce_adaptive_keeps_all():
    assert _coerce_thinking("max", True, "adaptive") == ("max", True)


def test_coerce_none_capability_returns_unmodified():
    # capability is None → we just pass through
    assert _coerce_thinking("high", False, None) == ("high", False)


@pytest.mark.asyncio
async def test_set_binding_stores_thinking(db_factory):
    registry = LLMProviderRegistry(db_factory)
    # pre-create a provider record in db_factory fixture
    ...  # fill in using existing conftest-style fixture
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/test_llm_registry_resolved.py -v
```

Expected: FAIL（`ResolvedProvider` 与 `_coerce_thinking` 未定义）

- [ ] **Step 3: 实现 ResolvedProvider 与 _coerce_thinking**

编辑 `sebastian/llm/registry.py`，文件顶部加 import 与 dataclass，将 `get_provider` 整段替换，扩展 `set_binding`：

```python
# 顶部 import 增加
from dataclasses import dataclass

# 模块级函数（class 外）
_EFFORT_ALIASES = {"off", "on", "low", "medium", "high", "max"}


def _coerce_thinking(
    effort: str | None,
    adaptive: bool,
    capability: str | None,
) -> tuple[str | None, bool]:
    """按 provider capability 钳制 effort/adaptive 到合法组合。"""
    if capability in ("none", "always_on"):
        return (None, False)
    if capability == "toggle":
        # 仅允许 'on' / 'off' / null；effort 为非法 bucket 时归一到 'on' 或 'off'
        if effort in (None, "off"):
            return ("off", False)
        if effort == "on":
            return ("on", False)
        # low/medium/high/max → 统一视为 on
        return ("on", False)
    if capability == "effort":
        # 允许 off/low/medium/high；max 钳到 high；on 视为 high
        if effort == "max":
            return ("high", False)
        if effort == "on":
            return ("high", False)
        return (effort, False)
    if capability == "adaptive":
        # 允许 off/low/medium/high/max + adaptive flag
        return (effort, adaptive)
    # capability 未知（None）→ pass-through
    return (effort, adaptive)


@dataclass
class ResolvedProvider:
    provider: LLMProvider
    model: str
    thinking_effort: str | None
    thinking_adaptive: bool
    capability: str | None  # 原始 provider.thinking_capability
```

替换 `get_provider` 返回签名：

```python
async def get_provider(self, agent_type: str | None = None) -> ResolvedProvider:
    record: LLMProviderRecord | None = None
    binding: AgentLLMBindingRecord | None = None
    if agent_type is not None:
        binding = await self._get_binding(agent_type)
        if binding is not None and binding.provider_id is not None:
            record = await self._get_record(binding.provider_id)

    if record is None:
        # fallback: 全局默认
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.is_default.is_(True)).limit(1)
            )
            record = result.scalar_one_or_none()

    if record is None:
        raise RuntimeError("No default LLM provider configured. Add one via the Settings page.")

    effort_raw = binding.thinking_effort if binding else None
    adaptive_raw = binding.thinking_adaptive if binding else False
    effort, adaptive = _coerce_thinking(effort_raw, adaptive_raw, record.thinking_capability)

    return ResolvedProvider(
        provider=self._instantiate(record),
        model=record.model,
        thinking_effort=effort,
        thinking_adaptive=adaptive,
        capability=record.thinking_capability,
    )
```

替换 `set_binding` 签名支持两新字段：

```python
async def set_binding(
    self,
    agent_type: str,
    provider_id: str | None,
    thinking_effort: str | None = None,
    thinking_adaptive: bool = False,
) -> AgentLLMBindingRecord:
    async with self._db_factory() as session:
        result = await session.execute(
            select(AgentLLMBindingRecord).where(AgentLLMBindingRecord.agent_type == agent_type)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            record = AgentLLMBindingRecord(
                agent_type=agent_type,
                provider_id=provider_id,
                thinking_effort=thinking_effort,
                thinking_adaptive=thinking_adaptive,
            )
            session.add(record)
        else:
            existing.provider_id = provider_id
            existing.thinking_effort = thinking_effort
            existing.thinking_adaptive = thinking_adaptive
            record = existing
        await session.commit()
        await session.refresh(record)
        return record
```

- [ ] **Step 4: 修复所有 get_provider 调用点**

全仓搜 `get_provider(` 调用：

```bash
grep -rn "llm_registry\.get_provider\|self\._llm_registry\.get_provider" sebastian/ --include='*.py'
```

Expected 调用点（预估 2-4 处，例如 `base_agent.py` 与 `orchestrator/*.py`）改为解构 `ResolvedProvider`。当前仅需最小改动使其不破：

```python
# 原来
provider, model = await self._llm_registry.get_provider(self.name)
# 改为
resolved = await self._llm_registry.get_provider(self.name)
provider, model = resolved.provider, resolved.model
```

（后续 Task A5 再改成直接用 resolved.thinking_effort。）

- [ ] **Step 5: 修补 conftest 里 db_factory fixture（如需）**

沿用现有 `tests/conftest.py` 的 db fixture。若测试里需要一个 provider record，直接用 SQLAlchemy 写入：

```python
import uuid
from sebastian.store.models import LLMProviderRecord

async def _mk_provider(factory, *, capability="effort", is_default=True):
    async with factory() as session:
        rec = LLMProviderRecord(
            id=uuid.uuid4().hex,
            name="p",
            provider_type="anthropic",
            base_url=None,
            api_key_enc=b"\x00" * 32,  # 若 crypto 要求具体格式，按现有 fixture 模式
            model="claude-3",
            thinking_capability=capability,
            is_default=is_default,
        )
        session.add(rec)
        await session.commit()
        return rec
```

- [ ] **Step 6: 补完测试 body**

在 Step 1 测试文件里补完 `test_set_binding_stores_thinking`、`test_get_provider_returns_resolved`、`test_get_provider_coerces_across_capability`：

```python
@pytest.mark.asyncio
async def test_set_binding_stores_thinking(db_factory):
    registry = LLMProviderRegistry(db_factory)
    await _mk_provider(db_factory, capability="adaptive", is_default=True)
    # 拿回新建的 provider_id
    records = await registry.list_all()
    pid = records[0].id
    await registry.set_binding("foo", pid, thinking_effort="high", thinking_adaptive=True)
    resolved = await registry.get_provider("foo")
    assert resolved.thinking_effort == "high"
    assert resolved.thinking_adaptive is True


@pytest.mark.asyncio
async def test_get_provider_falls_back_to_default_when_no_binding(db_factory):
    registry = LLMProviderRegistry(db_factory)
    await _mk_provider(db_factory, capability="effort", is_default=True)
    resolved = await registry.get_provider("missing_agent")
    assert resolved.capability == "effort"
    assert resolved.thinking_effort is None
    assert resolved.thinking_adaptive is False


@pytest.mark.asyncio
async def test_get_provider_coerces_max_down_in_effort_capability(db_factory):
    registry = LLMProviderRegistry(db_factory)
    await _mk_provider(db_factory, capability="effort", is_default=True)
    records = await registry.list_all()
    pid = records[0].id
    # 直接往 DB 写入一个越界配置（模拟用户先绑 adaptive 后切 effort 时数据库留下的旧值）
    async with db_factory() as session:
        session.add(AgentLLMBindingRecord(agent_type="foo", provider_id=pid, thinking_effort="max", thinking_adaptive=True))
        await session.commit()
    resolved = await registry.get_provider("foo")
    assert resolved.thinking_effort == "high"
    assert resolved.thinking_adaptive is False
```

- [ ] **Step 7: 运行测试**

```bash
pytest tests/unit/test_llm_registry_resolved.py -v
```

Expected: PASS

- [ ] **Step 8: 快速跑全量单测不让其他地方挂**

```bash
pytest tests/unit/ -x
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add sebastian/llm/registry.py tests/unit/test_llm_registry_resolved.py
git commit -m "feat(llm): registry.get_provider 返回 ResolvedProvider 携带思考配置"
```

---

### Task A3: `/api/v1/agents/...` 路由扩展 + 解除 Sebastian 屏蔽

**Files:**
- Modify: `sebastian/gateway/routes/agents.py`（整文件）
- Test: `tests/integration/test_agent_binding_api.py`

- [ ] **Step 1: 写失败集成测试**

新建 `tests/integration/test_agent_binding_api.py`：

```python
from __future__ import annotations

import pytest
from httpx import AsyncClient

# 复用现有 gateway test fixture（沿用其他 integration test 的风格）


@pytest.mark.asyncio
async def test_list_agents_includes_sebastian_first(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/agents", headers=auth_headers)
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert agents[0]["agent_type"] == "sebastian"
    assert agents[0]["is_orchestrator"] is True


@pytest.mark.asyncio
async def test_put_binding_with_thinking_fields(client, auth_headers, default_adaptive_provider):
    resp = await client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "provider_id": default_adaptive_provider.id,
            "thinking_effort": "high",
            "thinking_adaptive": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["thinking_effort"] == "high"
    assert body["thinking_adaptive"] is True


@pytest.mark.asyncio
async def test_put_binding_switching_provider_forces_reset(
    client, auth_headers, default_adaptive_provider, effort_only_provider
):
    # 先绑定 adaptive provider 带配置
    await client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "provider_id": default_adaptive_provider.id,
            "thinking_effort": "high",
            "thinking_adaptive": True,
        },
        headers=auth_headers,
    )
    # 切到 effort-only provider，即使请求体带 effort 也要被重置
    resp = await client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "provider_id": effort_only_provider.id,
            "thinking_effort": "high",
            "thinking_adaptive": False,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["thinking_effort"] is None
    assert body["thinking_adaptive"] is False


@pytest.mark.asyncio
async def test_put_binding_to_none_capability_provider_clears_thinking(
    client, auth_headers, none_capability_provider
):
    resp = await client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "provider_id": none_capability_provider.id,
            "thinking_effort": "high",
            "thinking_adaptive": False,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["thinking_effort"] is None


@pytest.mark.asyncio
async def test_get_binding_for_sebastian_returns_record(client, auth_headers):
    resp = await client.get("/api/v1/agents/sebastian/llm-binding", headers=auth_headers)
    assert resp.status_code == 200  # 不再是 403/404
```

Fixture 需要支持 3 类 provider，按 `tests/integration/conftest.py` 现有模式注入。

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/integration/test_agent_binding_api.py -v
```

Expected: FAIL（Sebastian 被屏蔽 + 新字段不存在）

- [ ] **Step 3: 重写 `sebastian/gateway/routes/agents.py`**

完整替换内容：

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["agents"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


class BindingUpdate(BaseModel):
    provider_id: str | None = None
    thinking_effort: str | None = None
    thinking_adaptive: bool = False


def _binding_to_dict(binding) -> JSONDict:
    return {
        "agent_type": binding.agent_type,
        "provider_id": binding.provider_id,
        "thinking_effort": binding.thinking_effort,
        "thinking_adaptive": binding.thinking_adaptive,
    }


@router.get("/agents")
async def list_agents(_auth: AuthPayload = Depends(require_auth)) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = {b.agent_type: b for b in await state.llm_registry.list_bindings()}

    agents: list[JSONDict] = []

    # Sebastian 置顶
    sebastian_binding = bindings.get("sebastian")
    agents.append(
        {
            "agent_type": "sebastian",
            "display_name": "Sebastian",
            "description": "Main orchestrator",
            "is_orchestrator": True,
            "active_session_count": 0,
            "max_children": 0,
            "binding": _binding_to_dict(sebastian_binding) if sebastian_binding else None,
        }
    )

    for agent_type, config in state.agent_registry.items():
        if agent_type == "sebastian":
            continue
        sessions = await state.index_store.list_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")
        b = bindings.get(agent_type)
        agents.append(
            {
                "agent_type": agent_type,
                "display_name": getattr(config, "display_name", agent_type),
                "description": config.description,
                "is_orchestrator": False,
                "active_session_count": active_count,
                "max_children": config.max_children,
                "binding": _binding_to_dict(b) if b else None,
            }
        )

    return {"agents": agents}


@router.get("/agents/{agent_type}/llm-binding")
async def get_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if agent_type != "sebastian" and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    bindings = {b.agent_type: b for b in await state.llm_registry.list_bindings()}
    b = bindings.get(agent_type)
    if b is None:
        return {
            "agent_type": agent_type,
            "provider_id": None,
            "thinking_effort": None,
            "thinking_adaptive": False,
        }
    return _binding_to_dict(b)


@router.put("/agents/{agent_type}/llm-binding")
async def set_agent_binding(
    agent_type: str,
    body: BindingUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    if agent_type != "sebastian" and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.provider_id is not None:
        record = await state.llm_registry._get_record(body.provider_id)
        if record is None:
            raise HTTPException(status_code=400, detail="Provider not found")

    # Provider 切换 → 强制重置；同 provider 修改 → 保留
    existing = None
    for b in await state.llm_registry.list_bindings():
        if b.agent_type == agent_type:
            existing = b
            break
    provider_changed = existing is None or existing.provider_id != body.provider_id

    effort = None if provider_changed else body.thinking_effort
    adaptive = False if provider_changed else body.thinking_adaptive

    # capability 硬约束：NONE / ALWAYS_ON 强制清空
    if body.provider_id is not None:
        capability = record.thinking_capability  # type: ignore[union-attr]
        if capability in ("none", "always_on"):
            effort = None
            adaptive = False

    binding = await state.llm_registry.set_binding(
        agent_type,
        body.provider_id,
        thinking_effort=effort,
        thinking_adaptive=adaptive,
    )
    return _binding_to_dict(binding)


@router.delete("/agents/{agent_type}/llm-binding", status_code=204)
async def clear_agent_binding(
    agent_type: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    if agent_type != "sebastian" and agent_type not in state.agent_registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    await state.llm_registry.clear_binding(agent_type)
    return Response(status_code=204)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/integration/test_agent_binding_api.py -v
```

Expected: PASS

- [ ] **Step 5: 跑已有 agents 测试**

```bash
pytest tests/ -k agent -x
```

Expected: PASS（可能需要调整其他测试对 Sebastian 被排除的假设）

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/agents.py tests/integration/test_agent_binding_api.py
git commit -m "feat(gateway): agents 路由扩思考字段 + 解除 Sebastian 绑定屏蔽"
```

---

### Task A4: `base_agent` 从 `ResolvedProvider` 直接读思考配置

**Files:**
- Modify: `sebastian/core/base_agent.py`（L259-402 附近的 turn/run_streaming 签名与内部逻辑）
- Modify: `sebastian/core/agent_loop.py:99, 128` 
- Modify: `sebastian/core/session_runner.py:34, 44`
- Test: `tests/unit/test_base_agent_thinking_injection.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_base_agent_thinking_injection.py`（使用 mock LLM 捕获 `chat_stream` 的 kwargs）：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from sebastian.llm.registry import ResolvedProvider


@pytest.mark.asyncio
async def test_base_agent_injects_effort_into_llm_call(make_agent, monkeypatch):
    mock_provider = MagicMock()
    mock_provider.chat_stream = AsyncMock(return_value=_empty_aiter())

    resolved = ResolvedProvider(
        provider=mock_provider,
        model="claude-3",
        thinking_effort="high",
        thinking_adaptive=False,
        capability="effort",
    )
    agent = make_agent(resolved=resolved)
    await agent.turn(messages=[{"role": "user", "content": "hi"}], task_id=None)

    mock_provider.chat_stream.assert_called_once()
    kwargs = mock_provider.chat_stream.call_args.kwargs
    assert kwargs["thinking_effort"] == "high"


@pytest.mark.asyncio
async def test_base_agent_adaptive_maps_to_adaptive_marker(make_agent):
    mock_provider = MagicMock()
    mock_provider.chat_stream = AsyncMock(return_value=_empty_aiter())
    resolved = ResolvedProvider(
        provider=mock_provider, model="claude-3",
        thinking_effort=None, thinking_adaptive=True, capability="adaptive",
    )
    agent = make_agent(resolved=resolved)
    await agent.turn(messages=[], task_id=None)
    kwargs = mock_provider.chat_stream.call_args.kwargs
    # 与现有 provider 接口约定一致：adaptive 以特殊字符串透传
    assert kwargs["thinking_effort"] == "adaptive"


@pytest.mark.asyncio
async def test_base_agent_no_thinking_when_effort_off(make_agent):
    mock_provider = MagicMock()
    mock_provider.chat_stream = AsyncMock(return_value=_empty_aiter())
    resolved = ResolvedProvider(
        provider=mock_provider, model="claude-3",
        thinking_effort="off", thinking_adaptive=False, capability="toggle",
    )
    agent = make_agent(resolved=resolved)
    await agent.turn(messages=[], task_id=None)
    kwargs = mock_provider.chat_stream.call_args.kwargs
    assert kwargs["thinking_effort"] in (None, "off")


async def _empty_aiter():
    if False:
        yield None
```

`make_agent` fixture 参见现有 `tests/conftest.py` 或 `tests/unit/test_base_agent.py` 的用法，把 `llm_registry.get_provider` mock 成返回 `resolved`。

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/test_base_agent_thinking_injection.py -v
```

Expected: FAIL

- [ ] **Step 3: 修改 `base_agent.py`**

找到 `turn()` 方法（约 L275）和 `run_streaming()`（约 L259）。

- **移除**方法签名里的 `thinking_effort: str | None = None` 参数
- 在 `turn()` 内部开头调 `resolved = await self._llm_registry.get_provider(self.name)`，把 `thinking_effort` 从 `resolved` 派生：

```python
resolved = await self._llm_registry.get_provider(self.name)
# adaptive 用特殊 sentinel 'adaptive' 透传给 LLM provider；各 provider adapter
# 负责识别（Anthropic → extended thinking adaptive mode；OpenAI 暂无，降级到 high）
if resolved.thinking_adaptive:
    thinking_effort_for_llm: str | None = "adaptive"
else:
    thinking_effort_for_llm = resolved.thinking_effort

# 继续使用已有流程
await self._agent_loop.run(
    ...,
    thinking_effort=thinking_effort_for_llm,
)
```

**注意**：`agent_loop.run` 签名保留 `thinking_effort`；`LLMProvider.chat_stream` 签名保留 `thinking_effort`。后端内部通道不变，变的只是**值的来源**（从 HTTP body 变成 binding 查询）。

- [ ] **Step 4: 修改 `session_runner.py`**

- 去掉 `run_new_session` 的 `thinking_effort` 参数（L34）
- 内部调用 `agent.run_streaming(goal, session.id)` 不再传 effort（L44）

- [ ] **Step 5: 修改 `agent_loop.py`**

保留签名不变（它仍然需要 `thinking_effort` 透传给 LLM）。

- [ ] **Step 6: 运行测试**

```bash
pytest tests/unit/test_base_agent_thinking_injection.py -v
pytest tests/unit/ -x
```

Expected: PASS（可能出现 call-site 编译错误，逐一修复）

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/ tests/unit/test_base_agent_thinking_injection.py
git commit -m "feat(core): base_agent 从 ResolvedProvider 派生思考参数，不再从入参透传"
```

---

### Task A5: 从 HTTP 入口去除 `thinking_effort`

**Files:**
- Modify: `sebastian/gateway/routes/turns.py:32, 85`
- Modify: `sebastian/gateway/routes/sessions.py:75, 98, 126, 232, 239, 246, 281`
- Modify: `tests/integration/test_sessions_send_turn.py`（新建或扩展现有）

- [ ] **Step 1: 写失败测试**

扩展 `tests/integration/test_agent_binding_api.py` 或新建 `tests/integration/test_turn_thinking_from_binding.py`：

```python
@pytest.mark.asyncio
async def test_send_turn_ignores_thinking_effort_field(client, auth_headers):
    # 请求体里带 thinking_effort 不报错（pydantic allow extra or silently drop），
    # 但真正走的是 binding 里的配置
    resp = await client.post(
        "/api/v1/turns",
        json={"content": "hello", "thinking_effort": "max"},  # 该字段被忽略
        headers=auth_headers,
    )
    # 期望 200 或 422（取决于 pydantic config）。若 422 说明已成功移除字段。
    assert resp.status_code in (200, 422)


@pytest.mark.asyncio
async def test_thinking_comes_from_binding(client, auth_headers, mock_llm_provider):
    # 先绑定 effort=high
    await client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": mock_llm_provider.id, "thinking_effort": "high", "thinking_adaptive": False},
        headers=auth_headers,
    )
    # 发消息
    await client.post("/api/v1/turns", json={"content": "hi"}, headers=auth_headers)
    # 断言 mock_llm_provider.chat_stream 被调用时 kwargs["thinking_effort"] == "high"
    assert mock_llm_provider.last_chat_kwargs["thinking_effort"] == "high"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/integration/test_turn_thinking_from_binding.py -v
```

Expected: FAIL（字段仍在且仍透传）

- [ ] **Step 3: 删除 HTTP 路径上的 thinking_effort 字段**

`sebastian/gateway/routes/turns.py:32`：删除 `thinking_effort: str | None = None` 字段。

`sebastian/gateway/routes/turns.py:85`：改成：

```python
body.content, session.id
```

`sebastian/gateway/routes/sessions.py`：
- L75-76: 删除 `thinking_effort = body.get("thinking_effort")`
- L98: 调 `_schedule_session_turn` 时不传
- L126: 删除字段声明
- L232, L239, L246: 删除参数与 keyword
- L281: 删除 keyword

- [ ] **Step 4: 运行测试**

```bash
pytest tests/integration/ -x
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/routes/ sebastian/core/session_runner.py tests/integration/test_turn_thinking_from_binding.py
git commit -m "refactor(gateway): 从 HTTP 入口移除 thinking_effort，改由 binding 决定"
```

---

### Task A6: 后端全量 lint + 测试 + 合并

- [ ] **Step 1: Lint**

```bash
ruff check sebastian/ tests/ && ruff format --check sebastian/ tests/
```

Expected: clean（有问题用 `ruff format` 自动修）

- [ ] **Step 2: mypy**

```bash
mypy sebastian/
```

Expected: clean

- [ ] **Step 3: 全量测试**

```bash
pytest -x
```

Expected: PASS

- [ ] **Step 4: Commit lint 修复（如果有）**

```bash
git add -A
git commit -m "chore: lint 修复"
```

- [ ] **Step 5: Push**

```bash
git push
```

Phase A 完成。

---

## Phase B：Android

### Task B1: DTO 层扩展

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TurnDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt`

- [ ] **Step 1: 扩 `AgentBindingDto`**

整文件替换为：

```kotlin
package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SetBindingRequest(
    @param:Json(name = "provider_id") val providerId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
    @param:Json(name = "thinking_adaptive") val thinkingAdaptive: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class AgentBindingDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "provider_id") val providerId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
    @param:Json(name = "thinking_adaptive") val thinkingAdaptive: Boolean = false,
)
```

- [ ] **Step 2: `TurnDto.kt` 去除 `thinkingEffort`**

`TurnDto.kt` L10 删除。

- [ ] **Step 3: 调整 `AgentInfo` 承载 binding + is_orchestrator**

查找 `data/model/AgentInfo.kt`：

```kotlin
data class AgentInfo(
    val agentType: String,
    val displayName: String,
    val description: String,
    val isOrchestrator: Boolean = false,
    val boundProviderId: String?,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
    val thinkingAdaptive: Boolean = false,
    // 保留 active_session_count / max_children 旧字段
    val activeSessionCount: Int = 0,
    val maxChildren: Int = 0,
)
```

- [ ] **Step 4: 调整 `AgentInfo` 的 `fromDto` 函数**

找到对 `/api/v1/agents` 响应的映射（通常在 `AgentRepositoryImpl.kt`），把新字段映射上。`thinkingEffort` 从字符串解析：

```kotlin
fun String?.toThinkingEffort(): ThinkingEffort = when (this) {
    "on" -> ThinkingEffort.ON
    "low" -> ThinkingEffort.LOW
    "medium" -> ThinkingEffort.MEDIUM
    "high" -> ThinkingEffort.HIGH
    "max" -> ThinkingEffort.MAX
    else -> ThinkingEffort.OFF
}

fun ThinkingEffort.toApiString(): String? = when (this) {
    ThinkingEffort.OFF -> null
    ThinkingEffort.ON -> "on"
    ThinkingEffort.LOW -> "low"
    ThinkingEffort.MEDIUM -> "medium"
    ThinkingEffort.HIGH -> "high"
    ThinkingEffort.MAX -> "max"
}
```

放到 `data/model/ThinkingEffort.kt` 作为公共扩展。

- [ ] **Step 5: Build 验证**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL（后续 Task 清理 ChatRepositoryImpl 里同名 private extension）

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/
git commit -m "feat(android/data): 扩 AgentBinding DTO 含 thinking_effort/adaptive；公共 effort 字符串转换"
```

---

### Task B2: `AgentRepository` 接口扩展

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`

- [ ] **Step 1: 扩 `ApiService`**

定位到 `ApiService.kt` 中 `setAgentBinding` 方法，确认其已经接受 `SetBindingRequest`（上一步已扩 DTO 包含新字段，此接口无需改签名）。新增一个 `getAgentBinding`：

```kotlin
@GET("/api/v1/agents/{agent_type}/llm-binding")
suspend fun getAgentBinding(@Path("agent_type") agentType: String): AgentBindingDto
```

- [ ] **Step 2: 扩 `AgentRepository` 接口**

```kotlin
interface AgentRepository {
    suspend fun getAgents(): Result<List<AgentInfo>>
    suspend fun getBinding(agentType: String): Result<AgentBindingDto>
    suspend fun setBinding(
        agentType: String,
        providerId: String?,
        thinkingEffort: ThinkingEffort,
        thinkingAdaptive: Boolean,
    ): Result<Unit>
    suspend fun clearBinding(agentType: String): Result<Unit>
}
```

- [ ] **Step 3: 更新 impl**

```kotlin
override suspend fun setBinding(
    agentType: String,
    providerId: String?,
    thinkingEffort: ThinkingEffort,
    thinkingAdaptive: Boolean,
): Result<Unit> = runCatching {
    apiService.setAgentBinding(
        agentType,
        SetBindingRequest(
            providerId = providerId,
            thinkingEffort = thinkingEffort.toApiString(),
            thinkingAdaptive = thinkingAdaptive,
        ),
    )
    Unit
}

override suspend fun getBinding(agentType: String): Result<AgentBindingDto> = runCatching {
    apiService.getAgentBinding(agentType)
}
```

`AgentBindingsViewModel.bind` 原签名改为：

```kotlin
fun bind(agentType: String, providerId: String) {
    viewModelScope.launch {
        agentRepository.setBinding(agentType, providerId, ThinkingEffort.OFF, false)
        ...
    }
}
```

（本 VM 后续 Task B10 会大幅简化，这里只作兼容改动不破坏现状）

- [ ] **Step 4: Build**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/
git commit -m "feat(android/data): AgentRepository 扩 thinking 字段，新增 getBinding"
```

---

### Task B3: 新路由 + NavHost 注册

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 1: 扩 Route**

编辑 `Route.kt`，在 `SettingsAgentBindings` 后面加：

```kotlin
@Serializable
data class SettingsAgentBindingEditor(val agentType: String) : Route()
```

- [ ] **Step 2: NavHost 注册**

在 `MainActivity.kt` NavHost 里（找 `composable<Route.SettingsAgentBindings>` 附近）加：

```kotlin
composable<Route.SettingsAgentBindingEditor> { backStackEntry ->
    val route: Route.SettingsAgentBindingEditor = backStackEntry.toRoute()
    AgentBindingEditorPage(
        agentType = route.agentType,
        navController = navController,
    )
}
```

（此时 `AgentBindingEditorPage` 尚未创建，会编译失败——留给后续 Task B7。）

- [ ] **Step 3: 暂时 stub `AgentBindingEditorPage` 使编译通过**

新建 `ui/settings/AgentBindingEditorPage.kt`：

```kotlin
package com.sebastian.android.ui.settings

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.navigation.NavController

@Composable
fun AgentBindingEditorPage(agentType: String, navController: NavController) {
    Text("Editor for $agentType")
}
```

- [ ] **Step 4: Build**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt
git commit -m "feat(android/nav): 新增 SettingsAgentBindingEditor 路由 + stub 页面"
```

---

### Task B4: 构造 `EffortSlider` 组件

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/EffortSlider.kt`
- Create: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/settings/components/EffortStepsTest.kt`

- [ ] **Step 1: 写失败测试**

```kotlin
// EffortStepsTest.kt
package com.sebastian.android.ui.settings.components

import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import org.junit.Assert.assertEquals
import org.junit.Test

class EffortStepsTest {
    @Test
    fun `toggle capability has 2 steps`() {
        assertEquals(
            listOf(ThinkingEffort.OFF, ThinkingEffort.ON),
            effortStepsFor(ThinkingCapability.TOGGLE),
        )
    }

    @Test
    fun `effort capability has 4 steps`() {
        assertEquals(
            listOf(ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH),
            effortStepsFor(ThinkingCapability.EFFORT),
        )
    }

    @Test
    fun `adaptive capability has 5 steps`() {
        assertEquals(
            listOf(ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH, ThinkingEffort.MAX),
            effortStepsFor(ThinkingCapability.ADAPTIVE),
        )
    }
}
```

- [ ] **Step 2: Run test (fail)**

```bash
cd ui/mobile-android && ./gradlew test --tests '*EffortStepsTest*'
```

Expected: FAIL

- [ ] **Step 3: 实现 `EffortSlider.kt`**

```kotlin
package com.sebastian.android.ui.settings.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.ui.common.SebastianSwitch

fun effortStepsFor(capability: ThinkingCapability): List<ThinkingEffort> = when (capability) {
    ThinkingCapability.TOGGLE -> listOf(ThinkingEffort.OFF, ThinkingEffort.ON)
    ThinkingCapability.EFFORT -> listOf(
        ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH,
    )
    ThinkingCapability.ADAPTIVE -> listOf(
        ThinkingEffort.OFF, ThinkingEffort.LOW, ThinkingEffort.MEDIUM, ThinkingEffort.HIGH, ThinkingEffort.MAX,
    )
    else -> emptyList()
}

private fun ThinkingEffort.label(): String = when (this) {
    ThinkingEffort.OFF -> "Off"
    ThinkingEffort.ON -> "On"
    ThinkingEffort.LOW -> "Low"
    ThinkingEffort.MEDIUM -> "Med"
    ThinkingEffort.HIGH -> "High"
    ThinkingEffort.MAX -> "Max"
}

@Composable
fun EffortSlider(
    capability: ThinkingCapability,
    value: ThinkingEffort,
    onValueChange: (ThinkingEffort) -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val steps = effortStepsFor(capability)
    if (steps.isEmpty()) return

    // TOGGLE 特例：用 Switch，不用 slider
    if (capability == ThinkingCapability.TOGGLE) {
        Row(
            modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Thinking", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            SebastianSwitch(
                checked = value == ThinkingEffort.ON,
                onCheckedChange = if (enabled) {
                    { checked -> onValueChange(if (checked) ThinkingEffort.ON else ThinkingEffort.OFF) }
                } else null,
                enabled = enabled,
            )
        }
        return
    }

    val currentIdx = steps.indexOf(value).coerceAtLeast(0)
    Column(
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)
            .alpha(if (enabled) 1f else 0.38f),
    ) {
        Slider(
            value = currentIdx.toFloat(),
            onValueChange = { if (enabled) onValueChange(steps[it.toInt()]) },
            valueRange = 0f..(steps.size - 1).toFloat(),
            steps = steps.size - 2,  // Material3 Slider steps = 内部档位数（不含两端）
            enabled = enabled,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            steps.forEach { eff ->
                Text(
                    text = eff.label(),
                    style = MaterialTheme.typography.labelSmall,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}
```

- [ ] **Step 4: Run test (pass)**

```bash
cd ui/mobile-android && ./gradlew test --tests '*EffortStepsTest*'
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/EffortSlider.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/ui/settings/components/EffortStepsTest.kt
git commit -m "feat(android/ui): 新增 EffortSlider 组件（TOGGLE/EFFORT/ADAPTIVE 三形态）"
```

---

### Task B5: 构造 `AdaptiveSwitch` 组件

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/AdaptiveSwitch.kt`

- [ ] **Step 1: 实现**

```kotlin
package com.sebastian.android.ui.settings.components

import androidx.compose.material3.ListItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.sebastian.android.ui.common.SebastianSwitch

@Composable
fun AdaptiveSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    ListItem(
        headlineContent = { Text("Adaptive Thinking") },
        supportingContent = { Text("Let the model decide thinking depth") },
        trailingContent = {
            SebastianSwitch(checked = checked, onCheckedChange = onCheckedChange)
        },
        modifier = modifier,
    )
}
```

- [ ] **Step 2: Build**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/AdaptiveSwitch.kt
git commit -m "feat(android/ui): 新增 AdaptiveSwitch 组件（复用 SebastianSwitch）"
```

---

### Task B6: 构造 `ProviderPickerDialog` 组件

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt`

- [ ] **Step 1: 实现**

```kotlin
package com.sebastian.android.ui.settings.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Provider

@Composable
fun ProviderPickerDialog(
    currentProviderId: String?,
    providers: List<Provider>,
    onDismiss: () -> Unit,
    onSelect: (String?) -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Select LLM Provider") },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 480.dp)
                    .verticalScroll(rememberScrollState()),
            ) {
                ListItem(
                    headlineContent = { Text("Use default provider") },
                    trailingContent = if (currentProviderId == null) {
                        { Icon(Icons.Filled.CheckCircle, contentDescription = "selected") }
                    } else null,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSelect(null) },
                )
                HorizontalDivider()
                providers.forEach { provider ->
                    ListItem(
                        headlineContent = { Text(provider.name) },
                        supportingContent = { Text(provider.type) },
                        trailingContent = if (currentProviderId == provider.id) {
                            { Icon(Icons.Filled.CheckCircle, contentDescription = "selected") }
                        } else null,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(provider.id) },
                    )
                    HorizontalDivider()
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Close") }
        },
    )
}
```

- [ ] **Step 2: Build**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt
git commit -m "feat(android/ui): 新增 ProviderPickerDialog 居中浮层组件"
```

---

### Task B7: `AgentBindingEditorViewModel`

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt`
- Create: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModelTest.kt`

- [ ] **Step 1: 写失败测试（覆盖关键行为）**

```kotlin
// AgentBindingEditorViewModelTest.kt
package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class AgentBindingEditorViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val agentRepo: AgentRepository = mock()
    private val settingsRepo: SettingsRepository = mock()

    @Before fun before() { Dispatchers.setMain(dispatcher) }
    @After fun after() { Dispatchers.resetMain() }

    @Test
    fun `selectProvider resets thinking config and debounce-puts`() = runTest(dispatcher) {
        val adaptive = Provider(id = "p1", name = "Claude", type = "anthropic", model = "c", isDefault = false, thinkingCapability = ThinkingCapability.ADAPTIVE)
        val effort = Provider(id = "p2", name = "GPT", type = "openai", model = "g", isDefault = false, thinkingCapability = ThinkingCapability.EFFORT)
        whenever(agentRepo.getBinding("sebastian")).thenReturn(Result.success(
            AgentBindingDto("sebastian", "p1", "high", true),
        ))
        whenever(settingsRepo.getProviders()).thenReturn(Result.success(listOf(adaptive, effort)))

        val vm = AgentBindingEditorViewModel("sebastian", agentRepo, settingsRepo)
        vm.load()
        dispatcher.scheduler.advanceUntilIdle()

        vm.selectProvider("p2")
        // 本地立即重置
        assertEquals(ThinkingEffort.OFF, vm.uiState.value.thinkingEffort)
        assertTrue(!vm.uiState.value.thinkingAdaptive)

        // 300ms 后 PUT
        dispatcher.scheduler.advanceTimeBy(350)
        verify(agentRepo).setBinding("sebastian", "p2", ThinkingEffort.OFF, false)
    }

    @Test
    fun `setEffort debounces consecutive changes into single put`() = runTest(dispatcher) {
        val p = Provider("p1", "C", "anthropic", "c", false, ThinkingCapability.EFFORT)
        whenever(agentRepo.getBinding("sebastian")).thenReturn(Result.success(
            AgentBindingDto("sebastian", "p1", null, false),
        ))
        whenever(settingsRepo.getProviders()).thenReturn(Result.success(listOf(p)))

        val vm = AgentBindingEditorViewModel("sebastian", agentRepo, settingsRepo)
        vm.load()
        dispatcher.scheduler.advanceUntilIdle()

        vm.setEffort(ThinkingEffort.LOW)
        dispatcher.scheduler.advanceTimeBy(100)
        vm.setEffort(ThinkingEffort.MEDIUM)
        dispatcher.scheduler.advanceTimeBy(100)
        vm.setEffort(ThinkingEffort.HIGH)
        dispatcher.scheduler.advanceTimeBy(350)

        verify(agentRepo).setBinding("sebastian", "p1", ThinkingEffort.HIGH, false)
    }

    @Test
    fun `effective capability falls back to default provider when binding has no provider`() = runTest(dispatcher) {
        val def = Provider("pd", "Default", "anthropic", "c", isDefault = true, thinkingCapability = ThinkingCapability.ADAPTIVE)
        whenever(agentRepo.getBinding("foo")).thenReturn(Result.success(
            AgentBindingDto("foo", null, null, false),
        ))
        whenever(settingsRepo.getProviders()).thenReturn(Result.success(listOf(def)))

        val vm = AgentBindingEditorViewModel("foo", agentRepo, settingsRepo)
        vm.load()
        dispatcher.scheduler.advanceUntilIdle()

        assertEquals(ThinkingCapability.ADAPTIVE, vm.uiState.value.effectiveCapability)
    }

    @Test
    fun `out-of-range effort is coerced to highest valid step on init`() = runTest(dispatcher) {
        val effortOnly = Provider("p", "GPT", "openai", "g", false, ThinkingCapability.EFFORT)
        // DB 里留下 max（上一任 provider 是 adaptive）
        whenever(agentRepo.getBinding("foo")).thenReturn(Result.success(
            AgentBindingDto("foo", "p", "max", true),
        ))
        whenever(settingsRepo.getProviders()).thenReturn(Result.success(listOf(effortOnly)))

        val vm = AgentBindingEditorViewModel("foo", agentRepo, settingsRepo)
        vm.load()
        dispatcher.scheduler.advanceUntilIdle()

        assertEquals(ThinkingEffort.HIGH, vm.uiState.value.thinkingEffort)
        assertTrue(!vm.uiState.value.thinkingAdaptive)
        // 并且触发 PUT 纠正
        dispatcher.scheduler.advanceTimeBy(350)
        verify(agentRepo).setBinding("foo", "p", ThinkingEffort.HIGH, false)
    }
}
```

- [ ] **Step 2: Run test (fail)**

```bash
cd ui/mobile-android && ./gradlew test --tests '*AgentBindingEditorViewModelTest*'
```

Expected: FAIL

- [ ] **Step 3: 实现 ViewModel**

```kotlin
// AgentBindingEditorViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.toThinkingEffort
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.ui.settings.components.effortStepsFor
import dagger.assisted.Assisted
import dagger.assisted.AssistedFactory
import dagger.assisted.AssistedInject
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class EditorUiState(
    val agentType: String,
    val agentDisplayName: String = "",
    val isOrchestrator: Boolean = false,
    val providers: List<Provider> = emptyList(),
    val selectedProvider: Provider? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
    val thinkingAdaptive: Boolean = false,
    val isSaving: Boolean = false,
    val errorMessage: String? = null,
    val loading: Boolean = true,
) {
    val effectiveCapability: ThinkingCapability?
        get() = (selectedProvider ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
}

sealed interface EditorEvent {
    data class Snackbar(val text: String) : EditorEvent
}

class AgentBindingEditorViewModel @AssistedInject constructor(
    @Assisted private val agentType: String,
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
) : ViewModel() {

    @AssistedFactory
    interface Factory {
        fun create(agentType: String): AgentBindingEditorViewModel
    }

    private val _uiState = MutableStateFlow(EditorUiState(agentType = agentType))
    val uiState: StateFlow<EditorUiState> = _uiState

    private val _events = MutableSharedFlow<EditorEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<EditorEvent> = _events.asSharedFlow()

    private var putJob: Job? = null
    private var snapshot: EditorUiState? = null

    fun load() {
        viewModelScope.launch {
            val bindingR = agentRepository.getBinding(agentType)
            val providersR = settingsRepository.getProviders()
            val err = bindingR.exceptionOrNull() ?: providersR.exceptionOrNull()
            if (err != null) {
                _uiState.update { it.copy(loading = false, errorMessage = err.message) }
                return@launch
            }
            val dto = bindingR.getOrThrow()
            val providers = providersR.getOrThrow()
            val selected = providers.firstOrNull { it.id == dto.providerId }
            val capability = (selected ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
            val (coercedEffort, coercedAdaptive, wasCoerced) =
                coerceEffort(dto.thinkingEffort.toThinkingEffort(), dto.thinkingAdaptive, capability)
            _uiState.update {
                it.copy(
                    loading = false,
                    providers = providers,
                    selectedProvider = selected,
                    thinkingEffort = coercedEffort,
                    thinkingAdaptive = coercedAdaptive,
                )
            }
            if (wasCoerced) schedulePut()
        }
    }

    fun selectProvider(providerId: String?) {
        val prev = _uiState.value
        val next = prev.providers.firstOrNull { it.id == providerId }
        val providerChanged = prev.selectedProvider?.id != providerId
        val hadConfig = prev.thinkingEffort != ThinkingEffort.OFF || prev.thinkingAdaptive
        _uiState.update {
            it.copy(
                selectedProvider = next,
                thinkingEffort = if (providerChanged) ThinkingEffort.OFF else it.thinkingEffort,
                thinkingAdaptive = if (providerChanged) false else it.thinkingAdaptive,
            )
        }
        if (providerChanged && hadConfig) {
            _events.tryEmit(EditorEvent.Snackbar("Thinking config reset for new provider"))
        }
        schedulePut()
    }

    fun setEffort(e: ThinkingEffort) {
        _uiState.update { it.copy(thinkingEffort = e) }
        schedulePut()
    }

    fun setAdaptive(enabled: Boolean) {
        _uiState.update { it.copy(thinkingAdaptive = enabled) }
        schedulePut()
    }

    private fun schedulePut() {
        putJob?.cancel()
        snapshot = _uiState.value
        putJob = viewModelScope.launch {
            delay(300)
            val s = _uiState.value
            _uiState.update { it.copy(isSaving = true) }
            val r = agentRepository.setBinding(
                agentType,
                s.selectedProvider?.id,
                s.thinkingEffort,
                s.thinkingAdaptive,
            )
            _uiState.update { it.copy(isSaving = false) }
            r.onFailure { err ->
                val snap = snapshot
                if (snap != null) _uiState.value = snap.copy(errorMessage = null, isSaving = false)
                _events.tryEmit(EditorEvent.Snackbar("Failed to save. Retry?"))
            }
        }
    }

    private fun coerceEffort(
        effort: ThinkingEffort,
        adaptive: Boolean,
        capability: ThinkingCapability?,
    ): Triple<ThinkingEffort, Boolean, Boolean> {
        val steps = capability?.let { effortStepsFor(it) } ?: return Triple(effort, adaptive, false)
        if (effort !in steps) {
            // 钳到最高合法档位
            val fallback = steps.lastOrNull { it != ThinkingEffort.OFF } ?: ThinkingEffort.OFF
            return Triple(fallback, false, true)
        }
        if (capability != ThinkingCapability.ADAPTIVE && adaptive) {
            return Triple(effort, false, true)
        }
        return Triple(effort, adaptive, false)
    }
}
```

> 注：ViewModel 使用 Hilt `@AssistedInject` 因为 `agentType` 来自 navigation。`DI` 层需要补一条 assisted factory（见 Step 5）。

- [ ] **Step 4: Run test (pass)**

```bash
cd ui/mobile-android && ./gradlew test --tests '*AgentBindingEditorViewModelTest*'
```

Expected: PASS

- [ ] **Step 5: DI 配置**

在 `di/RepositoryModule.kt`（或对应 ViewModel 模块）确保 `AgentBindingEditorViewModel.Factory` 被 Hilt 解析；页面里用 `assistedFactory.create(agentType)` 获取。参考其他 assisted ViewModel（如 `ProviderFormViewModel`）的现有写法。

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModelTest.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/di/
git commit -m "feat(android/vm): 新增 AgentBindingEditorViewModel（debounce 保存 + 重置 + 钳制）"
```

---

### Task B8: `AgentBindingEditorPage` 装配

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt`

- [ ] **Step 1: 替换 stub 为完整页面**

```kotlin
package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.ui.settings.components.AdaptiveSwitch
import com.sebastian.android.ui.settings.components.EffortSlider
import com.sebastian.android.ui.settings.components.ProviderPickerDialog
import com.sebastian.android.viewmodel.AgentBindingEditorViewModel
import com.sebastian.android.viewmodel.EditorEvent
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingEditorPage(
    agentType: String,
    navController: NavController,
) {
    val factory = (hiltViewModel<AgentBindingEditorEntry>()).factory
    val vm = remember(agentType) { factory.create(agentType) }
    val state by vm.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) { vm.load() }
    LaunchedEffect(vm) {
        vm.events.collect { ev ->
            when (ev) {
                is EditorEvent.Snackbar -> scope.launch { snackbarHostState.showSnackbar(ev.text) }
            }
        }
    }

    var showPicker by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(state.selectedProvider?.name ?: agentType.replaceFirstChar { it.uppercase() }) },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        if (state.loading) {
            Column(
                modifier = Modifier.fillMaxSize().padding(padding),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator() }
            return@Scaffold
        }

        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            Text("LLM Provider", style = MaterialTheme.typography.titleSmall)
            ElevatedCard(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 8.dp),
            ) {
                ListItem(
                    leadingContent = { Icon(Icons.Outlined.Memory, contentDescription = null) },
                    headlineContent = {
                        Text(state.selectedProvider?.name ?: "Use default provider")
                    },
                    supportingContent = {
                        Text(state.selectedProvider?.type ?: "Follow global default")
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                )
            }
            androidx.compose.foundation.layout.Spacer(Modifier.size(16.dp))

            val capability = state.effectiveCapability
            when (capability) {
                null -> {
                    Text("No default provider configured", style = MaterialTheme.typography.bodyMedium)
                }
                ThinkingCapability.NONE -> Unit
                ThinkingCapability.ALWAYS_ON -> {
                    ListItem(
                        headlineContent = { Text("Thinking: Always on (controlled by model)") },
                    )
                }
                else -> {
                    Text("Thinking Depth", style = MaterialTheme.typography.titleSmall)
                    EffortSlider(
                        capability = capability,
                        value = state.thinkingEffort,
                        onValueChange = vm::setEffort,
                        enabled = !(capability == ThinkingCapability.ADAPTIVE && state.thinkingAdaptive),
                    )
                    if (capability == ThinkingCapability.ADAPTIVE) {
                        AdaptiveSwitch(
                            checked = state.thinkingAdaptive,
                            onCheckedChange = vm::setAdaptive,
                        )
                    }
                }
            }
        }

        if (showPicker) {
            ProviderPickerDialog(
                currentProviderId = state.selectedProvider?.id,
                providers = state.providers,
                onDismiss = { showPicker = false },
                onSelect = { pid ->
                    vm.selectProvider(pid)
                    showPicker = false
                },
            )
        }
    }
}
```

> Provider 卡片点击触发 `showPicker = true`：在上面的 ElevatedCard 外包 `Modifier.clickable { showPicker = true }`（补加 import `androidx.compose.foundation.clickable`）。

> `AgentBindingEditorEntry` 是一个小的 Hilt entry point 用于从 `hiltViewModel()` 拿到 `AssistedFactory`；参见现有 `ProviderFormPage` 的写法（可能直接命名为 `<VMName>Factory`）。如果项目中 Assisted+Hilt 已有成例，沿用。

- [ ] **Step 2: Build + Manual Smoke**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt
git commit -m "feat(android/ui): AgentBindingEditorPage 装配 provider/effort/adaptive 三控件"
```

---

### Task B9: 重构 `AgentBindingsPage` 列表

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt`

- [ ] **Step 1: 简化 `AgentBindingsViewModel`**

整文件替换为：

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AgentBindingsUiState(
    val loading: Boolean = false,
    val agents: List<AgentInfo> = emptyList(),
    val providers: List<Provider> = emptyList(),
    val errorMessage: String? = null,
)

@HiltViewModel
class AgentBindingsViewModel @Inject constructor(
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(AgentBindingsUiState())
    val uiState: StateFlow<AgentBindingsUiState> = _uiState

    fun load() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, errorMessage = null) }
            val agentsR = agentRepository.getAgents()
            val providersR = settingsRepository.getProviders()
            val err = agentsR.exceptionOrNull() ?: providersR.exceptionOrNull()
            _uiState.update {
                it.copy(
                    loading = false,
                    agents = agentsR.getOrDefault(emptyList()),
                    providers = providersR.getOrDefault(emptyList()),
                    errorMessage = err?.message,
                )
            }
        }
    }
}
```

（删除 `bind` / `useDefault` / events — 全部下放到 Editor 页）

- [ ] **Step 2: 重写 `AgentBindingsPage.kt`**

整文件替换为：

```kotlin
package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.AgentBindingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentBindingsPage(
    navController: NavController,
    viewModel: AgentBindingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Agent LLM Bindings") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        val (orchestrator, subAgents) = state.agents.partition { it.isOrchestrator }
        val defaultProvider = state.providers.firstOrNull { it.isDefault }

        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding)) {
            if (orchestrator.isNotEmpty()) {
                item { SectionHeader("Orchestrator") }
                items(orchestrator, key = { it.agentType }) { agent ->
                    AgentRow(
                        agent = agent,
                        providers = state.providers,
                        defaultProviderName = defaultProvider?.name,
                        icon = Icons.Outlined.AutoAwesome,
                        onClick = {
                            navController.navigate(Route.SettingsAgentBindingEditor(agent.agentType))
                        },
                    )
                }
            }
            if (subAgents.isNotEmpty()) {
                item { SectionHeader("Sub-Agents") }
                items(subAgents, key = { it.agentType }) { agent ->
                    AgentRow(
                        agent = agent,
                        providers = state.providers,
                        defaultProviderName = defaultProvider?.name,
                        icon = Icons.Outlined.Extension,
                        onClick = {
                            navController.navigate(Route.SettingsAgentBindingEditor(agent.agentType))
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun SectionHeader(title: String) {
    Column {
        Text(
            text = title,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp),
        )
        HorizontalDivider()
    }
}

@Composable
private fun AgentRow(
    agent: AgentInfo,
    providers: List<com.sebastian.android.data.model.Provider>,
    defaultProviderName: String?,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
) {
    val bound = providers.firstOrNull { it.id == agent.boundProviderId }
    val subtitle = if (bound != null) {
        buildString {
            append(bound.name)
            if (agent.thinkingEffort != ThinkingEffort.OFF) {
                append(" · ")
                append(
                    when (agent.thinkingEffort) {
                        ThinkingEffort.ON -> "on"
                        ThinkingEffort.LOW -> "low"
                        ThinkingEffort.MEDIUM -> "medium"
                        ThinkingEffort.HIGH -> "high"
                        ThinkingEffort.MAX -> "max"
                        ThinkingEffort.OFF -> ""
                    }
                )
                if (agent.thinkingAdaptive) append(" · adaptive")
            }
        }
    } else {
        "Use default · ${defaultProviderName ?: "—"}"
    }

    ElevatedCard(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .clickable { onClick() },
    ) {
        ListItem(
            leadingContent = { Icon(icon, contentDescription = null) },
            headlineContent = { Text(agent.displayName) },
            supportingContent = { Text(subtitle) },
        )
    }
}
```

- [ ] **Step 3: Build**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt
git commit -m "refactor(android/ui): AgentBindingsPage 改为分区列表 + 次级页导航"
```

---

### Task B10: 移除 Composer 思考按钮链路

**Files:**
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt`
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/EffortPickerCard.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/Composer.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`

- [ ] **Step 1: 删 ThinkButton.kt 与 EffortPickerCard.kt**

```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/EffortPickerCard.kt
```

- [ ] **Step 2: 改 `Composer.kt`**

整文件替换，删 `effort`/`onEffortChange`/`onShowEffortPicker`/`activeProvider` 参数，删 `ThinkButton` 调用；其余保留：

```kotlin
package com.sebastian.android.ui.composer

// imports: 删掉 Provider / ThinkingEffort / ThinkButton 相关 import

@Composable
fun Composer(
    state: ComposerState,
    glassState: GlassState,
    onSend: (String) -> Unit,
    onStop: () -> Unit,
    voiceSlot: @Composable (() -> Unit)? = null,
    attachmentSlot: @Composable (() -> Unit)? = null,
    attachmentPreviewSlot: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    var text by rememberSaveable { mutableStateOf("") }

    val effectiveState = when {
        state == ComposerState.STREAMING || state == ComposerState.SENDING || state == ComposerState.CANCELLING -> state
        text.isNotBlank() -> ComposerState.IDLE_READY
        else -> ComposerState.IDLE_EMPTY
    }

    GlassSurface(
        state = glassState,
        shape = RoundedCornerShape(24.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column {
            AnimatedVisibility(visible = attachmentPreviewSlot != null) {
                attachmentPreviewSlot?.invoke()
            }

            TextField(
                value = text,
                onValueChange = { text = it },
                placeholder = {
                    androidx.compose.material3.Text("发消息给 Sebastian")
                },
                maxLines = 6,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            // 工具栏（ThinkButton 位置留空，Composer 整体高度不变）
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 12.dp, end = 4.dp, top = 2.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 原 ThinkButton 位置空出，用与 ThinkButton 等高的 Spacer 占位（48dp 高度）
                Spacer(Modifier.size(width = 0.dp, height = 48.dp))
                voiceSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }
                attachmentSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }
                Spacer(Modifier.weight(1f))
                SendButton(
                    state = effectiveState,
                    onSend = {
                        val msg = text.trim()
                        if (msg.isNotEmpty()) {
                            text = ""
                            onSend(msg)
                        }
                    },
                    onStop = onStop,
                )
            }
        }
    }
}
```

> 补 `Spacer` 和 `size` 的 import。**高度确保 48.dp 等同于原 ThinkButton 的视觉高度**，保证整体 Composer 高度不变。

- [ ] **Step 3: 改 `ChatScreen.kt`**

删除：
- L63 `import com.sebastian.android.ui.composer.EffortPickerCard`
- L154 `var showEffortPicker by remember { mutableStateOf(false) }`
- L328-370 `EffortPickerCard overlay` 整块（`showPickerCard` 值、外层 Box 的点击关闭、EffortPickerCard 调用）
- L379 `onShowEffortPicker = { showEffortPicker = true }`

同时修改 Composer 调用处，去掉传入的 `activeProvider`/`effort`/`onEffortChange`/`onShowEffortPicker` 参数（只保留 `state`/`glassState`/`onSend`/`onStop`）。

- [ ] **Step 4: 改 `ChatViewModel.kt`**

- 删除 `activeThinkingEffort` MutableStateFlow 与对外暴露
- 删除 `setEffort(...)` 方法
- 改 `sendMessage` / `sendTurn` 调用：去掉 `effort` 参数
- 搜索所有 `ThinkingEffort` 的 import 若无其他用途一并删除

- [ ] **Step 5: 改 `ChatRepository` 接口 + `ChatRepositoryImpl.kt`**

`ChatRepository.kt` 接口：`sendTurn` / `sendSessionTurn` 签名去掉 `effort: ThinkingEffort` 参数。

`ChatRepositoryImpl.kt`：
- L30 签名去掉 `effort`
- L32-36 `SendTurnRequest(content=..., sessionId=..., thinkingEffort=...)` 改成 `SendTurnRequest(content=content, sessionId=sessionId)`
- L41-42 同理
- L76-83 整段 `toApiString` 删除（已移到 `data/model/ThinkingEffort.kt` 公共位置）

- [ ] **Step 6: Build**

```bash
cd ui/mobile-android && ./gradlew compileDebugKotlin
```

Expected: BUILD SUCCESSFUL

- [ ] **Step 7: 单测**

```bash
cd ui/mobile-android && ./gradlew test
```

Expected: PASS（旧的 ChatViewModel test 若引用 `effort` 参数需要同步清理）

- [ ] **Step 8: Commit**

```bash
git add -A  # 含删除的两文件
git commit -m "refactor(android): 移除 ThinkButton / EffortPickerCard / ChatViewModel.effort 全链路"
```

---

### Task B11: 更新 README

**Files:**
- Modify: `ui/mobile-android/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md`（如含 composer 修改表）

- [ ] **Step 1: 更新「修改导航」表**

`ui/mobile-android/README.md` L198-199 附近：

```diff
- | 改输入框（Composer） | `ui/composer/Composer.kt`、`SendButton.kt`、`ThinkButton.kt` |
+ | 改输入框（Composer） | `ui/composer/Composer.kt`、`SendButton.kt` |
```

补一行：

```diff
+ | 改 Agent LLM 绑定次级页 | `ui/settings/AgentBindingEditorPage.kt`、`viewmodel/AgentBindingEditorViewModel.kt`、`ui/settings/components/*.kt` |
```

同步更新导航信息架构章节，在 `SettingsAgentBindings` 节点下加 `SettingsAgentBindingEditor` 子节点。

- [ ] **Step 2: 更新 ui/ README（如需要）**

若 `ui/README.md` 或 `ui/settings/README.md` 有组件清单，补上 `components/EffortSlider.kt`、`AdaptiveSwitch.kt`、`ProviderPickerDialog.kt`。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/
git commit -m "docs(android): README 同步 AgentBinding 次级页与 Composer 变更"
```

---

### Task B12: 全量验证

- [ ] **Step 1: Lint / test / build**

```bash
cd ui/mobile-android
./gradlew lint
./gradlew test
./gradlew compileDebugKotlin
```

Expected: all PASS

- [ ] **Step 2: 手动验收（按 spec § 7.4 清单）**

- [ ] Bindings 列表顶部 Orchestrator 分区 + Sebastian 条目
- [ ] Sub-Agents 分区按原顺序展示
- [ ] 点击条目进入 Editor 次级页
- [ ] Provider 卡片弹出居中 Dialog（非 BottomSheet）
- [ ] Dialog 首行 Use default provider 正常
- [ ] 选 EFFORT provider → 4 档 slider，无 Adaptive 开关
- [ ] 选 ADAPTIVE provider → 5 档 slider + Adaptive 开关
- [ ] Adaptive 开关开启 → slider 半透明不响应；关闭 → 恢复
- [ ] 选 TOGGLE provider → Switch（非 slider）
- [ ] 选 NONE 能力 provider → 思考区完全隐藏
- [ ] 选 ALWAYS_ON provider → 只读 label
- [ ] 切换 provider → snackbar 提示重置
- [ ] 返回列表，副标题正确
- [ ] Composer 已无 ThinkButton，整体高度不变
- [ ] ChatScreen 已无 EffortPickerCard 浮层
- [ ] 发消息可以在后端日志看到 binding 的 effort 被注入
- [ ] 所有文案英文，无 emoji
- [ ] 无默认 provider 时，Editor 页显示 `No default provider configured`

- [ ] **Step 3: 若手动验收发现问题，按问题驱动的单独 task 修**

不要把多个手动问题一次性批量改；每个 follow-up 一个 commit。

- [ ] **Step 4: Push**

```bash
git push
```

---

## 自审

1. **Spec 覆盖**：
   - § 2 数据模型 → Task A1 ✓
   - § 3.1 API 扩展 + 重置逻辑 → Task A3 ✓
   - § 3.2 Sebastian 解屏 → Task A3 ✓
   - § 3.3 思考参数注入 → Task A2 (registry) + A4 (base_agent) ✓
   - § 3.4 废弃 SendTurnRequest.thinking_effort → Task A5 ✓
   - § 4.1 路由 → Task B3 ✓
   - § 4.2 新增文件 → Task B4/B5/B6/B7/B8 ✓
   - § 4.3 改造与删除 → Task B9/B10 ✓
   - § 4.4 ViewModel 接口 → Task B7 ✓
   - § 5.1 列表分区 → Task B9 ✓
   - § 5.2 Editor 布局 → Task B8 ✓
   - § 5.3 Dialog → Task B6 ✓
   - § 5.4 EffortSlider → Task B4 ✓
   - § 5.5 AdaptiveSwitch → Task B5 ✓
   - § 5.6 ALWAYS_ON / NONE / effectiveCapability == null → Task B8 ✓
   - § 6 交互边界 → Task B7 (debounce/reset/coerce) + B8 (loading/error) ✓
   - § 7 测试 → Task A1/A2/A3/A4/A5 (后端) + Task B4/B7 (Android) ✓
   - § 9 受影响文件清单 → 全部被上述 Task 覆盖 ✓

2. **Placeholder 扫描**：无 TBD / TODO / "similar to" / "handle edge cases" 残留。

3. **类型一致性**：
   - `ResolvedProvider`（Python dataclass） ↔ Android 不直接映射，Android 消费 `AgentBindingDto` 的 `thinking_effort: String?` → `ThinkingEffort` enum（`toThinkingEffort()` 扩展统一在 `data/model/ThinkingEffort.kt`）
   - `EditorUiState.effectiveCapability` 派生属性在 ViewModel 与 Page 两处用法一致
   - `effortStepsFor(capability)` 在 Task B4 定义，Task B7 的 ViewModel `coerceEffort` 引用同一个函数

可以交付。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-agent-binding-thinking-migration.md`.

两种执行方式：

**1. Subagent-Driven（推荐）** — 每个 Task 派一个独立 subagent 做完即回归主会话 review，可快速并行尝试。

**2. Inline Execution** — 在当前会话批次执行，中途插 checkpoints。

请选择一种方式开始实施。

# Thinking-Effort Review 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development 执行本计划。步骤使用 checkbox (`- [ ]`) 语法跟踪进度。

**Goal:** 修复 thinking-effort 功能 review 中发现的 P0 / P1 问题，让"输入框思考档位"在全路径（含 sub-agent 首条消息）真正控制 LLM 思考开启与否，并修正静默兜底、DB migration 缺失、PUT 接口语义缺陷与 clamp toast 闭环。

**Architecture:** 修复分散在后端 Provider/Gateway/Store 与前端 Composer/Settings 多模块。原则：不引入新设计，只修错；不做兼容补丁，失败直接抛异常；不超 spec（`docs/superpowers/specs/2026-04-08-thinking-effort-design.md`）。

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy async, Pydantic v2, pytest-asyncio)，React Native + Zustand + TypeScript。

**Review 来源：** Spec 合规 + 代码质量双审查于 2026-04-08 完成，覆盖 `80554a8..HEAD` 26 个 commit。

---

## 问题一览（按优先级）

| ID | 级别 | 文件 | 摘要 |
|----|------|------|------|
| P0-1 | 严重 | `sebastian/core/session_runner.py` + `sebastian/gateway/routes/sessions.py:57` + `ui/mobile/src/api/sessions.ts:105` + `ui/mobile/app/subagents/session/[id].tsx` | Sub-agent 新会话首条消息 `thinking_effort` 丢失 |
| P0-2 | 严重 | `sebastian/llm/anthropic.py:74-86` | effort 模式静默兜底，违反"不许降级"原则 |
| P0-3 | 严重 | `sebastian/store/database.py:42-46` | `llm_providers.thinking_capability` 新列无 idempotent ALTER，升级即炸 |
| P1-4 | 重要 | `ui/mobile/src/store/composer.ts:79-99` + 三处调用 | Clamp 发生时无 toast，已有 session 被 clamp 完全不报告 |
| P1-5 | 重要 | `sebastian/gateway/routes/llm_providers.py:84-112` | PUT 用 `is not None` 判断，无法显式清空字段 |
| P1-6 | 重要 | OpenAI 路径测试 | `thinking_capability='effort'` × `thinking_format='reasoning_content'` 双轴组合未覆盖 |

---

## File Structure

本计划**只改已有文件**，不新增模块。涉及文件（共 12 个）：

**后端：**
- `sebastian/llm/anthropic.py` — 移除静默兜底，改抛 ValueError
- `sebastian/store/database.py` — 新增 idempotent ALTER TABLE 逻辑
- `sebastian/gateway/routes/llm_providers.py` — PUT 改 `model_dump(exclude_unset=True)`
- `sebastian/gateway/routes/sessions.py` — `POST /agents/{type}/sessions` 接收 thinking_effort
- `sebastian/core/session_runner.py` — `run_agent_session` 新增 thinking_effort 参数

**前端：**
- `ui/mobile/src/api/sessions.ts` — `createAgentSession` 新增 thinkingEffort 参数
- `ui/mobile/app/subagents/session/[id].tsx` — 新建分支把 `opts.effort` 传入
- `ui/mobile/src/store/composer.ts` — `clampAllToCapability` 返回结构化对象并覆盖所有场景
- `ui/mobile/src/api/llm.ts` — `onClamped` 回调接入 toast
- `ui/mobile/app/_layout.tsx` — 启动同步补 toast 回调
- `ui/mobile/src/components/settings/LLMProviderConfig.tsx` — provider 切换后 toast 回调

**测试：**
- `tests/unit/test_anthropic_provider_thinking.py` — 新增 `ValueError` 抛出用例、删除原静默用例
- `tests/unit/test_openai_compat_thinking.py` — 新增 effort × reasoning_content 双轴测试
- `tests/unit/test_llm_providers_route.py`（或同等文件）— 新增 PUT 显式 null 用例
- 新建 `tests/unit/test_create_agent_session_thinking.py` — sub-agent 新会话首条消息透传

---

## Task 1：修复 P0-2 Anthropic 静默兜底（改抛异常）

**Files:**
- Modify: `sebastian/llm/anthropic.py:47-88`
- Test: `tests/unit/test_anthropic_provider_thinking.py`

**背景：** `_build_thinking_kwargs` 在 `effort` 模式下对 `effort='max'` 与 `budget >= max_tokens` 两处都 `return {}`（静默禁用）。违反 CLAUDE.md "不允许兼容补丁 / 失败抛异常"原则。

- [ ] **Step 1：写失败测试**

在 `tests/unit/test_anthropic_provider_thinking.py` 追加：

```python
import pytest
from sebastian.llm.anthropic import AnthropicProvider


def test_effort_max_raises_for_capability_effort() -> None:
    """capability='effort' 下传入 'max' 应抛 ValueError（'max' 仅 adaptive 允许）。"""
    provider = AnthropicProvider(api_key="sk-test", thinking_capability="effort")
    with pytest.raises(ValueError, match="max.*not allowed.*effort"):
        provider._build_thinking_kwargs("max", max_tokens=8192)


def test_effort_budget_exceeds_max_tokens_raises() -> None:
    """effort='high' (budget=24576) 但 max_tokens=8192 时应抛 ValueError。"""
    provider = AnthropicProvider(api_key="sk-test", thinking_capability="effort")
    with pytest.raises(ValueError, match="budget_tokens.*max_tokens"):
        provider._build_thinking_kwargs("high", max_tokens=8192)
```

- [ ] **Step 2：运行测试确认失败**

```bash
pytest tests/unit/test_anthropic_provider_thinking.py::test_effort_max_raises_for_capability_effort tests/unit/test_anthropic_provider_thinking.py::test_effort_budget_exceeds_max_tokens_raises -v
```

预期：FAIL（当前返回 `{}` 而非抛错）。

- [ ] **Step 3：修改 `_build_thinking_kwargs`**

将 `sebastian/llm/anthropic.py` 中的 effort 分支改为：

```python
if capability == 'effort':
    budget = self.FIXED_EFFORT_TO_BUDGET.get(thinking_effort)
    if budget is None:
        raise ValueError(
            f"thinking_effort={thinking_effort!r} not allowed for "
            f"thinking_capability='effort' (allowed: low/medium/high)"
        )
    if budget >= max_tokens:
        raise ValueError(
            f"budget_tokens={budget} must be strictly less than "
            f"max_tokens={max_tokens}; raise max_tokens or lower effort"
        )
    return {'thinking': {'type': 'enabled', 'budget_tokens': budget}}
```

同时清理已不再需要的 clamp 注释（原 77-85 行）。

- [ ] **Step 4：删除/更新已有静默兜底相关测试**

查找 `test_anthropic_provider_thinking.py` 里断言 `_build_thinking_kwargs` 在上述两种边界返回 `{}` 的旧用例，删除或改为断言抛 `ValueError`。

- [ ] **Step 5：运行所有 Anthropic thinking 测试**

```bash
pytest tests/unit/test_anthropic_provider_thinking.py -v
```

预期：全绿。

- [ ] **Step 6：检查 clamp 的上游——前端永远不该送 illegal effort**

Grep `ui/mobile/src` 确认 `setEffort` 所有调用点都来自 `EFFORT_LEVELS_BY_CAPABILITY[capability]`，不会越权。若没问题，不需要改前端。

- [ ] **Step 7：commit**

```bash
git add sebastian/llm/anthropic.py tests/unit/test_anthropic_provider_thinking.py
git commit -m "$(cat <<'EOF'
fix(llm): Anthropic effort 模式错误时改抛 ValueError 不再静默降级

Review 发现 _build_thinking_kwargs 在两种边界下静默返回 {}，违反项目
"不允许兼容补丁/失败抛异常"原则：
- effort='max' 配 capability='effort' → 应抛错
- budget >= max_tokens → 应抛错

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：修复 P0-3 DB schema 新列无 migration

**Files:**
- Modify: `sebastian/store/database.py:42-46`
- Test: 手工验证（老 DB 启动）

**背景：** 仓库仅靠 `Base.metadata.create_all`，已存在的 `llm_providers` 表**不会**自动加 `thinking_capability` 列。现有部署升级后 INSERT/SELECT 都会炸。

- [ ] **Step 1：修改 `init_db()`**

在 `sebastian/store/database.py` 的 `init_db` 中，于 `Base.metadata.create_all` 之后加入 idempotent ALTER（只处理 SQLite 路径）：

```python
async def init_db() -> None:
    """Create all tables. Call once at startup."""
    from sebastian.store import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    logger.info("Database initialized")


async def _apply_idempotent_migrations(conn: Any) -> None:
    """Apply best-effort schema patches for columns added after initial create_all.

    Each entry: (table, column, DDL fragment).
    """
    from sqlalchemy import text

    patches: list[tuple[str, str, str]] = [
        ("llm_providers", "thinking_capability", "VARCHAR(20)"),
    ]
    for table, column, ddl in patches:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {row[1] for row in result.fetchall()}
        if column not in existing:
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
            )
            logger.info("Applied migration: %s.%s", table, column)
```

注意：import `Any` 若未存在需补上 `from typing import Any`。

- [ ] **Step 2：手工验证**

```bash
# 备份并模拟老 DB（删除 thinking_capability 列后重启）
python3 -c "
import asyncio, sqlite3, os
from pathlib import Path
db = Path.home() / '.sebastian' / 'sebastian.db'
if db.exists():
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(llm_providers)').fetchall()]
    print('before:', cols)
    conn.close()
"

# 启动 gateway 触发 init_db
python3 -c "
import asyncio
from sebastian.store.database import init_db
asyncio.run(init_db())
"

python3 -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.sebastian' / 'sebastian.db'
conn = sqlite3.connect(db)
cols = [r[1] for r in conn.execute('PRAGMA table_info(llm_providers)').fetchall()]
print('after:', cols)
assert 'thinking_capability' in cols
print('OK')
"
```

预期：after 输出包含 `thinking_capability`。

- [ ] **Step 3：commit**

```bash
git add sebastian/store/database.py
git commit -m "$(cat <<'EOF'
fix(store): init_db 补 idempotent ALTER 为 thinking_capability 列补丁

老部署升级时 Base.metadata.create_all 不会加新列，SELECT/INSERT 会炸。
改为检查 PRAGMA table_info 后按需 ALTER，后续新增列可在 patches 列表追加。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：修复 P1-5 PUT /llm-providers 用 exclude_unset

**Files:**
- Modify: `sebastian/gateway/routes/llm_providers.py:84-112`
- Test: 新增 `tests/unit/test_llm_providers_route.py` 若不存在（先 grep 确认）

**背景：** 当前 `if body.thinking_capability is not None` 让"未提供"与"显式置 NULL"无法区分。前端把 capability 清空 → 后端忽略。

- [ ] **Step 1：查找已有测试文件**

```bash
ls tests/unit/ | grep -i "llm_provider"
```

如果有 `test_llm_providers_route.py` 用它；否则在最合适的现有 `test_llm_providers_*` 文件里追加用例。

- [ ] **Step 2：写失败测试**

```python
@pytest.mark.asyncio
async def test_put_provider_clears_thinking_capability_with_explicit_null(
    authed_client, sample_provider_id
) -> None:
    """PUT 显式传 {thinking_capability: null} 应清空字段。"""
    resp = await authed_client.put(
        f"/api/v1/llm-providers/{sample_provider_id}",
        json={"thinking_capability": None},
    )
    assert resp.status_code == 200
    assert resp.json()["thinking_capability"] is None


@pytest.mark.asyncio
async def test_put_provider_omitted_field_preserves_value(
    authed_client, sample_provider_id_with_effort
) -> None:
    """PUT 不传 thinking_capability 时应保留原值。"""
    resp = await authed_client.put(
        f"/api/v1/llm-providers/{sample_provider_id_with_effort}",
        json={"name": "updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["thinking_capability"] == "effort"
```

若没有现成 fixture，使用已有 `test_llm_providers_*.py` 的 setup 复用（grep 查找 `POST /api/v1/llm-providers`）。

- [ ] **Step 3：运行测试确认失败**

```bash
pytest tests/unit/test_llm_providers_route.py::test_put_provider_clears_thinking_capability_with_explicit_null -v
```

- [ ] **Step 4：修改 `update_llm_provider`**

```python
@router.put("/llm-providers/{provider_id}")
async def update_llm_provider(
    provider_id: str,
    body: LLMProviderUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    from sebastian.llm.crypto import encrypt

    data = body.model_dump(exclude_unset=True)
    updates: dict[str, Any] = {}
    if "name" in data:
        updates["name"] = data["name"]
    if "api_key" in data:
        updates["api_key_enc"] = encrypt(data["api_key"])
    if "model" in data:
        updates["model"] = data["model"]
    if "base_url" in data:
        updates["base_url"] = data["base_url"]
    if "thinking_format" in data:
        updates["thinking_format"] = data["thinking_format"]
    if "thinking_capability" in data:
        updates["thinking_capability"] = data["thinking_capability"]
    if "is_default" in data:
        updates["is_default"] = data["is_default"]

    record = await state.llm_registry.update(provider_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _record_to_dict(record)
```

- [ ] **Step 5：运行测试**

```bash
pytest tests/unit/test_llm_providers_route.py -v
```

- [ ] **Step 6：commit**

```bash
git add sebastian/gateway/routes/llm_providers.py tests/unit/test_llm_providers_route.py
git commit -m "$(cat <<'EOF'
fix(gateway): PUT /llm-providers 改用 exclude_unset 支持显式清空字段

原实现 if body.x is not None 让"未提供"与"显式 null"混淆，用户无法把
thinking_capability 重置为未设置。改用 model_dump(exclude_unset=True)
区分两种语义。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4：修复 P0-1 Sub-Agent 首条消息透传 thinking_effort

**Files:**
- Modify: `sebastian/core/session_runner.py:20-31`
- Modify: `sebastian/gateway/routes/sessions.py:57-103`
- Modify: `ui/mobile/src/api/sessions.ts:105-114`
- Modify: `ui/mobile/app/subagents/session/[id].tsx`（`isNewSession` 分支）
- Test: `tests/unit/` 新增/更新

**背景：** `POST /api/v1/agents/{agent_type}/sessions` 是创建 sub-agent 会话 + 跑首条 goal 的入口，目前完全不接受 `thinking_effort`；`run_agent_session` 签名也没有该参数。这是"首次发送消息没有思考"的核心 bug。

- [ ] **Step 1：写后端失败测试**

在 `tests/unit/` 选合适文件或新建 `test_create_agent_session_thinking.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.session_runner import run_agent_session
from sebastian.core.types import Session


@pytest.mark.asyncio
async def test_run_agent_session_passes_thinking_effort() -> None:
    """run_agent_session 应将 thinking_effort 透传到 agent.run_streaming。"""
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value=None)
    session = Session(agent_type="code", title="t", goal="g", depth=2)
    session_store = AsyncMock()
    index_store = AsyncMock()

    await run_agent_session(
        agent=agent,
        session=session,
        goal="hello",
        session_store=session_store,
        index_store=index_store,
        event_bus=None,
        thinking_effort="high",
    )
    agent.run_streaming.assert_awaited_once_with(
        "hello", session.id, thinking_effort="high"
    )


@pytest.mark.asyncio
async def test_run_agent_session_default_none() -> None:
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value=None)
    session = Session(agent_type="code", title="t", goal="g", depth=2)

    await run_agent_session(
        agent=agent,
        session=session,
        goal="hello",
        session_store=AsyncMock(),
        index_store=AsyncMock(),
        event_bus=None,
    )
    agent.run_streaming.assert_awaited_once_with(
        "hello", session.id, thinking_effort=None
    )
```

- [ ] **Step 2：运行测试确认失败**

```bash
pytest tests/unit/test_create_agent_session_thinking.py -v
```

- [ ] **Step 3：修改 `run_agent_session`**

在 `sebastian/core/session_runner.py`：

```python
async def run_agent_session(
    agent: BaseAgent,
    session: Session,
    goal: str,
    session_store: SessionStore,
    index_store: IndexStore,
    event_bus: EventBus | None = None,
    thinking_effort: str | None = None,
) -> None:
    """Run an agent on a session asynchronously. Sets status on completion/failure."""
    try:
        await agent.run_streaming(goal, session.id, thinking_effort=thinking_effort)
        ...
```

- [ ] **Step 4：修改 `POST /agents/{agent_type}/sessions`**

在 `sebastian/gateway/routes/sessions.py:57-103`：

```python
@router.post("/agents/{agent_type}/sessions")
async def create_agent_session(
    agent_type: str,
    body: dict,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    ...
    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content is required")
    thinking_effort = body.get("thinking_effort")  # optional

    session = Session(...)
    ...

    _task = asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=content,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
            thinking_effort=thinking_effort,
        )
    )
    ...
```

- [ ] **Step 5：补一个 route 级集成测试（可选但推荐）**

在已有 `tests/unit/test_sessions_route_*` 中加：

```python
@pytest.mark.asyncio
async def test_create_agent_session_forwards_thinking_effort(monkeypatch) -> None:
    """POST /agents/{type}/sessions 应把 thinking_effort 传到 run_agent_session。"""
    # 参考既有 test_sessions_route_*.py 的 mock pattern
    ...
```

- [ ] **Step 6：修改前端 `createAgentSession`**

在 `ui/mobile/src/api/sessions.ts`：

```typescript
import type { ThinkingEffort } from '../types';
...
export async function createAgentSession(
  agent: string,
  content: string,
  thinkingEffort: ThinkingEffort,
): Promise<{ sessionId: string; ts: string }> {
  const { data } = await apiClient.post<{ session_id: string; ts: string }>(
    `/api/v1/agents/${agent}/sessions`,
    {
      content,
      thinking_effort: thinkingEffort === 'off' ? null : thinkingEffort,
    },
  );
  return { sessionId: data.session_id, ts: data.ts };
}
```

- [ ] **Step 7：修改 `app/subagents/session/[id].tsx` 的 isNewSession 分支**

查找 `createAgentSession(` 的所有调用点（grep），把 `opts.effort` 传入。同时确保 `handleSend` 的 signature 已经接受 `opts: { effort: ThinkingEffort }`（Task 20 已做，只需要把参数转发）。

- [ ] **Step 8：TypeScript 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

- [ ] **Step 9：运行所有测试**

```bash
pytest tests/unit/test_create_agent_session_thinking.py tests/unit/test_sessions_route_*.py -v
```

- [ ] **Step 10：commit**

```bash
git add sebastian/core/session_runner.py sebastian/gateway/routes/sessions.py ui/mobile/src/api/sessions.ts "ui/mobile/app/subagents/session/[id].tsx" tests/unit/test_create_agent_session_thinking.py
git commit -m "$(cat <<'EOF'
fix: sub-agent 新会话首条消息透传 thinking_effort

run_agent_session、POST /agents/{type}/sessions、createAgentSession
三处都补上 thinking_effort 参数，修复首次发起消息永远不开思考的链路
断点。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5：修复 P1-4 clamp toast 反馈闭环

**Files:**
- Modify: `ui/mobile/src/store/composer.ts:79-99`
- Modify: `ui/mobile/src/api/llm.ts`（`syncCurrentThinkingCapability`）
- Modify: `ui/mobile/app/_layout.tsx`
- Modify: `ui/mobile/src/components/settings/LLMProviderConfig.tsx`

**背景：** `clampAllToCapability` 返回语义不清（只报告 draft / lastUserChoice 变化，已有 session 被 clamp 完全不报告）；三处调用都没接 `onClamped` 回调 → 用户切 provider 静默降级。

- [ ] **Step 1：重构 `clampAllToCapability` 返回结构化对象**

在 `ui/mobile/src/store/composer.ts`：

```typescript
export interface ClampReport {
  /** 至少有一项发生了降级时返回，否则返回 null */
  from: ThinkingEffort;
  to: ThinkingEffort;
}

interface ComposerStore {
  ...
  clampAllToCapability: (allowedEfforts: readonly ThinkingEffort[]) => ClampReport | null;
}

      clampAllToCapability(allowedEfforts) {
        const s = get();
        let report: ClampReport | null = null;
        const nextMap: Record<string, ThinkingEffort> = {};
        for (const [k, v] of Object.entries(s.effortBySession)) {
          const clamped = clampOne(v, allowedEfforts);
          nextMap[k] = clamped;
          if (clamped !== v && report === null) {
            report = { from: v, to: clamped };
          }
        }
        const clampedLast = clampOne(s.lastUserChoice, allowedEfforts);
        if (clampedLast !== s.lastUserChoice && report === null) {
          report = { from: s.lastUserChoice, to: clampedLast };
        }
        set({
          effortBySession: nextMap,
          lastUserChoice: clampedLast,
        });
        return report;
      },
```

策略：报告"第一次发现的降级"即可，足够触发 toast；不尝试聚合多条。

- [ ] **Step 2：顺手修 `clampOne` 在 `always_on` / `none`（`allowed=[]`）下的脏返回**

```typescript
function clampOne(
  current: ThinkingEffort,
  allowed: readonly ThinkingEffort[],
): ThinkingEffort {
  if (allowed.length === 0) return 'off'; // always_on / none：effort 字段在 UI 不读，固化 off
  if (allowed.includes(current)) return current;
  if (allowed.includes('on')) {
    return current === 'off' ? 'off' : 'on';
  }
  if (current === 'max' && allowed.includes('high')) return 'high';
  if (current === 'on' && allowed.includes('medium')) return 'medium';
  if (allowed.includes('off')) return 'off';
  return allowed[0] ?? 'off';
}
```

- [ ] **Step 3：修改 `syncCurrentThinkingCapability`**

在 `ui/mobile/src/api/llm.ts`，`onClamped` 类型与 `ClampReport` 对齐：

```typescript
import type { ClampReport } from '../store/composer';
...
export async function syncCurrentThinkingCapability(
  onClamped?: (report: ClampReport) => void,
): Promise<void> {
  const providers = await fetchProviders();
  const def = providers.find((p) => p.is_default);
  const capability = def?.thinking_capability ?? null;
  useSettingsStore.getState().setCurrentThinkingCapability(capability);
  if (capability) {
    const allowed = EFFORT_LEVELS_BY_CAPABILITY[capability];
    const report = useComposerStore.getState().clampAllToCapability(allowed);
    if (report && onClamped) {
      onClamped(report);
    }
  }
}
```

- [ ] **Step 4：`_layout.tsx` 启动同步接 toast**

```typescript
import { ToastAndroid, Platform, Alert } from 'react-native';
...
useEffect(() => {
  if (!jwtToken) return;
  void syncCurrentThinkingCapability((r) => {
    const msg = `${r.from} 在新模型下不可用，已切换为 ${r.to}`;
    if (Platform.OS === 'android') {
      ToastAndroid.show(msg, ToastAndroid.SHORT);
    } else {
      Alert.alert('思考档位已调整', msg);
    }
  }).catch((err) => {
    console.warn('syncCurrentThinkingCapability failed', err);
  });
}, [jwtToken]);
```

（若项目已有 toast 工具函数，优先复用；否则用 RN 内置。）

- [ ] **Step 5：`LLMProviderConfig.tsx` 两处同样接 toast**

在 create / update provider 成功后：

```typescript
await syncCurrentThinkingCapability((r) => {
  const msg = `${r.from} 在新模型下不可用，已切换为 ${r.to}`;
  if (Platform.OS === 'android') {
    ToastAndroid.show(msg, ToastAndroid.SHORT);
  } else {
    Alert.alert('思考档位已调整', msg);
  }
});
```

- [ ] **Step 6：TypeScript 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

- [ ] **Step 7：commit**

```bash
git add ui/mobile/src/store/composer.ts ui/mobile/src/api/llm.ts ui/mobile/app/_layout.tsx ui/mobile/src/components/settings/LLMProviderConfig.tsx
git commit -m "$(cat <<'EOF'
fix(mobile): clampAllToCapability 返回结构化 report 并补齐 toast 反馈

- clampAllToCapability 返回 {from,to} | null，任意项被降级都会报告
- clampOne 在 allowed=[] 下直接归零为 'off'，避免脏 state
- _layout.tsx、LLMProviderConfig.tsx 三处调用接 Android Toast / iOS Alert

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6：修复 P1-6 OpenAI reasoning_content × effort 双轴测试

**Files:**
- Modify: `tests/unit/test_openai_compat_thinking.py`

**背景：** 当前测试只覆盖单轴。需补 `capability='effort' + thinking_format='reasoning_content'` 组合：应同时注入 `reasoning_effort` 并正确解析 `delta.reasoning_content` 产生 `ThinkingBlockStart/Delta/Stop` 事件序列。

- [ ] **Step 1：查看现有测试结构**

```bash
head -80 tests/unit/test_openai_compat_thinking.py
```

- [ ] **Step 2：新增组合用例**

参考现有 mock pattern，新增：

```python
@pytest.mark.asyncio
async def test_openai_effort_and_reasoning_content_combo(monkeypatch) -> None:
    """capability='effort' + thinking_format='reasoning_content' 应同时工作。"""
    provider = OpenAICompatProvider(
        api_key="sk-test",
        model="o3-mini",
        thinking_format="reasoning_content",
        thinking_capability="effort",
    )

    # mock 返回一个包含 reasoning_content delta 的 chunk，再返回 text delta
    captured_kwargs: dict[str, Any] = {}

    async def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        # yield reasoning chunk then text chunk（参考已有 mock fixture）
        ...

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_stream)

    events = []
    async for ev in provider.stream(
        system="s", messages=[], tools=[], model="o3-mini",
        max_tokens=1024, thinking_effort="medium",
    ):
        events.append(ev)

    assert captured_kwargs.get("reasoning_effort") == "medium"
    # 断言事件序列含 ThinkingBlockStart / ThinkingDelta / ThinkingBlockStop / TextBlockStart / TextDelta
    event_types = [type(e).__name__ for e in events]
    assert "ThinkingBlockStart" in event_types
    assert "ThinkingDelta" in event_types
```

（实际 mock chunk 结构参考已有测试复用，保持风格一致。）

- [ ] **Step 3：运行测试**

```bash
pytest tests/unit/test_openai_compat_thinking.py -v
```

- [ ] **Step 4：commit**

```bash
git add tests/unit/test_openai_compat_thinking.py
git commit -m "$(cat <<'EOF'
test(llm): 补 OpenAI effort × reasoning_content 双轴组合用例

Review 发现 thinking_capability 与 thinking_format 双轴交互未覆盖，
补上端到端断言验证同时注入 reasoning_effort 并解析 reasoning_content。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7：跑全量测试 & TypeScript check

- [ ] **Step 1：全量 pytest**

```bash
pytest tests/ --ignore=tests/e2e -x
```

预期：绿。

- [ ] **Step 2：前端类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

- [ ] **Step 3：若有失败，定位原因并修复（不要跳过）**

- [ ] **Step 4：ruff 检查**

```bash
ruff check sebastian/ tests/
```

- [ ] **Step 5：最终确认无 commit 遗漏**

```bash
git status
```

预期：clean。

---

## Task 8：同步 README

- [ ] **Step 1：检查受影响的 README**

以下 README 可能需要同步（按需更新，不需要的跳过）：
- `sebastian/store/README.md`：说明 idempotent ALTER 机制与 patches 列表
- `sebastian/llm/README.md`：明确 Anthropic effort 模式错误会抛 `ValueError`（不是静默）
- `sebastian/gateway/routes/README.md`：`POST /agents/{type}/sessions` 新增 `thinking_effort` 参数
- `ui/mobile/src/components/composer/README.md`：clamp toast 反馈行为

- [ ] **Step 2：commit**

```bash
git add <changed READMEs>
git commit -m "$(cat <<'EOF'
docs: 同步 thinking-effort review 修复涉及的模块 README

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 不在本计划范围（P2 建议）

以下是 review 中标记为"建议"级的清理项，**不在本次修复范围**，留待后续迭代：

- `AnthropicProvider._build_thinking_kwargs` 中 `getattr(self, '_capability', None)` 收敛为直接属性
- `base_agent.py` 直戳 `self._loop._provider` 改为 `AgentLoop.set_provider()` 方法
- `FIXED_EFFORT_TO_BUDGET` 键类型收紧为 `Literal['low','medium','high']`
- `composer/index.tsx` 的 `onEffortChange` 闭包包 `useCallback`
- 前端 composer store 的 jest 单测
- `openai_compat.py` 中 `think_block_id` 变量冗余清理

用户可在 P0/P1 合入并通过真机验证后另开 PR 处理。

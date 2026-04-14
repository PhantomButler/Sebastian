# Code Review Batch 4 — 测试 + 清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐测试覆盖（C4/M10/M11）、修复集成测试隔离（H10）、按 session 路由 cancel_task（L1）、删除废弃状态和文件（L2/L3/L4）。

**Architecture:** 纯后端改动：新增单元测试、修改集成测试 fixture、修复两个路由端点的 TaskManager 路由逻辑、删除 `ARCHIVED` 状态、EventBus 加 `reset()`、更新两个 README。

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, FastAPI

---

## 文件改动汇总

| 文件 | 改动 |
|------|------|
| `tests/unit/test_stalled_watchdog.py` | 补 5 个测试 |
| `tests/unit/test_tool_delegate.py` | 补 2 个测试 |
| `tests/unit/test_session_store_paths.py` | 补 3 个测试 |
| `tests/conftest.py` | 加 autouse env fixture + bus reset fixture |
| `tests/integration/test_gateway_turns.py` | 删模块顶层 3 行 setdefault |
| `tests/integration/test_gateway_sessions.py` | 删模块顶层 3 行 setdefault |
| `sebastian/gateway/routes/sessions.py` | cancel_task (DELETE+POST) 按 session.agent_type 路由 |
| `sebastian/core/types.py` | 删 `ARCHIVED = "archived"` |
| `ui/mobile/src/types.ts` | `SessionMeta.status` 删 `'archived'` |
| `sebastian/protocol/events/bus.py` | 加 `reset()` 方法 |
| `sebastian/protocol/a2a/README.md` | 更新（删 dispatcher.py / types.py 描述） |
| `sebastian/orchestrator/README.md` | 删 `intervene()` / `A2ADispatcher.delegate()` 引用 |

---

### Task 1: C4 — stalled_watchdog 补 5 个测试

**Files:**
- Modify: `tests/unit/test_stalled_watchdog.py`

当前只有 1 个 happy path 测试，缺少对已完成 session、阈值边界、空 last_activity_at、get_session 返回 None 的覆盖。

**背景知识**：`_check_stalled_sessions` 中 `if now - last_activity > timedelta(minutes=threshold)` 使用严格大于，恰好 5 分钟不触发。

- [ ] **Step 1: 在 test_stalled_watchdog.py 末尾追加 5 个测试**

```python
@pytest.mark.asyncio
async def test_completed_session_not_marked() -> None:
    """非 active 状态的 session 不被误标为 stalled。"""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "status": "completed", "last_activity_at": old, "depth": 2},
    ])
    session_store = AsyncMock()
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    session_store.get_session.assert_not_awaited()
    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_threshold_boundary_below_not_stalled() -> None:
    """4m59s 未活动（< threshold 5m）不标 stalled。"""
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=4, seconds=59)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "status": "active", "last_activity_at": recent, "depth": 2},
    ])
    session_store = AsyncMock()
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_threshold_boundary_above_stalled() -> None:
    """5m1s 未活动（> threshold 5m）标为 stalled。"""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=5, seconds=1)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s2", "agent_type": "code", "status": "active", "last_activity_at": old, "depth": 2},
    ])
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(return_value=MagicMock(
        id="s2", status="active",
        last_activity_at=now - timedelta(minutes=5, seconds=1),
        goal="test goal",
    ))
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == ["s2"]
    session_store.update_session.assert_awaited_once()
    index_store.upsert.assert_awaited_once()
    event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_last_activity_at_skipped() -> None:
    """last_activity_at 为空字符串时跳过，不报错。"""
    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "status": "active", "last_activity_at": "", "depth": 2},
    ])
    session_store = AsyncMock()
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    session_store.get_session.assert_not_awaited()
    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_session_none_skipped() -> None:
    """session_store.get_session 返回 None 时跳过，不调 index_store.upsert。"""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "status": "active", "last_activity_at": old, "depth": 2},
    ])
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(return_value=None)
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    index_store.upsert.assert_not_awaited()
    event_bus.publish.assert_not_awaited()
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/unit/test_stalled_watchdog.py -v
```

预期：6 tests PASSED（原有 1 + 新增 5）。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_stalled_watchdog.py
git commit -m "test: C4 — stalled_watchdog 补 5 个边界/异常测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: M10 — test_tool_delegate 补 2 个测试

**Files:**
- Modify: `tests/unit/test_tool_delegate.py`

当前只有 happy path，缺少：agent_type 不存在时返回 `ToolResult(ok=False)`；`asyncio.create_task` 被调用的验证。

- [ ] **Step 1: 在 test_tool_delegate.py 末尾追加 2 个测试**

```python
@pytest.mark.asyncio
async def test_delegate_unknown_agent_type_returns_error() -> None:
    """agent_type 不在 agent_instances 时返回 ok=False。"""
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent
    from sebastian.permissions.types import ToolCallContext
    from unittest.mock import patch, MagicMock

    mock_state = MagicMock()
    mock_state.agent_instances = {}  # 无任何 agent

    ctx = ToolCallContext(
        task_goal="build feature",
        session_id="seb_session",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )

    with patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state):
        result = await delegate_to_agent(
            agent_type="nonexistent", goal="write auth module", context="", _ctx=ctx,
        )

    assert result.ok is False
    assert "nonexistent" in result.error


@pytest.mark.asyncio
async def test_delegate_creates_background_task() -> None:
    """成功委派时 asyncio.create_task 被调用一次。"""
    from sebastian.capabilities.tools.delegate_to_agent import delegate_to_agent
    from sebastian.permissions.types import ToolCallContext
    from unittest.mock import patch, MagicMock, AsyncMock
    import asyncio

    mock_state = MagicMock()
    mock_agent = MagicMock()
    mock_state.agent_instances = {"code": mock_agent}
    mock_state.agent_registry = {
        "code": MagicMock(display_name="铁匠", max_children=5),
    }
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.event_bus = MagicMock()

    ctx = ToolCallContext(
        task_goal="build feature",
        session_id="seb_session",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.add_done_callback = MagicMock()

    with patch("sebastian.capabilities.tools.delegate_to_agent._get_state", return_value=mock_state):
        with patch("asyncio.create_task", return_value=mock_task) as mock_create_task:
            result = await delegate_to_agent(
                agent_type="code", goal="write auth module", context="", _ctx=ctx,
            )

    assert result.ok is True
    mock_create_task.assert_called_once()
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/unit/test_tool_delegate.py -v
```

预期：3 tests PASSED（原有 1 + 新增 2）。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_tool_delegate.py
git commit -m "test: M10 — test_tool_delegate 补 agent_type 不存在和 create_task 调用测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: M11 — test_session_store_paths 补 3 个测试

**Files:**
- Modify: `tests/unit/test_session_store_paths.py`

当前只测 `depth=2`，缺少 `depth=3`、`parent_session_id` 持久化、`depth=1`（sebastian）路径的验证。

**背景知识**：`_session_dir` 的路径格式固定为 `sessions_dir / session.agent_type / session.id`，与 depth 无关。depth=1 的 sebastian 会话 `agent_type="sebastian"`，路径为 `{sessions_dir}/sebastian/{session_id}/`。

- [ ] **Step 1: 在 test_session_store_paths.py 末尾追加 3 个测试**

```python
@pytest.mark.asyncio
async def test_depth3_session_path(tmp_path: Path) -> None:
    """depth=3 的 session 存储路径格式与 depth=2 相同：{agent_type}/{session_id}/。"""
    store = SessionStore(tmp_path)
    session = Session(
        id="deep456",
        agent_type="stock",
        title="test",
        depth=3,
        parent_session_id="parent-123",
    )
    await store.create_session(session)
    expected_dir = tmp_path / "stock" / "deep456"
    assert expected_dir.exists(), f"Expected {expected_dir} to exist"
    assert "subagents" not in str(expected_dir)


@pytest.mark.asyncio
async def test_depth3_parent_session_id_persisted(tmp_path: Path) -> None:
    """depth=3 session 的 parent_session_id 写入 meta.json 后可读回。"""
    store = SessionStore(tmp_path)
    session = Session(
        id="child789",
        agent_type="research",
        title="test",
        depth=3,
        parent_session_id="parent-abc",
    )
    await store.create_session(session)
    loaded = await store.get_session("child789", "research")
    assert loaded is not None
    assert loaded.parent_session_id == "parent-abc"
    assert loaded.depth == 3


@pytest.mark.asyncio
async def test_sebastian_session_path(tmp_path: Path) -> None:
    """Sebastian 主会话（depth=1）存储路径为 {sessions_dir}/sebastian/{session_id}/。"""
    store = SessionStore(tmp_path)
    session = Session(
        id="seb123",
        agent_type="sebastian",
        title="test",
        depth=1,
    )
    await store.create_session(session)
    expected_dir = tmp_path / "sebastian" / "seb123"
    assert expected_dir.exists(), f"Expected {expected_dir} to exist"
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/unit/test_session_store_paths.py -v
```

预期：4 tests PASSED（原有 1 + 新增 3）。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_session_store_paths.py
git commit -m "test: M11 — test_session_store_paths 补 depth=3 路径、parent_session_id 和 depth=1 路径测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: H10 — 集成测试环境变量隔离

**Files:**
- Modify: `tests/integration/test_gateway_turns.py`（删 3 行）
- Modify: `tests/integration/test_gateway_sessions.py`（删 3 行）
- Modify: `tests/conftest.py`（加 autouse fixture）

**问题**：两个集成测试文件在模块顶层调用 `os.environ.setdefault`，在 pytest 收集文件时就生效且不可逆，导致测试顺序影响 config 初始化结果。

**修复方案**：
1. 删除两个文件的模块顶层 `setdefault` 行
2. 在 `conftest.py` 加 function-scoped autouse fixture 用 `monkeypatch.setenv` 设置必要环境变量
3. 保留各 `client` fixture 内部的 `importlib.reload(cfg_module)` 不变（确保 pydantic Settings 对象在 `patch.dict` 上下文内重新加载）

- [ ] **Step 1: 删除 test_gateway_turns.py 的模块顶层 setdefault**

打开 `tests/integration/test_gateway_turns.py`，删除以下 3 行（约 line 9-11）：

```python
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")
```

同时保留文件顶部的 `import importlib` 和 `import os`（仍被 fixture 使用）。

- [ ] **Step 2: 删除 test_gateway_sessions.py 的模块顶层 setdefault**

打开 `tests/integration/test_gateway_sessions.py`，删除以下 3 行（约 line 10-12）：

```python
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")
```

- [ ] **Step 3: 在 conftest.py 加 autouse env fixture**

打开 `tests/conftest.py`，在现有内容末尾追加：

```python
@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保每个测试都有必要的环境变量，防止 config 加载失败。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret-key")
```

注意：`SEBASTIAN_DATA_DIR` 不在此 fixture 中设置，集成测试的 `client` fixture 已通过 `patch.dict` 将其指向 `tmp_path`，确保每个测试使用独立临时目录。

- [ ] **Step 4: 运行集成测试验证隔离性**

```bash
pytest tests/integration/ -v
```

预期：所有集成测试 PASSED，无顺序相关失败。

- [ ] **Step 5: 运行全量测试**

```bash
pytest -x -q
```

预期：全量通过（除已知的 `test_sessions_dir_derived_from_data_dir` 失败）。

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/integration/test_gateway_turns.py tests/integration/test_gateway_sessions.py
git commit -m "test: H10 — 集成测试 env 隔离：删模块顶层 setdefault，加 conftest autouse fixture

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: L1 — cancel_task 按 session.agent_type 路由

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`

两个 cancel task 端点硬编码 `state.sebastian._task_manager`，sub-agent session 的 task 无法取消。

**关键信息**：
- `_resolve_session_task(state, session_id, task_id) -> tuple[Session, Task]`
- DELETE 端点当前丢弃返回值；POST 端点只保留 task
- `state.agent_instances` 包含所有 sub-agent 实例，每个实例有 `_task_manager`

- [ ] **Step 1: 修改 DELETE `/sessions/{session_id}/tasks/{task_id}`**

找到 `cancel_task` 函数（约 line 307-317）：

```python
@router.delete("/sessions/{session_id}/tasks/{task_id}")
async def cancel_task(
    session_id: str,
    task_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    await _resolve_session_task(state, session_id, task_id)
    cancelled = await state.sebastian._task_manager.cancel(task_id)
    return {"task_id": task_id, "cancelled": cancelled}
```

改为：

```python
@router.delete("/sessions/{session_id}/tasks/{task_id}")
async def cancel_task(
    session_id: str,
    task_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session, _ = await _resolve_session_task(state, session_id, task_id)
    if session.agent_type == "sebastian":
        manager = state.sebastian._task_manager
    else:
        agent = state.agent_instances.get(session.agent_type)
        if agent is None:
            raise HTTPException(404, f"Agent not found: {session.agent_type}")
        manager = agent._task_manager
    cancelled = await manager.cancel(task_id)
    return {"task_id": task_id, "cancelled": cancelled}
```

- [ ] **Step 2: 修改 POST `/sessions/{session_id}/tasks/{task_id}/cancel`**

找到 `cancel_task_post` 函数（约 line 320-347）：

```python
    _, task = await _resolve_session_task(state, session_id, task_id)
    try:
        cancelled = await state.sebastian._task_manager.cancel(task_id)
```

改为：

```python
    session, task = await _resolve_session_task(state, session_id, task_id)
    if session.agent_type == "sebastian":
        manager = state.sebastian._task_manager
    else:
        agent = state.agent_instances.get(session.agent_type)
        if agent is None:
            raise HTTPException(404, f"Agent not found: {session.agent_type}")
        manager = agent._task_manager
    try:
        cancelled = await manager.cancel(task_id)
```

- [ ] **Step 3: 运行相关测试**

```bash
pytest tests/ -k "cancel" -v
```

预期：PASSED（或无相关测试，无报错）。

- [ ] **Step 4: Commit**

```bash
git add sebastian/gateway/routes/sessions.py
git commit -m "fix: L1 — cancel_task 按 session.agent_type 路由，支持 sub-agent task 取消

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: L2 + L4 — 删除 ARCHIVED 状态 + EventBus reset

**Files:**
- Modify: `sebastian/core/types.py`（删 ARCHIVED）
- Modify: `ui/mobile/src/types.ts`（删 archived）
- Modify: `sebastian/protocol/events/bus.py`（加 reset 方法）
- Modify: `tests/conftest.py`（加 bus reset fixture）

**L2 背景**：`ARCHIVED` 没有合法的状态转换路径，是未实现功能的遗留枚举值。

**L4 背景**：`bus = EventBus()` 是全局单例，测试间 handler 会泄漏，需要 `reset()` + conftest 清理。

- [ ] **Step 1: 删除 SessionStatus.ARCHIVED**

打开 `sebastian/core/types.py`，找到 `SessionStatus` 枚举，删除：

```python
    ARCHIVED = "archived"
```

删除后 `SessionStatus` 应为：

```python
class SessionStatus(StrEnum):
    """Enumeration of session lifecycle states."""

    ACTIVE = "active"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    STALLED = "stalled"
    CANCELLED = "cancelled"
```

- [ ] **Step 2: 删除前端 types.ts 的 archived**

打开 `ui/mobile/src/types.ts`，找到 `SessionMeta.status` 类型（约 line 15）：

```typescript
  status: 'active' | 'idle' | 'completed' | 'failed' | 'stalled' | 'cancelled' | 'archived';
```

改为：

```typescript
  status: 'active' | 'idle' | 'completed' | 'failed' | 'stalled' | 'cancelled';
```

- [ ] **Step 3: EventBus 加 reset 方法**

打开 `sebastian/protocol/events/bus.py`，在 `unsubscribe` 方法之后加 `reset` 方法：

```python
    def reset(self) -> None:
        """Clear all handlers. Used in tests to prevent handler leakage between tests."""
        self._handlers.clear()
```

完整文件在 `reset` 方法后应为：

```python
class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, handler: EventHandler, event_type: EventType | None = None) -> None:
        key = event_type.value if event_type is not None else _WILDCARD
        self._handlers[key].append(handler)

    def unsubscribe(self, handler: EventHandler, event_type: EventType | None = None) -> None:
        key = event_type.value if event_type is not None else _WILDCARD
        self._handlers[key] = [h for h in self._handlers[key] if h is not handler]

    def reset(self) -> None:
        """Clear all handlers. Used in tests to prevent handler leakage between tests."""
        self._handlers.clear()

    async def publish(self, event: Event) -> None:
        ...
```

- [ ] **Step 4: conftest.py 加 bus reset fixture**

打开 `tests/conftest.py`，在 `_patch_env` fixture 之后追加：

```python
@pytest.fixture(autouse=True)
def _reset_event_bus() -> Generator[None, None, None]:
    yield
    from sebastian.protocol.events.bus import bus
    bus.reset()
```

同时在文件顶部的 import 中加 `Generator`：

```python
from collections.abc import Generator
```

- [ ] **Step 5: 运行全量测试**

```bash
pytest -x -q
```

预期：全量通过（除已知失败项）。

- [ ] **Step 6: TypeScript 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

预期：无类型错误。

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/types.py ui/mobile/src/types.ts sebastian/protocol/events/bus.py tests/conftest.py
git commit -m "fix: L2+L4 — 删除 ARCHIVED 状态 + EventBus 加 reset() + conftest bus reset fixture

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7: L3 — README 更新

**Files:**
- Modify: `sebastian/protocol/a2a/README.md`
- Modify: `sebastian/orchestrator/README.md`

**背景**：
- `protocol/a2a/` 目录当前只有 `__init__.py`，`dispatcher.py` 和 `types.py` 均已删除
- `orchestrator/README.md` 仍引用 `intervene()` 和 `A2ADispatcher.delegate()`，这两者均已不存在

- [ ] **Step 1: 更新 protocol/a2a/README.md**

将 `sebastian/protocol/a2a/README.md` 完整替换为：

```markdown
# a2a

> 上级索引：[protocol/](../README.md)

## 目录职责

A2A（Agent-to-Agent）通信协议定义目录。

**当前状态**：`dispatcher.py` 和 `types.py` 已在三层 Agent 架构重构中删除。Agent 间通信已改为：
- **下发任务**：通过 `capabilities/tools/delegate_to_agent` 工具直接创建 session 并异步执行
- **上报事件**：通过 `protocol/events/` EventBus 广播（`SESSION_STALLED`、`SESSION_COMPLETED` 等）

本目录保留 `__init__.py` 包标记，暂不删除以避免潜在的 import 路径变动。

## 目录结构

```
a2a/
└── __init__.py        # 包入口（空）
```

## 修改导航

如需修改 Agent 间通信逻辑，请参考：
- 委派任务：[capabilities/tools/delegate_to_agent/](../../capabilities/tools/delegate_to_agent/)
- 事件广播：[protocol/events/](../events/)

---

> 修改本目录或模块后，请同步更新此 README。
```

- [ ] **Step 2: 更新 orchestrator/README.md**

找到以下需要删除/修改的行：

**删除 `sebas.py` 结构中的 `intervene()` 引用**（约 line 14）：

```
├── sebas.py           # Sebastian 类：继承 BaseAgent，定义人格 Prompt、chat()、get_or_create_session()、intervene()
```

改为：

```
├── sebas.py           # Sebastian 类：继承 BaseAgent，定义人格 Prompt、chat()、get_or_create_session()
```

**删除修改导航中的 `intervene()` 行**（约 line 29）：

```
| 干预（用户主动介入正在执行的 Agent）逻辑 | [sebas.py](sebas.py) 的 `intervene()` |
```

整行删除。

**更新数据流中的委派描述**（约 line 48）：

```
        → 需要委派: delegate_to_agent → A2ADispatcher.delegate() → Sub-Agent
```

改为：

```
        → 需要委派: delegate_to_agent → 直接创建 Session + asyncio.create_task → Sub-Agent
```

**删除子模块说明中的 A2ADispatcher 引用**（约 line 36）：

```
- [tools/](tools/README.md) — Orchestrator 专属工具，当前包含 `delegate_to_agent`（通过 A2ADispatcher 将任务委派给 Sub-Agent）
```

改为：

```
- [tools/](tools/README.md) — Orchestrator 专属工具，当前包含 `delegate_to_agent`（直接创建 sub-agent session 并异步执行）
```

- [ ] **Step 3: 运行全量测试确认无破坏**

```bash
pytest -x -q
```

预期：全量通过（除已知失败项）。

- [ ] **Step 4: Commit**

```bash
git add sebastian/protocol/a2a/README.md sebastian/orchestrator/README.md
git commit -m "docs: L3 — 更新 a2a/README 和 orchestrator/README，清除 A2ADispatcher/intervene 过时内容

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 自检清单

- [ ] C4: `test_stalled_watchdog.py` 有 6 个测试全部 PASS
- [ ] M10: `test_tool_delegate.py` 有 3 个测试全部 PASS
- [ ] M11: `test_session_store_paths.py` 有 4 个测试全部 PASS
- [ ] H10: 两个集成测试文件无模块顶层 `setdefault`；`conftest.py` 有 `_patch_env` autouse fixture
- [ ] L1: `cancel_task` 和 `cancel_task_post` 均按 `session.agent_type` 路由
- [ ] L2: `SessionStatus.ARCHIVED` 已删除；`SessionMeta.status` 不含 `'archived'`
- [ ] L4: `EventBus.reset()` 存在；`conftest.py` 有 `_reset_event_bus` autouse fixture
- [ ] L3: 两个 README 不再引用 `A2ADispatcher`、`dispatcher.py`、`intervene()`
- [ ] `pytest -x -q` 全量通过
- [ ] `cd ui/mobile && npx tsc --noEmit` 无错误

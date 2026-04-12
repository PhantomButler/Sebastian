# Code Review Batch 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Batch 2 的 7 个架构 / 中等问题：M8 / H9 / M1+M2 / M3 / M9 / M12（M5 已在 Batch 1 修复）

**Architecture:**
- M8：将 `IndexStore` 从 `base_agent._update_activity` 的运行时 import 改为构造函数注入，消除 core→gateway 反向依赖
- H9：`LLMProviderRegistry.get_provider(agent_type?)` 按 manifest 路由 LLM，同时用注入的 `llm_registry` 替换 `base_agent.run_streaming` 中的运行时 import
- M1+M2：`SessionStore.update_activity` 轻量写 meta.json；`IndexStore.update_activity` 写完 index.json 后同步调 SessionStore，保证重启后状态一致
- M3：`_schedule_session_turn` 任务完成时加 done callback，失败/取消时持久化 session 状态
- M9+M12：`create_agent_session` 保存 task 引用；`_schedule_session_turn` 删去冗余 `agent_name` kwarg

**Tech Stack:** Python 3.12+, asyncio, aiofiles, tomllib, SQLAlchemy async, FastAPI

---

## 文件改动汇总

| 文件 | 任务 | 操作 |
|------|------|------|
| `sebastian/core/base_agent.py` | M8, H9 | 注入 index_store + llm_registry，删运行时 import |
| `sebastian/gateway/app.py` | M8, H9 | `_initialize_agent_instances` 传入 index_store + llm_registry |
| `sebastian/llm/registry.py` | H9 | 加 `get_provider`, `_get_by_type`, `_read_manifest_llm` |
| `sebastian/store/session_store.py` | M2 | 加 `update_activity` 轻量方法 |
| `sebastian/store/index_store.py` | M1 | 注入 session_store，`update_activity` 末尾同步 |
| `sebastian/gateway/routes/sessions.py` | M3, M9, M12 | done callback + 保存 task + 删 agent_name kwarg |

---

## Task 1：M9 + M12 — sessions 路由两处小修

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Test: `tests/unit/test_sessions_route_fixes.py` (新建)

### 当前代码（`create_agent_session`，约第 82-91 行）

```python
asyncio.create_task(
    run_agent_session(
        agent=agent,
        session=session,
        goal=content,
        session_store=state.session_store,
        index_store=state.index_store,
        event_bus=state.event_bus,
    )
)
```

### 当前代码（`_schedule_session_turn`，约第 174-175 行）

```python
task = asyncio.create_task(
    agent.run_streaming(content, session.id, agent_name=session.agent_type)
)
```

- [ ] **Step 1: Write failing tests**

新建 `tests/unit/test_sessions_route_fixes.py`：

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_agent_session_task_has_done_callback() -> None:
    """create_agent_session 的 asyncio.create_task 返回值需绑定 done callback。"""
    from sebastian.gateway.routes.sessions import _log_background_turn_failure

    # 构造一个已完成的 task
    async def noop() -> None:
        pass

    task = asyncio.create_task(noop())
    await task

    # _log_background_turn_failure 是 done callback，对成功 task 不抛出
    _log_background_turn_failure(task)


@pytest.mark.asyncio
async def test_schedule_session_turn_no_agent_name_kwarg() -> None:
    """_schedule_session_turn 调用 agent.run_streaming 时不应传 agent_name kwarg。"""
    from unittest.mock import patch, AsyncMock, MagicMock
    from sebastian.core.types import Session, SessionStatus

    session = MagicMock(spec=Session)
    session.agent_type = "code"
    session.id = "sess-1"
    session.status = SessionStatus.ACTIVE

    mock_agent = MagicMock()
    mock_agent.run_streaming = AsyncMock(return_value="ok")

    mock_state = MagicMock()
    mock_state.agent_instances = {"code": mock_agent}
    mock_state.session_store = AsyncMock()
    mock_state.index_store = AsyncMock()
    mock_state.event_bus = AsyncMock()

    with patch("sebastian.gateway.routes.sessions.asyncio.create_task") as mock_ct:
        mock_ct.return_value = MagicMock()
        import sebastian.gateway.routes.sessions as mod
        with patch.object(mod, "__import__", side_effect=lambda name, *a, **kw: mock_state if name == "sebastian.gateway.state" else __import__(name, *a, **kw)):
            pass  # 通过导入 mock 验证调用签名

    # 直接验证：run_streaming 签名不含 agent_name 的调用不报错
    result = await mock_agent.run_streaming("hello", "sess-1")
    assert result == "ok"
    call_kwargs = mock_agent.run_streaming.call_args
    assert "agent_name" not in (call_kwargs.kwargs if call_kwargs else {})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/test_sessions_route_fixes.py -v
```

Expected: 部分测试 pass（因为目前代码并没有使用 agent_name 参数破坏签名），但这是验收前的基线。

- [ ] **Step 3: Apply M9 fix — save create_task return value**

在 `sebastian/gateway/routes/sessions.py` 的 `create_agent_session` 中，将：

```python
asyncio.create_task(
    run_agent_session(
        agent=agent,
        session=session,
        goal=content,
        session_store=state.session_store,
        index_store=state.index_store,
        event_bus=state.event_bus,
    )
)
```

改为：

```python
_task = asyncio.create_task(
    run_agent_session(
        agent=agent,
        session=session,
        goal=content,
        session_store=state.session_store,
        index_store=state.index_store,
        event_bus=state.event_bus,
    )
)
_task.add_done_callback(_log_background_turn_failure)
```

- [ ] **Step 4: Apply M12 fix — remove agent_name kwarg**

在 `_schedule_session_turn` 中将：

```python
task = asyncio.create_task(
    agent.run_streaming(content, session.id, agent_name=session.agent_type)
)
```

改为：

```python
task = asyncio.create_task(
    agent.run_streaming(content, session.id)
)
```

（`agent.name` 已在 `_initialize_agent_instances` 中设为 `cfg.agent_type`，无需额外传参）

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_sessions_route_fixes.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/sessions.py tests/unit/test_sessions_route_fixes.py
git commit -m "fix: M9+M12 — create_agent_session 保存 task + 删 agent_name 冗余 kwarg"
```

---

## Task 2：M8 — base_agent index_store 注入

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/gateway/app.py`
- Test: `tests/unit/test_base_agent_index_store.py` (新建)

### 当前 `__init__` 签名（第 65-74 行）

```python
def __init__(
    self,
    gate: PolicyGate,
    session_store: SessionStore,
    event_bus: EventBus | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    allowed_skills: list[str] | None = None,
) -> None:
```

### 当前 `_update_activity`（第 408-414 行）

```python
async def _update_activity(self, session_id: str) -> None:
    """Update last_activity_at in index for stalled detection."""
    try:
        import sebastian.gateway.state as _state
        await _state.index_store.update_activity(session_id)
    except (AttributeError, ImportError):
        pass  # state not initialised (tests)
```

- [ ] **Step 1: Write failing test**

新建 `tests/unit/test_base_agent_index_store.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_update_activity_uses_injected_index_store() -> None:
    """_update_activity 应该调用注入的 index_store，不 import gateway.state。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore
    from sebastian.store.index_store import IndexStore

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "test"

    mock_index_store = MagicMock(spec=IndexStore)
    mock_index_store.update_activity = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
        index_store=mock_index_store,
    )

    await agent._update_activity("sess-abc")

    mock_index_store.update_activity.assert_awaited_once_with("sess-abc")


@pytest.mark.asyncio
async def test_update_activity_without_index_store_is_noop() -> None:
    """不注入 index_store 时 _update_activity 静默跳过，不报错。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "test"

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
    )

    # Should not raise
    await agent._update_activity("sess-xyz")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_base_agent_index_store.py -v
```

Expected: FAIL — `BaseAgent.__init__` 不接受 `index_store` 参数

- [ ] **Step 3: Update `BaseAgent.__init__`**

在 `sebastian/core/base_agent.py` 的 `__init__` 签名末尾加 `index_store` 参数，并保存：

```python
def __init__(
    self,
    gate: PolicyGate,
    session_store: SessionStore,
    event_bus: EventBus | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    allowed_skills: list[str] | None = None,
    index_store: IndexStore | None = None,
) -> None:
```

在文件顶部的 `TYPE_CHECKING` 块中加 `IndexStore` 类型引用（已有 `LLMProvider` 的写法）：

```python
if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider
    from sebastian.store.index_store import IndexStore
```

在 `__init__` 方法体中（`self._event_bus = event_bus` 之后）加：

```python
self._index_store = index_store
```

- [ ] **Step 4: Replace `_update_activity`**

将第 408-414 行整块替换为：

```python
async def _update_activity(self, session_id: str) -> None:
    """Update last_activity_at in index for stalled detection."""
    if self._index_store is not None:
        await self._index_store.update_activity(session_id)
```

- [ ] **Step 5: Update `_initialize_agent_instances` in `gateway/app.py`**

函数签名加 `index_store` 参数，并传入构造：

```python
def _initialize_agent_instances(
    agent_configs: list[AgentConfig],
    gate: Any,
    session_store: SessionStore,
    event_bus: EventBus,
    index_store: IndexStore,
) -> dict[str, BaseAgent]:
    """Create a singleton instance for each registered agent type."""
    instances: dict[str, BaseAgent] = {}
    for cfg in agent_configs:
        agent = cfg.agent_class(
            gate=gate,
            session_store=session_store,
            event_bus=event_bus,
            index_store=index_store,
            allowed_tools=cfg.allowed_tools,
            allowed_skills=cfg.allowed_skills,
        )
        agent.name = cfg.agent_type
        instances[cfg.agent_type] = agent
        logger.info("Registered agent instance: %s (%s)", cfg.agent_type, cfg.display_name)
    return instances
```

在 `lifespan` 中找到调用处（`state.agent_instances = _initialize_agent_instances(...)`），加 `index_store=state.index_store`：

```python
state.agent_instances = _initialize_agent_instances(
    agent_configs=agent_configs,
    gate=gate,
    session_store=state.session_store,
    event_bus=state.event_bus,
    index_store=state.index_store,
)
```

同时在 `app.py` 的 `TYPE_CHECKING` 或 import 块中加：

```python
if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore
```

（`IndexStore` 和 `SessionStore` 可能已在 `TYPE_CHECKING` 块中，视文件实际情况添加）

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/test_base_agent_index_store.py tests/unit/test_base_agent.py tests/unit/test_base_agent_provider.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/base_agent.py sebastian/gateway/app.py tests/unit/test_base_agent_index_store.py
git commit -m "fix: M8 — base_agent 注入 index_store，消除 core→gateway 反向依赖"
```

---

## Task 3：M1 + M2 — activity 写入一致性

**Files:**
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/store/index_store.py`
- Modify: `sebastian/gateway/app.py`
- Test: `tests/unit/test_activity_sync.py` (新建)

### 目标

`IndexStore.update_activity` 写完 index.json 后，通过注入的 `SessionStore.update_activity` 同步更新 meta.json，保证重启后两处状态一致。

`SessionStore.update_activity` 只修改 `last_activity_at` 和 `status` 两个字段，不加载/保存完整 Session 对象。

- [ ] **Step 1: Write failing tests**

新建 `tests/unit/test_activity_sync.py`：

```python
from __future__ import annotations

import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime

import pytest


@pytest.mark.asyncio
async def test_session_store_update_activity_writes_meta(tmp_path: Path) -> None:
    """SessionStore.update_activity 只更新 meta.json 中的 last_activity_at + status。"""
    from sebastian.store.session_store import SessionStore
    from sebastian.core.types import Session, SessionStatus

    store = SessionStore(tmp_path)
    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    session.status = SessionStatus.STALLED
    await store.create_session(session)

    await store.update_activity(session.id, "code")

    meta_path = tmp_path / "code" / session.id / "meta.json"
    data = json.loads(meta_path.read_text())
    assert data["status"] == "active"  # stalled → active
    assert data["last_activity_at"] is not None


@pytest.mark.asyncio
async def test_index_store_update_activity_syncs_meta(tmp_path: Path) -> None:
    """IndexStore.update_activity 注入 session_store 后同步写 meta.json。"""
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore
    from sebastian.core.types import Session, SessionStatus

    session_store = SessionStore(tmp_path)
    index_store = IndexStore(tmp_path, session_store=session_store)

    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    session.status = SessionStatus.STALLED
    await session_store.create_session(session)
    await index_store.upsert(session)

    await index_store.update_activity(session.id)

    meta_path = tmp_path / "code" / session.id / "meta.json"
    data = json.loads(meta_path.read_text())
    assert data["status"] == "active"
    assert data["last_activity_at"] is not None


@pytest.mark.asyncio
async def test_index_store_update_activity_without_session_store(tmp_path: Path) -> None:
    """IndexStore.update_activity 不注入 session_store 时仅写 index.json，不报错。"""
    from sebastian.store.index_store import IndexStore
    from sebastian.core.types import Session, SessionStatus

    index_store = IndexStore(tmp_path)  # no session_store

    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    await index_store.upsert(session)

    # Should not raise
    await index_store.update_activity(session.id)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_activity_sync.py -v
```

Expected: FAIL — `SessionStore` 无 `update_activity` 方法；`IndexStore` 不接受 `session_store` 参数

- [ ] **Step 3: Add `SessionStore.update_activity`**

在 `sebastian/store/session_store.py` 的 `update_session` 方法之后插入：

```python
async def update_activity(self, session_id: str, agent_type: str) -> None:
    """Lightweight update: set last_activity_at to now, transition stalled→active in meta.json."""
    async with self._session_lock(session_id, agent_type):
        directory = _session_dir_by_id(self._dir, session_id, agent_type)
        meta_path = directory / "meta.json"
        if not meta_path.exists():
            return
        async with aiofiles.open(meta_path) as f:
            data = json.loads(await f.read())
        data["last_activity_at"] = datetime.now(UTC).isoformat()
        if data.get("status") == "stalled":
            data["status"] = "active"
        await self._atomic_write_text(meta_path, json.dumps(data))
```

- [ ] **Step 4: Update `IndexStore.__init__` to accept `session_store`**

在 `sebastian/store/index_store.py` 中，修改 `IndexStore.__init__`：

在文件顶部的 `TYPE_CHECKING` 导入块（若无则新增）中加：

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sebastian.store.session_store import SessionStore
```

修改 `__init__`：

```python
def __init__(self, sessions_dir: Path, session_store: SessionStore | None = None) -> None:
    self._path = sessions_dir / INDEX_FILE
    resolved = self._path.resolve()
    lock = _LOCKS_BY_PATH.get(resolved)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS_BY_PATH[resolved] = lock
    self._lock = lock
    self._session_store = session_store
```

- [ ] **Step 5: Update `IndexStore.update_activity` to sync meta**

在现有 `update_activity` 方法（第 98-113 行）中，找到 `await self._write(sessions)` 之后（锁外）添加同步调用。

修改后的完整方法：

```python
async def update_activity(self, session_id: str) -> None:
    """Update last_activity_at for a session.

    Also transitions stalled sessions back to active — if a stalled session
    receives a tool call it means it's no longer stuck.
    Syncs the change to meta.json via injected session_store (if present).
    """
    agent_type: str | None = None
    async with self._lock:
        sessions = await self._read()
        now = datetime.now(UTC).isoformat()
        for entry in sessions:
            if entry["id"] == session_id:
                entry["last_activity_at"] = now
                if entry.get("status") == "stalled":
                    entry["status"] = "active"
                agent_type = entry.get("agent_type")
                break
        await self._write(sessions)

    if self._session_store is not None and agent_type is not None:
        await self._session_store.update_activity(session_id, agent_type)
```

- [ ] **Step 6: Pass `session_store` when constructing `IndexStore` in `gateway/app.py`**

在 `lifespan` 中找到：

```python
index_store = IndexStore(settings.sessions_dir)
```

改为（在 `session_store` 已创建之后）：

```python
index_store = IndexStore(settings.sessions_dir, session_store=session_store)
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/test_activity_sync.py tests/unit/test_index_store.py tests/unit/test_index_store_v2.py -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/session_store.py sebastian/store/index_store.py sebastian/gateway/app.py tests/unit/test_activity_sync.py
git commit -m "fix: M1+M2 — IndexStore.update_activity 同步写 meta.json，SessionStore 加轻量 update_activity"
```

---

## Task 4：M3 — `_schedule_session_turn` 失败时持久化状态

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Test: `tests/unit/test_schedule_turn_failure.py` (新建)

### 问题

`_schedule_session_turn` 创建的 `asyncio.Task` 失败时，只通过 `_log_background_turn_failure` 记日志，session 状态永远不更新为 `FAILED`/`CANCELLED`。

### 设计

新增 `_make_turn_done_callback(session, session_store, index_store, event_bus)` 工厂函数，返回的 callback 在任务失败/取消时：
1. 设置 `session.status`
2. 用 `asyncio.create_task` 调 `_persist_session_status` 异步持久化

`_schedule_session_turn` 改为传入 state 的 session_store / index_store / event_bus 并绑定此 callback。

正常完成（`task.exception()` 为 None 且非 cancelled）不修改 status — session 保持 active 等待下一轮输入。

- [ ] **Step 1: Write failing test**

新建 `tests/unit/test_schedule_turn_failure.py`：

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.types import Session, SessionStatus


@pytest.mark.asyncio
async def test_turn_done_callback_sets_failed_on_exception() -> None:
    """done callback 应在任务抛异常时把 session.status 设为 FAILED 并持久化。"""
    from sebastian.gateway.routes.sessions import _make_turn_done_callback

    session = MagicMock(spec=Session)
    session.id = "sess-1"
    session.agent_type = "code"
    session.status = SessionStatus.ACTIVE

    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    cb = _make_turn_done_callback(session, session_store, index_store, event_bus)

    async def fail_task() -> None:
        raise RuntimeError("oops")

    task = asyncio.create_task(fail_task())
    try:
        await task
    except RuntimeError:
        pass

    cb(task)
    # Give the event loop a tick to process the inner create_task
    await asyncio.sleep(0)

    assert session.status == SessionStatus.FAILED


@pytest.mark.asyncio
async def test_turn_done_callback_noop_on_success() -> None:
    """done callback 在任务正常完成时不修改 session status。"""
    from sebastian.gateway.routes.sessions import _make_turn_done_callback

    session = MagicMock(spec=Session)
    session.id = "sess-2"
    session.agent_type = "code"
    session.status = SessionStatus.ACTIVE

    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    cb = _make_turn_done_callback(session, session_store, index_store, event_bus)

    async def ok_task() -> str:
        return "done"

    task = asyncio.create_task(ok_task())
    await task
    cb(task)

    assert session.status == SessionStatus.ACTIVE  # unchanged
    session_store.update_session.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_schedule_turn_failure.py -v
```

Expected: FAIL — `_make_turn_done_callback` 不存在

- [ ] **Step 3: Add helper functions to `sessions.py`**

在 `sebastian/gateway/routes/sessions.py` 中，在 `_log_background_turn_failure` 之后插入：

```python
async def _persist_session_status(
    session: Session,
    session_store: Any,
    index_store: Any,
    event_bus: Any,
) -> None:
    from datetime import UTC, datetime

    from sebastian.protocol.events.types import Event, EventType

    session.updated_at = datetime.now(UTC)
    await session_store.update_session(session)
    await index_store.upsert(session)
    if event_bus is not None:
        from sebastian.core.types import SessionStatus

        event_type = (
            EventType.SESSION_CANCELLED
            if session.status == SessionStatus.CANCELLED
            else EventType.SESSION_FAILED
        )
        await event_bus.publish(
            Event(
                type=event_type,
                data={"session_id": session.id, "agent_type": session.agent_type, "status": session.status.value},
            )
        )


def _make_turn_done_callback(
    session: Session,
    session_store: Any,
    index_store: Any,
    event_bus: Any,
) -> Any:
    from sebastian.core.types import SessionStatus

    def _cb(task: asyncio.Task[object]) -> None:
        if task.cancelled():
            session.status = SessionStatus.CANCELLED
        elif task.exception() is not None:
            session.status = SessionStatus.FAILED
        else:
            return
        asyncio.create_task(
            _persist_session_status(session, session_store, index_store, event_bus)
        )

    return _cb
```

需要在文件头部确保 `Session` 已从 `sebastian.core.types` 导入（已导入）。

- [ ] **Step 4: Update `_schedule_session_turn` to use the callback**

将 `_schedule_session_turn` 改为接收 `state` 并绑定 callback：

```python
async def _schedule_session_turn(
    session: Session,
    content: str,
) -> None:
    """Route a turn to the correct agent instance."""
    import sebastian.gateway.state as state

    if session.agent_type == "sebastian":
        task = asyncio.create_task(
            state.sebastian.run_streaming(content, session.id)
        )
    else:
        agent = state.agent_instances.get(session.agent_type)
        if agent is None:
            raise ValueError(f"No agent instance for type: {session.agent_type}")
        task = asyncio.create_task(
            agent.run_streaming(content, session.id)
        )
    task.add_done_callback(_log_background_turn_failure)
    task.add_done_callback(
        _make_turn_done_callback(session, state.session_store, state.index_store, state.event_bus)
    )
```

（两个 callback 都绑定：`_log_background_turn_failure` 记日志，`_make_turn_done_callback` 持久化状态。成功时两个 callback 都不做写操作。）

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_schedule_turn_failure.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/sessions.py tests/unit/test_schedule_turn_failure.py
git commit -m "fix: M3 — _schedule_session_turn 失败时通过 done callback 持久化 session 状态"
```

---

## Task 5：H9 — per-agent LLM provider 路由

**Files:**
- Modify: `sebastian/llm/registry.py`
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/gateway/app.py`
- Test: `tests/unit/test_llm_provider_routing.py` (新建)

### 设计

`LLMProviderRegistry.get_provider(agent_type?)`:
1. 若 `agent_type` 不为 None，读 `agents/{agent_type}/manifest.toml` 的 `[llm]` 块
2. 若存在 `provider_type` + `model`，查 DB 取该类型首条记录并实例化
3. 否则 fallback 到 `get_default_with_model()`

`BaseAgent.__init__` 新增 `llm_registry` 参数；`run_streaming` 用它替换现有的 gateway.state 运行时 import。

- [ ] **Step 1: Write failing tests**

新建 `tests/unit/test_llm_provider_routing.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_provider_falls_back_to_default_when_no_manifest_llm() -> None:
    """agent_type 的 manifest 无 [llm] 块时，get_provider 返回 default provider。"""
    from sebastian.llm.registry import LLMProviderRegistry

    registry = LLMProviderRegistry(MagicMock())
    mock_provider = MagicMock()
    registry.get_default_with_model = AsyncMock(return_value=(mock_provider, "claude-3-5-sonnet-20241022"))

    with patch("sebastian.llm.registry._read_manifest_llm", return_value=None):
        provider, model = await registry.get_provider("code")

    assert provider is mock_provider
    assert model == "claude-3-5-sonnet-20241022"


@pytest.mark.asyncio
async def test_get_provider_uses_manifest_llm_when_present() -> None:
    """manifest [llm] 有 provider_type + model 时，get_provider 用对应的 DB 记录。"""
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import LLMProviderRecord

    registry = LLMProviderRegistry(MagicMock())
    manifest_llm = {"provider_type": "openai", "model": "gpt-4o"}
    mock_record = MagicMock(spec=LLMProviderRecord)
    mock_record.provider_type = "openai"

    mock_provider = MagicMock()
    registry._instantiate = MagicMock(return_value=mock_provider)
    registry._get_by_type = AsyncMock(return_value=mock_record)

    with patch("sebastian.llm.registry._read_manifest_llm", return_value=manifest_llm):
        provider, model = await registry.get_provider("some_agent")

    assert provider is mock_provider
    assert model == "gpt-4o"
    registry._get_by_type.assert_awaited_once_with("openai")


@pytest.mark.asyncio
async def test_get_provider_without_agent_type_returns_default() -> None:
    """agent_type=None 时，get_provider 直接返回 default。"""
    from sebastian.llm.registry import LLMProviderRegistry

    registry = LLMProviderRegistry(MagicMock())
    mock_provider = MagicMock()
    registry.get_default_with_model = AsyncMock(return_value=(mock_provider, "default-model"))

    provider, model = await registry.get_provider(None)

    assert provider is mock_provider
    assert model == "default-model"


@pytest.mark.asyncio
async def test_base_agent_run_streaming_uses_injected_llm_registry() -> None:
    """run_streaming 通过注入的 llm_registry 获取 provider，不 import gateway.state。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.core.stream_events import (
        TextBlockStart, TextBlockStop, TextDelta, ProviderCallEnd,
    )
    from tests.unit.test_agent_loop import MockLLMProvider
    from unittest.mock import MagicMock, AsyncMock

    mock_provider = MockLLMProvider([
        TextBlockStart(block_id="b0"),
        TextDelta(block_id="b0", delta="hi"),
        TextBlockStop(block_id="b0", text="hi"),
        ProviderCallEnd(stop_reason="end_turn"),
    ])
    mock_registry = MagicMock(spec=LLMProviderRegistry)
    mock_registry.get_provider = AsyncMock(return_value=(mock_provider, "test-model"))

    class TestAgent(BaseAgent):
        name = "code"
        system_prompt = "test"

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    from sebastian.memory.episodic_memory import EpisodicMemory
    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        llm_registry=mock_registry,
    )
    agent._episodic = episodic_mock

    result = await agent.run("hello", session_id="sess-h9")
    assert result == "hi"
    mock_registry.get_provider.assert_awaited_once_with("code")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_llm_provider_routing.py -v
```

Expected: FAIL — `_read_manifest_llm` / `_get_by_type` / `get_provider` 不存在；BaseAgent 不接受 `llm_registry`

- [ ] **Step 3: Add `_read_manifest_llm`, `_get_by_type`, `get_provider` to `registry.py`**

在 `sebastian/llm/registry.py` 的顶部 import 块中加：

```python
import tomllib
from pathlib import Path
```

在 `LLMProviderRegistry` 类的 `get_by_id` 之后、`list_all` 之前插入：

```python
async def get_provider(self, agent_type: str | None = None) -> tuple[LLMProvider, str]:
    """Return (provider, model) for the given agent_type.

    Checks agents/{agent_type}/manifest.toml [llm] section first.
    Falls back to get_default_with_model() if no manifest config or no matching DB record.
    """
    if agent_type is not None:
        manifest_llm = _read_manifest_llm(agent_type)
        if manifest_llm:
            provider_type = manifest_llm.get("provider_type")
            model = manifest_llm.get("model")
            if provider_type and model:
                record = await self._get_by_type(provider_type)
                if record is not None:
                    return self._instantiate(record), model
    return await self.get_default_with_model()

async def _get_by_type(self, provider_type: str) -> LLMProviderRecord | None:
    """Return first DB record matching provider_type."""
    async with self._db_factory() as session:
        result = await session.execute(
            select(LLMProviderRecord)
            .where(LLMProviderRecord.provider_type == provider_type)
            .limit(1)
        )
        return result.scalar_one_or_none()
```

在 **文件末尾**（类定义之外）新增模块级辅助函数：

```python
def _read_manifest_llm(agent_type: str) -> dict | None:
    """Read [llm] section from the agent's manifest.toml, or return None if absent."""
    # Builtin agents live alongside this package: sebastian/agents/{agent_type}/manifest.toml
    agents_dir = Path(__file__).parent.parent / "agents"
    manifest_path = agents_dir / agent_type / "manifest.toml"
    if not manifest_path.exists():
        return None
    with manifest_path.open("rb") as f:
        data = tomllib.load(f)
    return data.get("llm")  # None if no [llm] section
```

- [ ] **Step 4: Update `BaseAgent.__init__` to accept `llm_registry`**

在 `sebastian/core/base_agent.py` 的 `TYPE_CHECKING` 块中加（已有 `IndexStore`）：

```python
if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.index_store import IndexStore
```

在 `__init__` 签名末尾加参数：

```python
def __init__(
    self,
    gate: PolicyGate,
    session_store: SessionStore,
    event_bus: EventBus | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    allowed_skills: list[str] | None = None,
    index_store: IndexStore | None = None,
    llm_registry: LLMProviderRegistry | None = None,
) -> None:
```

在 `self._index_store = index_store` 之后加：

```python
self._llm_registry = llm_registry
```

- [ ] **Step 5: Replace gateway.state runtime import in `run_streaming`**

将当前的 `run_streaming` 中的 runtime import 块（约第 183-193 行）：

```python
if not self._provider_injected:
    try:
        import sebastian.gateway.state as _state

        if not hasattr(_state, "llm_registry"):
            raise AttributeError("llm_registry not initialised")
        provider, model = await _state.llm_registry.get_default_with_model()
        self._loop._provider = provider
        self._loop._model = model
    except AttributeError:
        pass  # state not initialised — keep existing provider
```

替换为：

```python
if not self._provider_injected:
    if self._llm_registry is not None:
        provider, model = await self._llm_registry.get_provider(self.name)
        self._loop._provider = provider
        self._loop._model = model
```

（不再需要 try/except — 注入了 registry 就用，否则静默使用初始 provider。测试中不注入 registry 依然可以用构造时传入的 provider。）

- [ ] **Step 6: Update `_initialize_agent_instances` in `gateway/app.py`**

函数签名再加 `llm_registry` 参数：

```python
def _initialize_agent_instances(
    agent_configs: list[AgentConfig],
    gate: Any,
    session_store: SessionStore,
    event_bus: EventBus,
    index_store: IndexStore,
    llm_registry: LLMProviderRegistry,
) -> dict[str, BaseAgent]:
    instances: dict[str, BaseAgent] = {}
    for cfg in agent_configs:
        agent = cfg.agent_class(
            gate=gate,
            session_store=session_store,
            event_bus=event_bus,
            index_store=index_store,
            llm_registry=llm_registry,
            allowed_tools=cfg.allowed_tools,
            allowed_skills=cfg.allowed_skills,
        )
        agent.name = cfg.agent_type
        instances[cfg.agent_type] = agent
        logger.info("Registered agent instance: %s (%s)", cfg.agent_type, cfg.display_name)
    return instances
```

更新 `lifespan` 中的调用：

```python
state.agent_instances = _initialize_agent_instances(
    agent_configs=agent_configs,
    gate=gate,
    session_store=state.session_store,
    event_bus=state.event_bus,
    index_store=state.index_store,
    llm_registry=llm_registry,
)
```

在 `app.py` 的 `TYPE_CHECKING` 块中加 `LLMProviderRegistry`（如未导入）：

```python
if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/test_llm_provider_routing.py tests/unit/test_llm_registry.py tests/unit/test_base_agent_provider.py -v
```

Expected: PASS

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: 全部 pass（或与 Batch 1 结束时相同的 pre-existing failure 数）

- [ ] **Step 9: Commit**

```bash
git add sebastian/llm/registry.py sebastian/core/base_agent.py sebastian/gateway/app.py tests/unit/test_llm_provider_routing.py
git commit -m "fix: H9 — LLMRegistry.get_provider 按 manifest 路由 + base_agent 注入 llm_registry"
```

---

## 自检清单

完成所有任务后逐项核对：

- [ ] `base_agent._update_activity` 不再有任何 `import sebastian.gateway.state`
- [ ] `base_agent.run_streaming` 不再有任何 `import sebastian.gateway.state`
- [ ] `IndexStore.__init__` 接受可选 `session_store` 参数
- [ ] `IndexStore.update_activity` 在写完 index.json 后调用 `session_store.update_activity`（若注入）
- [ ] `SessionStore` 有 `update_activity(session_id, agent_type)` 轻量方法
- [ ] `_schedule_session_turn` 任务绑定了 `_make_turn_done_callback`
- [ ] `create_agent_session` 的 `asyncio.create_task` 返回值已保存并绑定 callback
- [ ] `_schedule_session_turn` 中无 `agent_name=` kwarg
- [ ] `LLMProviderRegistry.get_provider(agent_type?)` 存在且 fallback 正常
- [ ] 全量测试通过，无新增失败

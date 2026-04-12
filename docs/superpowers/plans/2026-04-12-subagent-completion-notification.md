# Sub-Agent 主动通知与双向通信 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现子代理完成/失败/等待时主动通知 Sebastian，并支持 Sebastian 向 waiting 子代理回复指示的双向通信机制。

**Architecture:** `run_agent_session` 发布携带 `parent_session_id` 的事件，`SSEManager` 路由修复使子代理事件到达客户端，`CompletionNotifier` 订阅这些事件并通过 per-session 队列串行触发父 Agent 的新 LLM turn；`ask_parent` 工具让子代理主动进入 WAITING 状态，`reply_to_agent` 工具让 Sebastian 向 waiting 子代理写入指示并重新启动其 session。

**Tech Stack:** Python 3.12, asyncio, FastAPI, Pydantic, pytest-asyncio

---

## 文件改动总览

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `sebastian/core/types.py` | 新增 `SessionStatus.WAITING` |
| 修改 | `sebastian/protocol/events/types.py` | 新增 `EventType.SESSION_WAITING` |
| 修改 | `sebastian/store/index_store.py` | `upsert` 补 `goal` 字段 |
| 修改 | `sebastian/core/session_runner.py` | 事件加 `parent_session_id`/`goal`；保护 WAITING 状态不被覆盖 |
| 修改 | `sebastian/gateway/sse.py` | 路由支持 `parent_session_id` 匹配 |
| 新增 | `sebastian/gateway/completion_notifier.py` | CompletionNotifier：订阅事件 → 触发父 Agent turn |
| 修改 | `sebastian/gateway/app.py` | 初始化并注册 CompletionNotifier |
| 新增 | `sebastian/capabilities/tools/ask_parent/__init__.py` | 子代理主动暂停工具 |
| 新增 | `sebastian/capabilities/tools/reply_to_agent/__init__.py` | Sebastian 回复 waiting 子代理工具 |
| 修改 | `sebastian/capabilities/README.md` | 更新工具列表 |
| 新增/修改 | `tests/unit/test_*.py` | 各组件单元测试 |

---

## Task 1：数据层 — SessionStatus.WAITING + EventType.SESSION_WAITING

**Files:**
- Modify: `sebastian/core/types.py`
- Modify: `sebastian/protocol/events/types.py`
- Test: `tests/unit/test_types_waiting.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_types_waiting.py
from sebastian.core.types import SessionStatus
from sebastian.protocol.events.types import EventType


def test_session_status_waiting_exists():
    assert SessionStatus.WAITING == "waiting"


def test_session_status_waiting_distinct_from_stalled():
    assert SessionStatus.WAITING != SessionStatus.STALLED


def test_event_type_session_waiting_exists():
    assert EventType.SESSION_WAITING == "session.waiting"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_types_waiting.py -v
```
Expected: `AttributeError: WAITING` 或 `AssertionError`

- [ ] **Step 3: 新增 `SessionStatus.WAITING`**

在 `sebastian/core/types.py` 的 `SessionStatus` 枚举里加一行：

```python
class SessionStatus(StrEnum):
    """Enumeration of session lifecycle states."""

    ACTIVE = "active"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    STALLED = "stalled"
    WAITING = "waiting"    # 子代理主动暂停等待指示（主动）
    CANCELLED = "cancelled"
```

- [ ] **Step 4: 新增 `EventType.SESSION_WAITING`**

在 `sebastian/protocol/events/types.py` 的 Session lifecycle 区段加一行：

```python
    # Session lifecycle (three-tier architecture)
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"
    SESSION_CANCELLED = "session.cancelled"
    SESSION_STALLED = "session.stalled"
    SESSION_WAITING = "session.waiting"    # 新增
```

- [ ] **Step 5: 运行确认通过**

```bash
pytest tests/unit/test_types_waiting.py -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/types.py sebastian/protocol/events/types.py tests/unit/test_types_waiting.py
git commit -m "feat(core): 新增 SessionStatus.WAITING 和 EventType.SESSION_WAITING"
```

---

## Task 2：修复 IndexStore.upsert 缺失 goal 字段

**Files:**
- Modify: `sebastian/store/index_store.py:59-76`
- Test: `tests/unit/test_index_store_goal.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_index_store_goal.py
import asyncio
from pathlib import Path
import pytest
from sebastian.store.index_store import IndexStore
from sebastian.core.types import Session, SessionStatus


@pytest.mark.asyncio
async def test_upsert_stores_goal(tmp_path: Path):
    store = IndexStore(tmp_path)
    session = Session(
        agent_type="code",
        title="写代码",
        goal="重构 auth 模块",
        depth=2,
    )
    await store.upsert(session)
    entries = await store.list_all()
    assert len(entries) == 1
    assert entries[0]["goal"] == "重构 auth 模块"


@pytest.mark.asyncio
async def test_upsert_goal_distinct_from_title(tmp_path: Path):
    store = IndexStore(tmp_path)
    session = Session(
        agent_type="code",
        title="写代码",
        goal="重构 auth 模块，保持接口兼容",
        depth=2,
    )
    await store.upsert(session)
    entries = await store.list_all()
    assert entries[0]["goal"] != entries[0]["title"]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_index_store_goal.py -v
```
Expected: `AssertionError: assert None == '重构 auth 模块'`（`goal` 键不存在）

- [ ] **Step 3: 修改 `IndexStore.upsert`**

在 `sebastian/store/index_store.py` 的 `upsert` 方法里，给 `entry` dict 补 `goal` 字段：

```python
    async def upsert(self, session: Session) -> None:
        async with self._lock:
            sessions = await self._read()
            entry = {
                "id": session.id,
                "agent_type": session.agent_type,
                "title": session.title,
                "goal": session.goal,                            # 补上
                "status": session.status.value,
                "depth": session.depth,
                "parent_session_id": session.parent_session_id,
                "last_activity_at": session.last_activity_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "task_count": session.task_count,
                "active_task_count": session.active_task_count,
            }
            sessions = [existing for existing in sessions if existing["id"] != session.id]
            sessions.insert(0, entry)
            await self._write(sessions)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_index_store_goal.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/index_store.py tests/unit/test_index_store_goal.py
git commit -m "fix(store): IndexStore.upsert 补写 goal 字段"
```

---

## Task 3：session_runner 事件携带 parent_session_id/goal + 保护 WAITING 状态

**Files:**
- Modify: `sebastian/core/session_runner.py`
- Test: `tests/unit/test_session_runner_events.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_session_runner_events.py
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from sebastian.core.session_runner import run_agent_session
from sebastian.core.types import Session, SessionStatus
from sebastian.protocol.events.types import EventType


def _make_session(**kwargs) -> Session:
    defaults = dict(
        agent_type="code",
        title="test",
        goal="目标任务",
        depth=2,
        parent_session_id="seb-session-1",
    )
    defaults.update(kwargs)
    return Session(**defaults)


@pytest.mark.asyncio
async def test_completed_event_carries_parent_session_id_and_goal():
    session = _make_session()
    agent = AsyncMock()
    agent.run_streaming = AsyncMock(return_value="done")
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(agent, session, "目标任务", session_store, index_store, event_bus)

    event_bus.publish.assert_called_once()
    published = event_bus.publish.call_args[0][0]
    assert published.type == EventType.SESSION_COMPLETED
    assert published.data["parent_session_id"] == "seb-session-1"
    assert published.data["goal"] == "目标任务"


@pytest.mark.asyncio
async def test_failed_event_carries_parent_session_id():
    session = _make_session()
    agent = AsyncMock()
    agent.run_streaming = AsyncMock(side_effect=RuntimeError("crash"))
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(agent, session, "目标任务", session_store, index_store, event_bus)

    published = event_bus.publish.call_args[0][0]
    assert published.type == EventType.SESSION_FAILED
    assert published.data["parent_session_id"] == "seb-session-1"


@pytest.mark.asyncio
async def test_waiting_status_not_overwritten_by_completed():
    """ask_parent 将 session 状态设为 WAITING 后，run_agent_session 不应覆盖为 COMPLETED。"""
    session = _make_session()
    agent = AsyncMock()

    async def _set_waiting(*_args, **_kwargs) -> str:
        session.status = SessionStatus.WAITING
        return "waiting"

    agent.run_streaming = AsyncMock(side_effect=_set_waiting)
    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    await run_agent_session(agent, session, "目标任务", session_store, index_store, event_bus)

    assert session.status == SessionStatus.WAITING
    published = event_bus.publish.call_args[0][0]
    # WAITING 状态不发布 SESSION_COMPLETED，而是什么都不发（ask_parent 工具自己发 SESSION_WAITING）
    assert published.type != EventType.SESSION_COMPLETED
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_session_runner_events.py -v
```
Expected: 前两个失败（缺 `parent_session_id`），第三个失败（WAITING 被覆盖）

- [ ] **Step 3: 修改 `session_runner.py`**

完整替换 `run_agent_session` 函数：

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
        # ask_parent 工具会把 session.status 设为 WAITING；此时不覆盖为 COMPLETED
        if session.status != SessionStatus.WAITING:
            session.status = SessionStatus.COMPLETED
    except asyncio.CancelledError:
        session.status = SessionStatus.CANCELLED
        raise  # finally block runs first, then CancelledError propagates
    except Exception:
        logger.exception("Agent session %s failed", session.id)
        session.status = SessionStatus.FAILED
    finally:
        session.updated_at = datetime.now(UTC)
        session.last_activity_at = datetime.now(UTC)
        await session_store.update_session(session)
        await index_store.upsert(session)
        if event_bus is not None and session.status != SessionStatus.WAITING:
            # WAITING 状态由 ask_parent 工具自己发布 SESSION_WAITING 事件，此处跳过
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
                        "parent_session_id": session.parent_session_id,
                        "agent_type": session.agent_type,
                        "goal": session.goal,
                        "status": session.status.value,
                    },
                )
            )
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_session_runner_events.py -v
```
Expected: 3 passed

- [ ] **Step 5: 确认原有测试不受影响**

```bash
pytest tests/ -v -k "session_runner or session_goal"
```
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/session_runner.py tests/unit/test_session_runner_events.py
git commit -m "feat(core): session_runner 事件携带 parent_session_id/goal，保护 WAITING 状态"
```

---

## Task 4：SSE 路由修复 — 支持 parent_session_id 匹配

**Files:**
- Modify: `sebastian/gateway/sse.py:52-61`
- Test: `tests/unit/test_sse_routing.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_sse_routing.py
import asyncio
import pytest
from unittest.mock import AsyncMock
from sebastian.gateway.sse import SSEManager
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType


@pytest.mark.asyncio
async def test_event_routed_to_parent_session_subscriber():
    """订阅 Sebastian session 的客户端应收到子代理的 SESSION_COMPLETED 事件。"""
    bus = EventBus()
    mgr = SSEManager(bus)

    received: list[str] = []

    async def consume():
        async for chunk in mgr.stream(session_id="seb-123"):
            received.append(chunk)
            break  # 收到一条就退出

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # 让 consume 进入等待

    await bus.publish(Event(
        type=EventType.SESSION_COMPLETED,
        data={
            "session_id": "child-456",
            "parent_session_id": "seb-123",
            "agent_type": "code",
            "goal": "重构",
            "status": "completed",
        },
    ))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert "session.completed" in received[0]


@pytest.mark.asyncio
async def test_event_not_routed_to_unrelated_subscriber():
    """不相关 session 的订阅者不应收到其他 parent 的子代理事件。"""
    bus = EventBus()
    mgr = SSEManager(bus)

    received: list[str] = []

    async def consume():
        async for chunk in mgr.stream(session_id="other-999"):
            received.append(chunk)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    await bus.publish(Event(
        type=EventType.SESSION_COMPLETED,
        data={
            "session_id": "child-456",
            "parent_session_id": "seb-123",
            "agent_type": "code",
            "goal": "重构",
            "status": "completed",
        },
    ))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 0
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_sse_routing.py -v
```
Expected: `test_event_routed_to_parent_session_subscriber` FAILED（事件被丢弃）

- [ ] **Step 3: 修改 `SSEManager._on_event`**

在 `sebastian/gateway/sse.py` 的 `_on_event` 方法里替换过滤逻辑：

```python
    async def _on_event(self, event: Event) -> None:
        async with self._lock:
            buffered_event = _BufferedEvent(self._next_event_id, event)
            self._next_event_id += 1
            self._buffer.append(buffered_event)
            logger.debug(
                "sse_event id=%d type=%s session=%s",
                buffered_event.event_id,
                buffered_event.event.type.value,
                buffered_event.event.data.get("session_id", "-"),
            )
            subscriptions = list(self._queues)

        for subscription in subscriptions:
            if subscription.session_id is not None:
                event_session_id = event.data.get("session_id")
                event_parent_id = event.data.get("parent_session_id")
                if subscription.session_id not in (event_session_id, event_parent_id):
                    continue
            try:
                subscription.queue.put_nowait(buffered_event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event %s", event.type)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_sse_routing.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/sse.py tests/unit/test_sse_routing.py
git commit -m "fix(gateway): SSE 路由支持 parent_session_id 匹配，子代理事件可达父会话订阅者"
```

---

## Task 5：CompletionNotifier

**Files:**
- Create: `sebastian/gateway/completion_notifier.py`
- Modify: `sebastian/gateway/app.py`
- Test: `tests/unit/test_completion_notifier.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_completion_notifier.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sebastian.gateway.completion_notifier import CompletionNotifier
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType


def _make_notifier(parent_agent=None, last_message="任务已完成，所有文件已修改"):
    bus = EventBus()
    session_store = AsyncMock()
    index_store = AsyncMock()

    # index_store.list_all 返回包含 parent session 条目的列表
    index_store.list_all = AsyncMock(return_value=[
        {
            "id": "seb-123",
            "agent_type": "sebastian",
            "depth": 1,
            "status": "active",
            "goal": "管理任务",
        }
    ])

    # session_store.get_messages 返回子代理对话历史
    session_store.get_messages = AsyncMock(return_value=[
        {"role": "user", "content": "重构 auth", "ts": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": last_message, "ts": "2026-01-01T00:01:00"},
    ])

    sebastian = parent_agent or AsyncMock()
    sebastian.run_streaming = AsyncMock(return_value="ok")

    notifier = CompletionNotifier(
        event_bus=bus,
        session_store=session_store,
        index_store=index_store,
        sebastian=sebastian,
        agent_instances={},
        agent_registry={},
    )
    return notifier, bus, sebastian


@pytest.mark.asyncio
async def test_completed_event_triggers_sebastian_turn():
    notifier, bus, sebastian = _make_notifier()

    await bus.publish(Event(
        type=EventType.SESSION_COMPLETED,
        data={
            "session_id": "child-456",
            "parent_session_id": "seb-123",
            "agent_type": "code",
            "goal": "重构 auth 模块",
            "status": "completed",
        },
    ))

    await asyncio.sleep(0.1)  # 等 worker 处理
    notifier.cancel()

    sebastian.run_streaming.assert_called_once()
    call_args = sebastian.run_streaming.call_args
    notification = call_args[0][0]
    session_id_arg = call_args[0][1]

    assert "已完成" in notification
    assert "重构 auth 模块" in notification
    assert "任务已完成，所有文件已修改" in notification
    assert session_id_arg == "seb-123"


@pytest.mark.asyncio
async def test_failed_event_triggers_sebastian_turn():
    notifier, bus, sebastian = _make_notifier(last_message="执行失败，无法找到配置文件")

    await bus.publish(Event(
        type=EventType.SESSION_FAILED,
        data={
            "session_id": "child-456",
            "parent_session_id": "seb-123",
            "agent_type": "code",
            "goal": "重构 auth 模块",
            "status": "failed",
        },
    ))

    await asyncio.sleep(0.1)
    notifier.cancel()

    notification = sebastian.run_streaming.call_args[0][0]
    assert "失败" in notification
    assert "执行失败，无法找到配置文件" in notification


@pytest.mark.asyncio
async def test_waiting_event_triggers_sebastian_turn_with_question():
    notifier, bus, sebastian = _make_notifier()

    await bus.publish(Event(
        type=EventType.SESSION_WAITING,
        data={
            "session_id": "child-456",
            "parent_session_id": "seb-123",
            "agent_type": "code",
            "goal": "重构 auth 模块",
            "question": "config.yaml 文件要覆盖吗？",
        },
    ))

    await asyncio.sleep(0.1)
    notifier.cancel()

    notification = sebastian.run_streaming.call_args[0][0]
    assert "config.yaml 文件要覆盖吗？" in notification
    assert "reply_to_agent" in notification


@pytest.mark.asyncio
async def test_no_parent_session_id_is_ignored():
    notifier, bus, sebastian = _make_notifier()

    await bus.publish(Event(
        type=EventType.SESSION_COMPLETED,
        data={"session_id": "orphan-789", "agent_type": "code", "goal": "x", "status": "completed"},
    ))

    await asyncio.sleep(0.1)
    notifier.cancel()

    sebastian.run_streaming.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_events_serialized_for_same_parent():
    """同一父 session 的多个通知应串行处理，不并发。"""
    call_order: list[int] = []
    call_count = 0

    async def fake_run_streaming(msg, session_id, **kwargs):
        nonlocal call_count
        call_count += 1
        order = call_count
        await asyncio.sleep(0.05)
        call_order.append(order)
        return "ok"

    sebastian = AsyncMock()
    sebastian.run_streaming = fake_run_streaming

    notifier, bus, _ = _make_notifier(parent_agent=sebastian)

    for _ in range(3):
        await bus.publish(Event(
            type=EventType.SESSION_COMPLETED,
            data={
                "session_id": "child-x",
                "parent_session_id": "seb-123",
                "agent_type": "code",
                "goal": "任务",
                "status": "completed",
            },
        ))

    await asyncio.sleep(0.5)
    notifier.cancel()

    assert call_order == [1, 2, 3]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_completion_notifier.py -v
```
Expected: `ImportError: cannot import name 'CompletionNotifier'`

- [ ] **Step 3: 实现 `CompletionNotifier`**

创建 `sebastian/gateway/completion_notifier.py`：

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

_MAX_REPORT_CHARS = 500


class CompletionNotifier:
    """订阅子代理 session 生命周期事件，触发父 Agent（Sebastian 或 Leader）的新 LLM turn。"""

    def __init__(
        self,
        event_bus: EventBus,
        session_store: SessionStore,
        index_store: IndexStore,
        sebastian: Sebastian,
        agent_instances: dict[str, BaseAgent],
        agent_registry: dict[str, AgentConfig],
    ) -> None:
        self._session_store = session_store
        self._index_store = index_store
        self._sebastian = sebastian
        self._agent_instances = agent_instances
        self._agent_registry = agent_registry
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        event_bus.subscribe(self._on_session_event, EventType.SESSION_COMPLETED)
        event_bus.subscribe(self._on_session_event, EventType.SESSION_FAILED)
        event_bus.subscribe(self._on_session_event, EventType.SESSION_WAITING)

    async def _on_session_event(self, event: Event) -> None:
        parent_session_id = event.data.get("parent_session_id")
        if not parent_session_id:
            return
        if parent_session_id not in self._queues:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._queues[parent_session_id] = queue
            self._workers[parent_session_id] = asyncio.create_task(
                self._worker(parent_session_id, queue),
                name=f"completion_notifier_{parent_session_id}",
            )
        item = {"event_type": event.type, "data": event.data}
        await self._queues[parent_session_id].put(item)

    async def _worker(
        self, parent_session_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        while True:
            try:
                item = await queue.get()
                await self._process(parent_session_id, item["event_type"], item["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "CompletionNotifier error for parent session %s", parent_session_id
                )

    async def _process(
        self,
        parent_session_id: str,
        event_type: EventType,
        data: dict[str, Any],
    ) -> None:
        parent_agent = await self._find_parent_agent(parent_session_id)
        if parent_agent is None:
            logger.warning("CompletionNotifier: parent agent not found for %s", parent_session_id)
            return

        notification = await self._build_notification(event_type, data)
        if notification is None:
            return

        try:
            await parent_agent.run_streaming(notification, parent_session_id)
        except Exception:
            logger.exception(
                "CompletionNotifier: run_streaming failed for parent %s", parent_session_id
            )

    async def _find_parent_agent(self, parent_session_id: str) -> BaseAgent | None:
        all_sessions = await self._index_store.list_all()
        parent_entry = next(
            (s for s in all_sessions if s.get("id") == parent_session_id), None
        )
        if parent_entry is None:
            return None
        agent_type = parent_entry.get("agent_type", "")
        if agent_type == "sebastian":
            return self._sebastian  # type: ignore[return-value]
        return self._agent_instances.get(agent_type)

    async def _build_notification(
        self, event_type: EventType, data: dict[str, Any]
    ) -> str | None:
        session_id = data.get("session_id", "")
        agent_type = data.get("agent_type", "")
        goal = data.get("goal", "未知目标")

        config = self._agent_registry.get(agent_type)
        display_name = config.display_name if config else agent_type

        if event_type == EventType.SESSION_WAITING:
            question = data.get("question", "（未提供问题内容）")
            return (
                f"[内部通知] 子代理 {display_name} 遇到问题，需要你的指示\n"
                f"目标：{goal}\n"
                f"问题：{question}\n"
                f"session_id：{session_id}（回复请使用 reply_to_agent 工具）"
            )

        # COMPLETED / FAILED
        last_report = await self._get_last_assistant_message(session_id, agent_type)
        status_label = "完成" if event_type == EventType.SESSION_COMPLETED else "失败"
        return (
            f"[内部通知] 子代理 {display_name} 已{status_label}任务\n"
            f"目标：{goal}\n"
            f"状态：{data.get('status', '')}\n"
            f"汇报：{last_report}\n"
            f"session_id：{session_id}（可用 inspect_session 查看详情）"
        )

    async def _get_last_assistant_message(
        self, session_id: str, agent_type: str
    ) -> str:
        messages = await self._session_store.get_messages(
            session_id, agent_type, limit=10
        )
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                content: str = msg["content"]
                if len(content) > _MAX_REPORT_CHARS:
                    content = content[:_MAX_REPORT_CHARS] + "…（已截断）"
                return content
        return "（无汇报内容）"

    def cancel(self) -> None:
        """关闭所有 worker task，供 gateway shutdown 时调用。"""
        for task in self._workers.values():
            task.cancel()
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_completion_notifier.py -v
```
Expected: 5 passed

- [ ] **Step 5: 在 `gateway/app.py` 初始化 CompletionNotifier**

在 `lifespan` 函数里，`watchdog_task = start_watchdog(...)` 那行**之后**加入：

```python
    from sebastian.gateway.completion_notifier import CompletionNotifier

    completion_notifier = CompletionNotifier(
        event_bus=state.event_bus,
        session_store=state.session_store,
        index_store=state.index_store,
        sebastian=state.sebastian,
        agent_instances=state.agent_instances,
        agent_registry=state.agent_registry,
    )
```

在 `yield` 之后（shutdown 阶段）加上：

```python
    watchdog_task.cancel()
    completion_notifier.cancel()     # 新增
    logger.info("Sebastian gateway shutdown")
```

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/completion_notifier.py sebastian/gateway/app.py tests/unit/test_completion_notifier.py
git commit -m "feat(gateway): CompletionNotifier — 子代理事件触发父 Agent 主动汇报"
```

---

## Task 6：ask_parent 工具

**Files:**
- Create: `sebastian/capabilities/tools/ask_parent/__init__.py`
- Test: `tests/unit/test_tool_ask_parent.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tool_ask_parent.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sebastian.core.tool_context import _current_tool_ctx
from sebastian.permissions.types import ToolCallContext
from sebastian.core.types import SessionStatus
from sebastian.protocol.events.types import EventType


def _make_mock_state(session_status=SessionStatus.ACTIVE):
    state = MagicMock()
    state.index_store = AsyncMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()

    mock_session = MagicMock()
    mock_session.status = session_status
    mock_session.goal = "重构 auth"
    mock_session.parent_session_id = "seb-123"
    mock_session.agent_type = "code"
    state.session_store.get_session = AsyncMock(return_value=mock_session)

    return state, mock_session


@pytest.mark.asyncio
async def test_ask_parent_sets_waiting_status():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    state, mock_session = _make_mock_state()
    ctx = ToolCallContext(
        task_goal="重构",
        session_id="child-456",
        task_id=None,
        agent_type="code",
        depth=2,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.ask_parent._get_state", return_value=state):
            result = await ask_parent(question="config.yaml 要覆盖吗？")
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is True
    assert mock_session.status == SessionStatus.WAITING
    state.session_store.update_session.assert_awaited_once()
    state.index_store.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_ask_parent_publishes_session_waiting_event():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    state, mock_session = _make_mock_state()
    ctx = ToolCallContext(
        task_goal="重构",
        session_id="child-456",
        task_id=None,
        agent_type="code",
        depth=2,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.ask_parent._get_state", return_value=state):
            await ask_parent(question="config.yaml 要覆盖吗？")
    finally:
        _current_tool_ctx.reset(token)

    state.event_bus.publish.assert_awaited_once()
    published = state.event_bus.publish.call_args[0][0]
    assert published.type == EventType.SESSION_WAITING
    assert published.data["question"] == "config.yaml 要覆盖吗？"
    assert published.data["parent_session_id"] == "seb-123"
    assert published.data["session_id"] == "child-456"


@pytest.mark.asyncio
async def test_ask_parent_blocked_for_sebastian():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    ctx = ToolCallContext(
        task_goal="总任务",
        session_id="seb-123",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        result = await ask_parent(question="这样做对吗？")
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is False
    assert "上级" in result.error


@pytest.mark.asyncio
async def test_ask_parent_output_instructs_to_wait():
    from sebastian.capabilities.tools.ask_parent import ask_parent

    state, _ = _make_mock_state()
    ctx = ToolCallContext(
        task_goal="重构",
        session_id="child-456",
        task_id=None,
        agent_type="code",
        depth=2,
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.ask_parent._get_state", return_value=state):
            result = await ask_parent(question="继续吗？")
    finally:
        _current_tool_ctx.reset(token)

    assert "等待" in result.output
    assert "继续" in result.output
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_tool_ask_parent.py -v
```
Expected: `ImportError: cannot import name 'ask_parent'`

- [ ] **Step 3: 实现 `ask_parent` 工具**

创建 `sebastian/capabilities/tools/ask_parent/__init__.py`：

```python
from __future__ import annotations

from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.protocol.events.types import Event, EventType


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="ask_parent",
    description=(
        "遇到无法自行决定的问题时，暂停当前任务并向上级请求指示。"
        "上级回复前请勿继续执行任何操作。"
    ),
    permission_tier=PermissionTier.LOW,
)
async def ask_parent(question: str) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")
    if ctx.depth == 1:
        return ToolResult(ok=False, error="Sebastian 没有上级，无法调用此工具")

    state = _get_state()

    session = await state.session_store.get_session(ctx.session_id, ctx.agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"找不到 session: {ctx.session_id}")

    session.status = SessionStatus.WAITING
    await state.session_store.update_session(session)
    await state.index_store.upsert(session)

    await state.event_bus.publish(
        Event(
            type=EventType.SESSION_WAITING,
            data={
                "session_id": ctx.session_id,
                "parent_session_id": session.parent_session_id,
                "agent_type": ctx.agent_type,
                "goal": session.goal,
                "question": question,
            },
        )
    )

    return ToolResult(
        ok=True,
        output="已向上级请求指示，请等待回复后继续。请不要继续执行任何操作。",
    )
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_tool_ask_parent.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/ask_parent/__init__.py tests/unit/test_tool_ask_parent.py
git commit -m "feat(tools): ask_parent — 子代理主动暂停并向上级请求指示"
```

---

## Task 7：reply_to_agent 工具

**Files:**
- Create: `sebastian/capabilities/tools/reply_to_agent/__init__.py`
- Test: `tests/unit/test_tool_reply_to_agent.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tool_reply_to_agent.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sebastian.core.types import Session, SessionStatus


def _make_waiting_session() -> Session:
    s = Session(agent_type="code", title="重构", goal="重构 auth", depth=2,
                parent_session_id="seb-123")
    s.status = SessionStatus.WAITING
    return s


def _make_mock_state(session: Session):
    state = MagicMock()
    state.index_store = AsyncMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()
    state.session_store.get_session = AsyncMock(return_value=session)
    state.index_store.list_all = AsyncMock(return_value=[
        {
            "id": session.id,
            "agent_type": session.agent_type,
            "status": session.status.value,   # 跟随 session 对象的实际状态
            "depth": 2,
        }
    ])

    mock_agent = AsyncMock()
    state.agent_instances = {"code": mock_agent}

    return state, mock_agent


@pytest.mark.asyncio
async def test_reply_to_agent_appends_message_and_restarts():
    from sebastian.capabilities.tools.reply_to_agent import reply_to_agent

    session = _make_waiting_session()
    state, mock_agent = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.reply_to_agent._get_state", return_value=state):
        result = await reply_to_agent(
            session_id=session.id,
            instruction="可以覆盖，继续执行",
        )

    assert result.ok is True
    state.session_store.append_message.assert_awaited_once_with(
        session.id,
        role="user",
        content="可以覆盖，继续执行",
        agent_type=session.agent_type,
    )
    # run_agent_session 通过 asyncio.create_task 调用，等一下让 task 完成
    import asyncio
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_reply_to_agent_rejects_non_waiting_session():
    from sebastian.capabilities.tools.reply_to_agent import reply_to_agent

    session = _make_waiting_session()
    session.status = SessionStatus.ACTIVE  # 不是 WAITING
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.reply_to_agent._get_state", return_value=state):
        result = await reply_to_agent(session_id=session.id, instruction="继续")

    assert result.ok is False
    assert "waiting" in result.error.lower() or "等待" in result.error


@pytest.mark.asyncio
async def test_reply_to_agent_rejects_unknown_session():
    from sebastian.capabilities.tools.reply_to_agent import reply_to_agent

    state = MagicMock()
    state.index_store = AsyncMock()
    state.index_store.list_all = AsyncMock(return_value=[])

    with patch("sebastian.capabilities.tools.reply_to_agent._get_state", return_value=state):
        result = await reply_to_agent(session_id="nonexistent", instruction="继续")

    assert result.ok is False
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_tool_reply_to_agent.py -v
```
Expected: `ImportError: cannot import name 'reply_to_agent'`

- [ ] **Step 3: 实现 `reply_to_agent` 工具**

创建 `sebastian/capabilities/tools/reply_to_agent/__init__.py`：

```python
from __future__ import annotations

import asyncio
import logging
from types import ModuleType
from typing import Any

from sebastian.core.tool import tool
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)


def _log_task_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("reply_to_agent: background session failed", exc_info=exc)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="reply_to_agent",
    description="向等待指示的子代理发送回复，恢复其任务执行。",
    permission_tier=PermissionTier.LOW,
)
async def reply_to_agent(session_id: str, instruction: str) -> ToolResult:
    state = _get_state()

    # 从 index_store 找到该 session 的基本信息
    all_sessions = await state.index_store.list_all()
    index_entry = next((s for s in all_sessions if s.get("id") == session_id), None)
    if index_entry is None:
        return ToolResult(ok=False, error=f"找不到 session: {session_id}")

    if index_entry.get("status") != SessionStatus.WAITING:
        return ToolResult(
            ok=False,
            error=f"session {session_id} 当前状态为 {index_entry.get('status')}，不在等待状态",
        )

    agent_type: str = index_entry.get("agent_type", "")
    session = await state.session_store.get_session(session_id, agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"找不到 session 数据: {session_id}")

    # 将指示写入子代理的对话历史
    await state.session_store.append_message(
        session_id,
        role="user",
        content=instruction,
        agent_type=agent_type,
    )

    # 找到对应 agent 实例
    agent = state.agent_instances.get(agent_type)
    if agent is None:
        return ToolResult(ok=False, error=f"Agent {agent_type} 未初始化")

    # 恢复 session 状态并重新启动
    session.status = SessionStatus.ACTIVE
    await state.session_store.update_session(session)
    await state.index_store.upsert(session)

    from sebastian.core.session_runner import run_agent_session

    task = asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=session.goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )
    task.add_done_callback(_log_task_failure)

    return ToolResult(ok=True, output=f"已向子代理发送指示，任务已恢复执行。")
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_tool_reply_to_agent.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/reply_to_agent/__init__.py tests/unit/test_tool_reply_to_agent.py
git commit -m "feat(tools): reply_to_agent — Sebastian 向 waiting 子代理发指示并恢复执行"
```

---

## Task 8：更新 capabilities/README.md

**Files:**
- Modify: `sebastian/capabilities/README.md`

- [ ] **Step 1: 读取当前 README**

```bash
cat sebastian/capabilities/README.md
```

- [ ] **Step 2: 在工具列表中加入两个新工具**

在 `capabilities/README.md` 的工具目录树中，在现有工具条目下补充：

```
│   ├── ask_parent/       # 子代理主动暂停并向上级请求指示
│   ├── reply_to_agent/   # Sebastian 向 waiting 子代理发指示并恢复执行
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/capabilities/README.md
git commit -m "docs(capabilities): 更新 README，记录 ask_parent 和 reply_to_agent 工具"
```

---

## Task 9：全量测试验证

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/ -v
```
Expected: 所有已有测试继续通过，新增测试全部通过

- [ ] **Step 2: 运行 lint + type check**

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
mypy sebastian/
```
Expected: 无新错误

---

## 自检结论

| Spec 需求 | 对应 Task |
|-----------|-----------|
| `SessionStatus.WAITING` | Task 1 |
| `EventType.SESSION_WAITING` | Task 1 |
| `IndexStore.upsert` 补 `goal` | Task 2 |
| 事件携带 `parent_session_id` / `goal` | Task 3 |
| WAITING 状态不被覆盖 | Task 3 |
| SSE 路由支持 `parent_session_id` | Task 4 |
| CompletionNotifier 主体逻辑 | Task 5 |
| CompletionNotifier 在 app.py 初始化 | Task 5 |
| `ask_parent` 工具 | Task 6 |
| `reply_to_agent` 工具 | Task 7 |
| capabilities README 更新 | Task 8 |

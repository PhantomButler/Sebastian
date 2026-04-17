# Sub-Agent stop/resume 工具实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sebastian 与组长补上 `stop_agent` 工具，并将现有 `reply_to_agent` 重命名并扩展为 `resume_agent`，使得已委派的 sub-agent session 可被主动暂停到 `IDLE` 并可恢复。

**Architecture:** 复用现有 `SessionStatus` 状态机（ACTIVE→IDLE、IDLE/WAITING→ACTIVE），在 `BaseAgent` cancel 机制里引入 "cancel vs stop" 两种意图以决定终态（CANCELLED vs IDLE）。两个新/改工具接受 `(agent_type, session_id, ...)` 签名，做 agent_type 交叉校验。工具注册通过 `_loader.py` 的 `_SUBAGENT_PROTOCOL_TOOLS` 自动追加到组长，并在 `sebas.py` 的 `allowed_tools` 手动声明。事件总线新增 `SESSION_PAUSED` / `SESSION_RESUMED` 两个 lifecycle 事件，消费方目前仅日志。

**Tech Stack:** Python 3.12+、pytest + pytest-asyncio（单测）、Kotlin + Jetpack Compose（Android 客户端）、JUnit4（Android 单测）。

> **Spec 参考**：`docs/superpowers/specs/2026-04-15-agent-stop-resume-design.md`
> **MCP 使用规范**：处理 Python 文件时优先用 JetBrains PyCharm MCP；处理 Kotlin 文件时优先用 Android Studio MCP（`android-studio-index`）。仅在 MCP 未连接或能力不够时退回本地 Grep/Glob/Read。

---

## Task 1: 新增 SESSION_PAUSED / SESSION_RESUMED 事件类型

**Files:**
- Modify: `sebastian/protocol/events/types.py`

- [ ] **Step 1: 阅读现状**

Read `sebastian/protocol/events/types.py`，确认 Session lifecycle 区段当前长这样：

```python
# Session lifecycle (three-tier architecture)
SESSION_COMPLETED = "session.completed"
SESSION_FAILED = "session.failed"
SESSION_CANCELLED = "session.cancelled"
SESSION_STALLED = "session.stalled"
SESSION_WAITING = "session.waiting"
```

- [ ] **Step 2: 加两行事件类型**

在 `SESSION_WAITING` 之后追加两行：

```python
SESSION_PAUSED = "session.paused"       # stop_agent 触发
SESSION_RESUMED = "session.resumed"     # resume_agent 触发
```

- [ ] **Step 3: 本地验证枚举可 import**

运行：

```bash
python -c "from sebastian.protocol.events.types import EventType; print(EventType.SESSION_PAUSED, EventType.SESSION_RESUMED)"
```

期望输出：`session.paused session.resumed`

- [ ] **Step 4: 运行单测套件确保无回归**

```bash
pytest tests/unit/ -q
```

期望：现有测试全绿（这步只加枚举，不应破坏任何 existing test）。

- [ ] **Step 5: 提交**

```bash
git add sebastian/protocol/events/types.py
git commit -m "feat(events): 新增 SESSION_PAUSED / SESSION_RESUMED 事件类型

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: BaseAgent 的 cancel 意图支持（set → dict）

**Files:**
- Modify: `sebastian/core/base_agent.py`（约 L119-120、L335-336、L543、L581-595）
- Test: `tests/unit/core/test_base_agent_cancel_intent.py` (新建)

背景：现有 `cancel_session` 之后 session 终态被固定为 `CANCELLED`。`stop_agent` 要求同样的 cancel 动作但终态推进到 `IDLE`。做法是把 `_cancel_requested: set[str]` 改成 `dict[str, Literal["cancel", "stop"]]`，并给 `cancel_session` 加 `intent` 参数。

finally 块本身**不**直接写 status（三层架构下 status 由外层 session_runner 或具体工具决定，`base_agent` 只管 stream 生命周期），本任务的改动是让 `cancel_session` 调用方能带意图，并把 intent 从 `_cancel_requested` 读回来暴露给外层。

- [ ] **Step 1: 写失败的测试**

新建 `tests/unit/core/test_base_agent_cancel_intent.py`：

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.base_agent import BaseAgent


class _DummyAgent(BaseAgent):
    name = "dummy"
    persona = "Dummy"
    allowed_tools: list[str] = []


@pytest.fixture
def agent() -> _DummyAgent:
    gate = MagicMock()
    gate.build_tool_specs.return_value = []
    session_store = AsyncMock()
    return _DummyAgent(gate=gate, session_store=session_store)


@pytest.mark.asyncio
async def test_cancel_session_defaults_to_cancel_intent(agent: _DummyAgent) -> None:
    # 模拟一个正在跑的 stream
    fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    async def _run() -> str:
        return await fut

    task = asyncio.create_task(_run())
    agent._active_streams["s1"] = task

    await agent.cancel_session("s1")

    assert agent._cancel_requested.get("s1") == "cancel"


@pytest.mark.asyncio
async def test_cancel_session_accepts_stop_intent(agent: _DummyAgent) -> None:
    fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    async def _run() -> str:
        return await fut

    task = asyncio.create_task(_run())
    agent._active_streams["s2"] = task

    await agent.cancel_session("s2", intent="stop")

    assert agent._cancel_requested.get("s2") == "stop"


@pytest.mark.asyncio
async def test_cancel_session_returns_false_when_no_stream(agent: _DummyAgent) -> None:
    result = await agent.cancel_session("nope")
    assert result is False
    assert "nope" not in agent._cancel_requested
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/core/test_base_agent_cancel_intent.py -v
```

期望：FAIL — `_cancel_requested` 当前是 set，`.get()` 会 AttributeError；`cancel_session` 不接受 intent 参数。

- [ ] **Step 3: 改 `_cancel_requested` 类型**

打开 `sebastian/core/base_agent.py` L119-120，当前：

```python
        self._active_streams: dict[str, asyncio.Task[str]] = {}  # session_id → task
        self._cancel_requested: set[str] = set()
```

改为：

```python
        self._active_streams: dict[str, asyncio.Task[str]] = {}  # session_id → task
        # session_id → 意图："cancel"=终态 CANCELLED；"stop"=终态 IDLE（保留上下文可恢复）
        self._cancel_requested: dict[str, str] = {}
```

- [ ] **Step 4: 改 run_streaming 的 finally 读取**

同文件 L335-336 当前：

```python
            was_cancelled = session_id in self._cancel_requested
            self._cancel_requested.discard(session_id)
```

改为：

```python
            was_cancelled = session_id in self._cancel_requested
            self._cancel_requested.pop(session_id, None)
```

- [ ] **Step 5: 改 _stream_inner 里的读取**

同文件 L543 当前：

```python
            if session_id not in self._cancel_requested:
```

这行语义不变（`in dict` 与 `in set` 行为一致），无需改动。

- [ ] **Step 6: 改 cancel_session 签名**

同文件 L581-595 当前：

```python
    async def cancel_session(self, session_id: str) -> bool:
        """Cancel the active streaming turn for session_id.

        Returns True if a stream was cancelled, False if no active stream exists.
        """
        stream = self._active_streams.get(session_id)
        if stream is None or stream.done():
            return False
        self._cancel_requested.add(session_id)
        stream.cancel()
        try:
            await stream
        except (asyncio.CancelledError, Exception):
            pass
        return True
```

改为：

```python
    async def cancel_session(self, session_id: str, intent: str = "cancel") -> bool:
        """Cancel the active streaming turn for session_id.

        Args:
            session_id: target session.
            intent: "cancel" (default, 终态 CANCELLED) 或 "stop"（终态 IDLE，可恢复）。
                    意图会写进 ``_cancel_requested[session_id]``，外层（session_runner /
                    stop_agent 等）在 stream 退出后读取决定如何设置 session.status。

        Returns True if a stream was cancelled, False if no active stream exists.
        """
        stream = self._active_streams.get(session_id)
        if stream is None or stream.done():
            return False
        self._cancel_requested[session_id] = intent
        stream.cancel()
        try:
            await stream
        except (asyncio.CancelledError, Exception):
            pass
        return True
```

- [ ] **Step 7: 运行新测试确认通过**

```bash
pytest tests/unit/core/test_base_agent_cancel_intent.py -v
```

期望：3 passed。

- [ ] **Step 8: 跑完整单测确认无回归**

```bash
pytest tests/unit/ -q
```

期望：全绿。若有测试因 `_cancel_requested` 类型变化失败（例如直接断言它是 set），把那些测试改成用 `in _cancel_requested` 的方式判断存在性。

- [ ] **Step 9: 提交**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_base_agent_cancel_intent.py
git commit -m "refactor(base_agent): _cancel_requested 支持 cancel/stop 两种意图

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 将 reply_to_agent 重命名并扩展为 resume_agent

**Files:**
- Rename: `sebastian/capabilities/tools/reply_to_agent/` → `sebastian/capabilities/tools/resume_agent/`
- Modify: new `resume_agent/__init__.py`
- Rename/rewrite: `tests/unit/capabilities/test_tool_reply_to_agent.py` → `tests/unit/capabilities/test_tool_resume_agent.py`

- [ ] **Step 1: 先写失败的新测试（TDD）**

新建 `tests/unit/capabilities/test_tool_resume_agent.py`，内容：

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import Session, SessionStatus


def _make_session(status: SessionStatus) -> Session:
    s = Session(
        agent_type="code",
        title="重构",
        goal="重构 auth",
        depth=2,
        parent_session_id="seb-123",
    )
    s.status = status
    return s


def _make_mock_state(session: Session):
    state = MagicMock()
    state.index_store = AsyncMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()
    state.session_store.get_session = AsyncMock(return_value=session)
    state.index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": session.id,
                "agent_type": session.agent_type,
                "status": session.status.value,
                "depth": session.depth,
                "parent_session_id": session.parent_session_id,
            }
        ]
    )
    mock_agent = AsyncMock()
    state.agent_instances = {"code": mock_agent}
    return state, mock_agent


@pytest.mark.asyncio
async def test_resume_from_waiting_with_instruction_appends_message():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING)
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(
            agent_type="code",
            session_id=session.id,
            instruction="可以覆盖，继续执行",
        )

    assert result.ok is True
    state.session_store.append_message.assert_awaited_once_with(
        session.id,
        role="user",
        content="可以覆盖，继续执行",
        agent_type="code",
    )
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_resume_from_waiting_without_instruction_skips_append():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING)
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(
            agent_type="code",
            session_id=session.id,
            instruction="",
        )

    assert result.ok is True
    state.session_store.append_message.assert_not_awaited()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_resume_from_idle_with_instruction():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.IDLE)
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(
            agent_type="code",
            session_id=session.id,
            instruction="用户确认继续",
        )

    assert result.ok is True
    state.session_store.append_message.assert_awaited_once()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_resume_from_idle_without_instruction():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.IDLE)
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(
            agent_type="code",
            session_id=session.id,
            instruction="",
        )

    assert result.ok is True
    state.session_store.append_message.assert_not_awaited()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_resume_rejects_active_session():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.ACTIVE)
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(agent_type="code", session_id=session.id, instruction="继续")

    assert result.ok is False
    assert session.id in result.error
    assert "active" in result.error.lower() or "执行" in result.error
    assert "inspect_session" in result.error


@pytest.mark.asyncio
async def test_resume_rejects_cancelled_session():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.CANCELLED)
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert "inspect_session" in result.error


@pytest.mark.asyncio
async def test_resume_rejects_unknown_session():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    state = MagicMock()
    state.index_store = AsyncMock()
    state.index_store.list_all = AsyncMock(return_value=[])

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(agent_type="code", session_id="nonexistent")

    assert result.ok is False
    assert "nonexistent" in result.error
    assert "check_sub_agents" in result.error


@pytest.mark.asyncio
async def test_resume_rejects_agent_type_mismatch():
    from sebastian.capabilities.tools.resume_agent import resume_agent

    session = _make_session(SessionStatus.WAITING)  # session 实际 agent_type=code
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.resume_agent._get_state", return_value=state):
        result = await resume_agent(agent_type="forge", session_id=session.id)  # 声明 forge，实际 code

    assert result.ok is False
    assert "code" in result.error
    assert "forge" in result.error
    assert "check_sub_agents" in result.error
```

- [ ] **Step 2: 运行测试确认失败（模块还没 rename）**

```bash
pytest tests/unit/capabilities/test_tool_resume_agent.py -v
```

期望：FAIL — `sebastian.capabilities.tools.resume_agent` 不存在。

- [ ] **Step 3: 物理重命名目录**

```bash
git mv sebastian/capabilities/tools/reply_to_agent sebastian/capabilities/tools/resume_agent
git mv tests/unit/capabilities/test_tool_reply_to_agent.py tests/unit/capabilities/test_tool_reply_to_agent.py.legacy
```

（`.legacy` 后缀防止 pytest 收集到被替代的旧测试；本步结束前会删掉）

- [ ] **Step 4: 重写 resume_agent/__init__.py**

打开 `sebastian/capabilities/tools/resume_agent/__init__.py`，完整内容改为：

```python
from __future__ import annotations

import asyncio
import logging
from types import ModuleType
from typing import Any

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

_MISSING_CONTEXT_ERROR = (
    "工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。"
    "请向上汇报'内部上下文缺失，无法执行 resume_agent'，不要重试此工具。"
)


def _log_task_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("resume_agent: background session failed", exc_info=exc)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


_RESUMABLE_STATUSES = {SessionStatus.WAITING.value, SessionStatus.IDLE.value}


@tool(
    name="resume_agent",
    description="恢复暂停（IDLE）或等待（WAITING）状态的 sub-agent，可选追加指令。",
    permission_tier=PermissionTier.LOW,
)
async def resume_agent(
    agent_type: str,
    session_id: str,
    instruction: str = "",
) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(ok=False, error=_MISSING_CONTEXT_ERROR)

    state = _get_state()

    all_sessions = await state.index_store.list_all()
    index_entry = next((s for s in all_sessions if s.get("id") == session_id), None)
    if index_entry is None:
        return ToolResult(
            ok=False,
            error=(
                f"找不到 session: {session_id}。"
                "请用 check_sub_agents 确认当前活跃 session 列表。"
            ),
        )

    actual_agent_type: str = index_entry.get("agent_type", "")
    if actual_agent_type != agent_type:
        return ToolResult(
            ok=False,
            error=(
                f"session {session_id} 属于 {actual_agent_type}，不是你传入的 {agent_type}。"
                "请重新核对 check_sub_agents 输出里的 agent_type 字段再调用。"
            ),
        )

    # 权限：组长（depth=2）只能恢复自己的 depth=3 组员
    caller_depth = getattr(ctx, "depth", None)
    caller_session_id = getattr(ctx, "session_id", None)
    target_depth = index_entry.get("depth")
    target_parent = index_entry.get("parent_session_id")
    if caller_depth == 2 and (target_depth != 3 or target_parent != caller_session_id):
        return ToolResult(
            ok=False,
            error=(
                f"无权恢复 session {session_id}：你只能恢复自己创建的子代理 session。"
            ),
        )

    current_status = index_entry.get("status")
    if current_status not in _RESUMABLE_STATUSES:
        return ToolResult(
            ok=False,
            error=(
                f"session {session_id} 当前 status={current_status}，无需恢复。"
                "ACTIVE 状态说明它正在执行，COMPLETED/FAILED/CANCELLED 说明已结束；"
                "请用 inspect_session 查看详情后再决定。"
            ),
        )

    session = await state.session_store.get_session(session_id, actual_agent_type)
    if session is None:
        return ToolResult(
            ok=False,
            error=(
                f"找不到 session 数据: {session_id}。"
                "数据可能已被清理，请用 check_sub_agents 重新列出。"
            ),
        )

    agent = state.agent_instances.get(actual_agent_type)
    if agent is None:
        return ToolResult(
            ok=False,
            error=(
                f"Agent {actual_agent_type} 未初始化。"
                "这是运行时异常，请向上汇报，不要重试此工具。"
            ),
        )

    if instruction:
        await state.session_store.append_message(
            session_id,
            role="user",
            content=instruction,
            agent_type=actual_agent_type,
        )

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

    # 发 SESSION_RESUMED 事件
    from sebastian.protocol.events.bus import EventBus  # noqa: F401
    from sebastian.protocol.events.types import Event, EventType

    if state.event_bus is not None:
        await state.event_bus.publish(
            Event(
                type=EventType.SESSION_RESUMED,
                data={
                    "session_id": session_id,
                    "agent_type": actual_agent_type,
                    "resumed_by": caller_session_id,
                    "instruction": instruction,
                },
            )
        )

    return ToolResult(ok=True, output=f"已恢复 session {session_id}")
```

- [ ] **Step 5: 运行新测试**

```bash
pytest tests/unit/capabilities/test_tool_resume_agent.py -v
```

期望：全部 8 个用例 passed。

如果 `test_resume_rejects_agent_type_mismatch` 等权限/校验测试失败，调试 `index_entry` mock 数据是否含必要字段（depth、parent_session_id 等）。

- [ ] **Step 6: 删除 legacy 测试文件**

```bash
git rm tests/unit/capabilities/test_tool_reply_to_agent.py.legacy
```

- [ ] **Step 7: 全量单测回归**

```bash
pytest tests/unit/ -q
```

期望：除了下游尚未改名的地方（Task 5/6/7），其他应全绿。若出现 import 错误如 `ModuleNotFoundError: sebastian.capabilities.tools.reply_to_agent`，说明有代码还在引用旧名，记录这些文件留到 Task 5/6/8 统一清理——本步先跳过这些失败（可用 `pytest --deselect` 或标记 xfail）。

**实操**：如果 Task 3 结束时还有因 `reply_to_agent` 旧引用挂的测试，不 commit 到干净状态而是继续往下做 Task 5/6 一起修，最后一次性跑绿再 commit。

如果测试结果是干净的（说明 `reply_to_agent` 的引用已被 Task 5/6 的前置搜索覆盖），则继续下一步。

- [ ] **Step 8: 提交**

```bash
git add -A sebastian/capabilities/tools/resume_agent tests/unit/capabilities/test_tool_resume_agent.py
git rm -r --cached sebastian/capabilities/tools/reply_to_agent 2>/dev/null || true
git commit -m "refactor(tools): reply_to_agent → resume_agent，支持 IDLE 恢复和空 instruction

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 新建 stop_agent 工具

**Files:**
- Create: `sebastian/capabilities/tools/stop_agent/__init__.py`
- Create: `tests/unit/capabilities/test_tool_stop_agent.py`

- [ ] **Step 1: 写失败的测试**

新建 `tests/unit/capabilities/test_tool_stop_agent.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import Session, SessionStatus


def _make_session(status: SessionStatus, depth: int = 2, parent_id: str = "seb-123") -> Session:
    s = Session(
        agent_type="code",
        title="重构",
        goal="重构 auth",
        depth=depth,
        parent_session_id=parent_id,
    )
    s.status = status
    return s


def _make_mock_state(session: Session):
    state = MagicMock()
    state.index_store = AsyncMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()
    state.session_store.get_session = AsyncMock(return_value=session)
    state.index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": session.id,
                "agent_type": session.agent_type,
                "status": session.status.value,
                "depth": session.depth,
                "parent_session_id": session.parent_session_id,
            }
        ]
    )
    mock_agent = AsyncMock()
    mock_agent.cancel_session = AsyncMock(return_value=True)
    state.agent_instances = {"code": mock_agent}
    return state, mock_agent


def _patch_sebastian_ctx(monkeypatch):
    """模拟调用方是 Sebastian（depth=1），有全权限。"""
    from sebastian.permissions.types import ToolCallContext

    ctx = ToolCallContext(
        agent_name="sebastian",
        agent_type="sebastian",
        session_id="seb-123",
        depth=1,
        task_id=None,
    )
    monkeypatch.setattr(
        "sebastian.capabilities.tools.stop_agent.get_tool_context", lambda: ctx
    )


@pytest.mark.asyncio
async def test_stop_active_session_transitions_to_idle(monkeypatch):
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    _patch_sebastian_ctx(monkeypatch)
    session = _make_session(SessionStatus.ACTIVE)
    state, mock_agent = _make_mock_state(session)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=session.id, reason="用户改主意")

    assert result.ok is True
    mock_agent.cancel_session.assert_awaited_once_with(session.id, intent="stop")
    # 状态写到 IDLE
    assert session.status == SessionStatus.IDLE
    state.session_store.update_session.assert_awaited()
    state.index_store.upsert.assert_awaited()
    # 对话历史加了 system message
    state.session_store.append_message.assert_awaited_once()
    kwargs = state.session_store.append_message.await_args.kwargs
    assert kwargs["role"] == "system"
    assert "用户改主意" in kwargs["content"]


@pytest.mark.asyncio
async def test_stop_stalled_session_transitions_to_idle(monkeypatch):
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    _patch_sebastian_ctx(monkeypatch)
    session = _make_session(SessionStatus.STALLED)
    state, _ = _make_mock_state(session)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    assert session.status == SessionStatus.IDLE


@pytest.mark.asyncio
async def test_stop_idle_session_is_idempotent(monkeypatch):
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    _patch_sebastian_ctx(monkeypatch)
    session = _make_session(SessionStatus.IDLE)
    state, mock_agent = _make_mock_state(session)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is True
    assert "IDLE" in result.output
    mock_agent.cancel_session.assert_not_awaited()
    state.session_store.append_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_completed_session_rejected(monkeypatch):
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    _patch_sebastian_ctx(monkeypatch)
    session = _make_session(SessionStatus.COMPLETED)
    state, _ = _make_mock_state(session)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=session.id)

    assert result.ok is False
    assert session.id in result.error
    assert "completed" in result.error.lower() or "已结束" in result.error
    assert "inspect_session" in result.error


@pytest.mark.asyncio
async def test_stop_unknown_session(monkeypatch):
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    _patch_sebastian_ctx(monkeypatch)
    state = MagicMock()
    state.index_store = AsyncMock()
    state.index_store.list_all = AsyncMock(return_value=[])

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id="nope")

    assert result.ok is False
    assert "nope" in result.error
    assert "check_sub_agents" in result.error


@pytest.mark.asyncio
async def test_stop_agent_type_mismatch(monkeypatch):
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent

    _patch_sebastian_ctx(monkeypatch)
    session = _make_session(SessionStatus.ACTIVE)  # 实际 agent_type=code
    state, _ = _make_mock_state(session)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="forge", session_id=session.id)  # 声明 forge

    assert result.ok is False
    assert "code" in result.error and "forge" in result.error
    assert "check_sub_agents" in result.error


@pytest.mark.asyncio
async def test_leader_can_stop_own_sub_worker(monkeypatch):
    """组长（depth=2）可以停自己派出去的 depth=3 组员。"""
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent
    from sebastian.permissions.types import ToolCallContext

    leader_session_id = "code-leader-1"
    worker_session = _make_session(
        SessionStatus.ACTIVE, depth=3, parent_id=leader_session_id
    )
    state, _ = _make_mock_state(worker_session)

    ctx = ToolCallContext(
        agent_name="code",
        agent_type="code",
        session_id=leader_session_id,
        depth=2,
        task_id=None,
    )
    monkeypatch.setattr(stop_mod, "get_tool_context", lambda: ctx)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=worker_session.id)

    assert result.ok is True


@pytest.mark.asyncio
async def test_leader_cannot_stop_other_leaders_worker(monkeypatch):
    """组长不能停别的组长的组员。"""
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent
    from sebastian.permissions.types import ToolCallContext

    other_leader_id = "code-leader-2"
    worker_session = _make_session(
        SessionStatus.ACTIVE, depth=3, parent_id=other_leader_id
    )
    state, _ = _make_mock_state(worker_session)

    ctx = ToolCallContext(
        agent_name="code",
        agent_type="code",
        session_id="code-leader-1",  # 不是该组员的父
        depth=2,
        task_id=None,
    )
    monkeypatch.setattr(stop_mod, "get_tool_context", lambda: ctx)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=worker_session.id)

    assert result.ok is False
    assert "无权" in result.error
    assert worker_session.id in result.error


@pytest.mark.asyncio
async def test_leader_cannot_stop_depth2_session(monkeypatch):
    """组长不能停别的组长本身（depth=2）。"""
    from sebastian.capabilities.tools import stop_agent as stop_mod
    from sebastian.capabilities.tools.stop_agent import stop_agent
    from sebastian.permissions.types import ToolCallContext

    leader_session = _make_session(SessionStatus.ACTIVE, depth=2, parent_id="seb-123")
    state, _ = _make_mock_state(leader_session)

    ctx = ToolCallContext(
        agent_name="code",
        agent_type="code",
        session_id="code-leader-1",
        depth=2,
        task_id=None,
    )
    monkeypatch.setattr(stop_mod, "get_tool_context", lambda: ctx)

    with patch.object(stop_mod, "_get_state", return_value=state):
        result = await stop_agent(agent_type="code", session_id=leader_session.id)

    assert result.ok is False
    assert "无权" in result.error
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/capabilities/test_tool_stop_agent.py -v
```

期望：FAIL — `sebastian.capabilities.tools.stop_agent` 不存在。

- [ ] **Step 3: 创建 stop_agent 目录和工具实现**

创建 `sebastian/capabilities/tools/stop_agent/__init__.py`：

```python
from __future__ import annotations

import logging
from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

_MISSING_CONTEXT_ERROR = (
    "工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。"
    "请向上汇报'内部上下文缺失，无法执行 stop_agent'，不要重试此工具。"
)

_STOPPABLE_STATUSES = {SessionStatus.ACTIVE.value, SessionStatus.STALLED.value}
_TERMINAL_STATUSES = {
    SessionStatus.COMPLETED.value,
    SessionStatus.FAILED.value,
    SessionStatus.CANCELLED.value,
}


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="stop_agent",
    description="暂停指定 sub-agent session 的执行，保留上下文以便恢复。",
    permission_tier=PermissionTier.LOW,
)
async def stop_agent(
    agent_type: str,
    session_id: str,
    reason: str = "",
) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(ok=False, error=_MISSING_CONTEXT_ERROR)

    state = _get_state()

    all_sessions = await state.index_store.list_all()
    index_entry = next((s for s in all_sessions if s.get("id") == session_id), None)
    if index_entry is None:
        return ToolResult(
            ok=False,
            error=(
                f"找不到 session: {session_id}。"
                "请用 check_sub_agents 确认当前活跃 session 列表，不要用猜的 id 重试。"
            ),
        )

    actual_agent_type: str = index_entry.get("agent_type", "")
    if actual_agent_type != agent_type:
        return ToolResult(
            ok=False,
            error=(
                f"session {session_id} 属于 {actual_agent_type}，不是你传入的 {agent_type}。"
                "请重新核对 check_sub_agents 输出里的 agent_type 字段再调用。"
            ),
        )

    # 权限：组长（depth=2）只能停自己的 depth=3 组员
    caller_depth = getattr(ctx, "depth", None)
    caller_session_id = getattr(ctx, "session_id", None)
    target_depth = index_entry.get("depth")
    target_parent = index_entry.get("parent_session_id")
    if caller_depth == 2 and (target_depth != 3 or target_parent != caller_session_id):
        return ToolResult(
            ok=False,
            error=(
                f"无权停止 session {session_id}：你只能停止自己创建的子代理 session。"
                "请向 Sebastian 汇报需要停止该任务。"
            ),
        )

    current_status = index_entry.get("status")

    # 幂等：已是 IDLE 直接成功
    if current_status == SessionStatus.IDLE.value:
        return ToolResult(ok=True, output=f"session {session_id} 已是 IDLE 状态")

    # 已终态：拒绝
    if current_status in _TERMINAL_STATUSES:
        return ToolResult(
            ok=False,
            error=(
                f"session {session_id} 已结束（status={current_status}），无法停止。"
                "如需查看结果，使用 inspect_session。"
            ),
        )

    # 只接受 ACTIVE / STALLED
    if current_status not in _STOPPABLE_STATUSES:
        return ToolResult(
            ok=False,
            error=(
                f"session {session_id} 当前 status={current_status}，无法停止。"
                "只能停止 ACTIVE 或 STALLED 状态的 session。"
            ),
        )

    agent = state.agent_instances.get(actual_agent_type)
    if agent is None:
        return ToolResult(
            ok=False,
            error=(
                f"Agent {actual_agent_type} 未初始化。"
                "这是运行时异常，请向上汇报，不要重试此工具。"
            ),
        )

    # 打断执行（intent=stop，外层据此决定不把 status 写成 CANCELLED）
    await agent.cancel_session(session_id, intent="stop")

    # 取 session 并落盘 IDLE
    session = await state.session_store.get_session(session_id, actual_agent_type)
    if session is None:
        return ToolResult(
            ok=False,
            error=(
                f"找不到 session 数据: {session_id}。"
                "数据可能已被清理，请用 check_sub_agents 重新列出。"
            ),
        )
    session.status = SessionStatus.IDLE
    await state.session_store.update_session(session)
    await state.index_store.upsert(session)

    # 追加 system message
    content = f"[上级暂停] reason: {reason}" if reason else "[上级暂停]"
    await state.session_store.append_message(
        session_id,
        role="system",
        content=content,
        agent_type=actual_agent_type,
    )

    # 发事件
    from sebastian.protocol.events.types import Event, EventType

    if state.event_bus is not None:
        await state.event_bus.publish(
            Event(
                type=EventType.SESSION_PAUSED,
                data={
                    "session_id": session_id,
                    "agent_type": actual_agent_type,
                    "stopped_by": caller_session_id,
                    "reason": reason,
                },
            )
        )

    return ToolResult(ok=True, output=f"已暂停 session {session_id}")
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/capabilities/test_tool_stop_agent.py -v
```

期望：9 个用例全绿。

调试提示：
- 若 `test_leader_cannot_stop_depth2_session` 过，说明组长打到 depth=2 的 session 已拒绝，没问题。
- 若 `test_stop_active_session_transitions_to_idle` 的 `cancel_session.assert_awaited_once_with(session.id, intent="stop")` 失败，检查 Task 2 是否已正确把 `cancel_session` 签名加上 intent。

- [ ] **Step 5: 跑完整单测回归**

```bash
pytest tests/unit/ -q
```

期望：全绿（但下游 sebas.py / _loader.py 的 reply_to_agent 引用可能还在，这些会在 Task 5/6 修，届时任何相关测试回归一起处理）。

- [ ] **Step 6: 提交**

```bash
git add sebastian/capabilities/tools/stop_agent tests/unit/capabilities/test_tool_stop_agent.py
git commit -m "feat(tools): 新增 stop_agent 工具，允许上级暂停 sub-agent session

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 更新 _loader.py 的协议工具清单

**Files:**
- Modify: `sebastian/agents/_loader.py`（L19-25）
- Modify: `tests/unit/agents/test_agent_loader.py`（若断言该清单）

- [ ] **Step 1: 看现状**

Read `sebastian/agents/_loader.py:19-25`：

```python
_SUBAGENT_PROTOCOL_TOOLS: tuple[str, ...] = (
    "ask_parent",
    "reply_to_agent",
    "spawn_sub_agent",
    "check_sub_agents",
    "inspect_session",
)
```

Read `tests/unit/agents/test_agent_loader.py`，找出 grep `reply_to_agent` 的位置：

```bash
grep -n reply_to_agent tests/unit/agents/test_agent_loader.py
```

- [ ] **Step 2: 改 _SUBAGENT_PROTOCOL_TOOLS**

把 `reply_to_agent` 改名为 `resume_agent`，并追加 `stop_agent`：

```python
_SUBAGENT_PROTOCOL_TOOLS: tuple[str, ...] = (
    "ask_parent",         # 向上级请示，暂停等待回复
    "resume_agent",       # 回复/恢复等待或暂停中的下属（取代 reply_to_agent）
    "stop_agent",         # 暂停下属 session
    "spawn_sub_agent",    # 向下分派 depth=3 组员
    "check_sub_agents",   # 查看自己的组员任务状态
    "inspect_session",    # 查看指定 session 的详细进展
)
```

- [ ] **Step 3: 同步测试**

打开 `tests/unit/agents/test_agent_loader.py`，把所有对 `reply_to_agent` 的断言改为 `resume_agent`，并在需要断言协议工具集合时把 `stop_agent` 加进去。

例如若有：
```python
assert "reply_to_agent" in effective_tools
```
改为：
```python
assert "resume_agent" in effective_tools
assert "stop_agent" in effective_tools
```

- [ ] **Step 4: 跑 agent loader 单测**

```bash
pytest tests/unit/agents/test_agent_loader.py -v
```

期望：全绿。

- [ ] **Step 5: 提交**

```bash
git add sebastian/agents/_loader.py tests/unit/agents/test_agent_loader.py
git commit -m "refactor(agents): 协议工具清单 reply_to_agent → resume_agent，补 stop_agent

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 更新 sebas.py 与相关下游引用

**Files:**
- Modify: `sebastian/orchestrator/sebas.py`（L84-99）
- Modify: `sebastian/gateway/completion_notifier.py`（若 grep 有 reply_to_agent）
- Modify: `tests/unit/runtime/test_sebas.py`（若 grep 有 reply_to_agent）
- Modify: `tests/unit/gateway/test_completion_notifier.py`（同上）
- Create: import 行补充（`stop_agent`、`resume_agent` 工具的注册 import）

- [ ] **Step 1: 找所有 reply_to_agent 引用**

```bash
grep -rn "reply_to_agent" sebastian/ tests/
```

目标：除 spec 文档以外都要改。

- [ ] **Step 2: 改 sebas.py**

打开 `sebastian/orchestrator/sebas.py`：

顶部 import（L7-9）当前：
```python
from sebastian.capabilities.tools import (
    delegate_to_agent as _delegate_tools,  # noqa: F401
)
```

改为（追加两条注册 import，模式与 _delegate_tools 一致）：
```python
from sebastian.capabilities.tools import (
    delegate_to_agent as _delegate_tools,  # noqa: F401  # registers delegate_to_agent tool
)
from sebastian.capabilities.tools import (
    resume_agent as _resume_tools,  # noqa: F401  # registers resume_agent tool
)
from sebastian.capabilities.tools import (
    stop_agent as _stop_tools,  # noqa: F401  # registers stop_agent tool
)
```

`allowed_tools` 列表（L87-99）当前：
```python
    allowed_tools = [
        "delegate_to_agent",
        "check_sub_agents",
        "inspect_session",
        "reply_to_agent",
        "todo_write",
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
    ]
```

改为：
```python
    allowed_tools = [
        "delegate_to_agent",
        "check_sub_agents",
        "inspect_session",
        "resume_agent",
        "stop_agent",
        "todo_write",
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
    ]
```

并把上方注释 L84-86 里提到 `reply_to_agent` 的那段更新为 `resume_agent`。

- [ ] **Step 3: 改 completion_notifier.py（如含引用）**

```bash
grep -n "reply_to_agent" sebastian/gateway/completion_notifier.py
```

若有命中，把所有 `reply_to_agent` 改成 `resume_agent`。这是通知机制里用来"唤起父 Agent"时建议使用的工具名提示文本，改名即可。

- [ ] **Step 4: 改测试中的 reply_to_agent 引用**

```bash
grep -rn "reply_to_agent" tests/
```

期望剩余文件：`tests/unit/runtime/test_sebas.py`、`tests/unit/gateway/test_completion_notifier.py`。

对每个命中：
- 若是 `allowed_tools` 断言，把 `"reply_to_agent"` 改为 `"resume_agent"`，如果测试检查协议工具集合完整性，补上 `"stop_agent"`。
- 若是 mock 或调用 `reply_to_agent` 函数本身，把 import 和调用都改成 `resume_agent`（注意签名变化：现在首参是 `agent_type`）。

- [ ] **Step 5: 再全局搜一次确保没遗漏**

```bash
grep -rn "reply_to_agent" sebastian/ tests/
```

期望：无匹配。

- [ ] **Step 6: 跑相关单测**

```bash
pytest tests/unit/runtime/ tests/unit/gateway/ tests/unit/capabilities/ tests/unit/agents/ -v
```

期望：全绿。

- [ ] **Step 7: 跑完整单测确认**

```bash
pytest tests/unit/ -q
```

期望：全绿。

- [ ] **Step 8: 提交**

```bash
git add sebastian/orchestrator/sebas.py sebastian/gateway/completion_notifier.py tests/
git commit -m "refactor: Sebastian allowed_tools 同步 resume_agent/stop_agent，清理 reply_to_agent 引用

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Android ToolDisplayName + ToolCallInputExtractor

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt`（L17-26 KEY_PRIORITY）
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt`

> 使用 Android Studio MCP 优先（`android-studio-index`）定位与编辑 Kotlin 文件。

- [ ] **Step 1: 先加 KEY_PRIORITY，让 extractor 测试 FAIL-then-PASS**

在 `ToolCallInputExtractorTest.kt` 里新增测试：

```kotlin
@Test
fun `stop_agent summary picks agent_type`() {
    val summary = ToolCallInputExtractor.extractInputSummary(
        "stop_agent",
        """{"agent_type":"forge","session_id":"abc-123","reason":"过时了"}""",
    )
    assertEquals("forge", summary)
}

@Test
fun `resume_agent summary picks agent_type`() {
    val summary = ToolCallInputExtractor.extractInputSummary(
        "resume_agent",
        """{"agent_type":"forge","session_id":"abc-123","instruction":"继续"}""",
    )
    assertEquals("forge", summary)
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolCallInputExtractorTest"
```

期望：FAIL — 当前没有 stop_agent / resume_agent 的 KEY_PRIORITY 条目，`agent_type` 不在 `GENERIC_KEYS` 中，fallback 会取别的键。

- [ ] **Step 3: 加 KEY_PRIORITY 条目**

打开 `ToolCallInputExtractor.kt` L17-26，把 KEY_PRIORITY 改为：

```kotlin
    private val KEY_PRIORITY: Map<String, List<String>> = mapOf(
        "Bash" to listOf("command"),
        "Read" to listOf("file_path"),
        "Write" to listOf("file_path"),
        "Edit" to listOf("file_path"),
        "Grep" to listOf("pattern", "path"),
        "Glob" to listOf("pattern", "path"),
        "delegate_to_agent" to listOf("agent_type"),
        "spawn_sub_agent" to listOf("goal"),
        "stop_agent" to listOf("agent_type"),
        "resume_agent" to listOf("agent_type"),
    )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolCallInputExtractorTest"
```

期望：PASS。

- [ ] **Step 5: 写 ToolDisplayNameTest 新用例**

打开 `ToolDisplayNameTest.kt`，追加：

```kotlin
@Test
fun `stop_agent resolves to 'Stop Agent: {Name}'`() {
    val display = ToolDisplayName.resolve(
        "stop_agent",
        """{"agent_type":"forge","session_id":"abc-123"}""",
    )
    assertEquals("Stop Agent: Forge", display.title)
    assertEquals("", display.summary)
}

@Test
fun `resume_agent resolves to 'Resume Agent: {Name}'`() {
    val display = ToolDisplayName.resolve(
        "resume_agent",
        """{"agent_type":"forge","session_id":"abc-123"}""",
    )
    assertEquals("Resume Agent: Forge", display.title)
    assertEquals("", display.summary)
}
```

- [ ] **Step 6: 跑测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolDisplayNameTest"
```

期望：FAIL — 默认 else 分支把 title 设为 "stop_agent"/"resume_agent"。

- [ ] **Step 7: 在 ToolDisplayName.resolve 加两条 case**

打开 `ToolDisplayName.kt`，把 `when` 改为：

```kotlin
        return when (toolName) {
            "delegate_to_agent" -> Display(
                title = "Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
                summary = "",
            )
            "spawn_sub_agent" -> Display(title = "Worker", summary = rawSummary)
            "stop_agent" -> Display(
                title = "Stop Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
                summary = "",
            )
            "resume_agent" -> Display(
                title = "Resume Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
                summary = "",
            )
            else -> Display(title = toolName, summary = rawSummary)
        }
```

- [ ] **Step 8: 跑测试**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolDisplayNameTest"
```

期望：全绿。

- [ ] **Step 9: 跑 ktlint/lint 保底**

```bash
./gradlew :app:lintDebug
```

期望：无新警告（或至少不涉及改动文件）。

- [ ] **Step 10: 提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt
git commit -m "feat(android): 工具卡片支持 stop_agent/resume_agent 的 'Stop/Resume Agent: {Name}' 显示

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 文档与 README 同步

**Files:**
- Modify: `docs/architecture/spec/overview/three-tier-agent.md`（§3.3 状态机、§5 工具章节）
- Modify: `sebastian/capabilities/README.md`
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/agents/README.md`（若提到 reply_to_agent）
- Modify: `docs/architecture/spec/agents/permission.md`（若提到 reply_to_agent）
- Modify: `docs/superpowers/specs/2026-04-15-agent-stop-resume-design.md` — 改 `status: planned` → `status: implemented`

- [ ] **Step 1: three-tier-agent.md §3.3 状态机补 stop 边**

Read `docs/architecture/spec/overview/three-tier-agent.md`，找到状态机示意图（约 L101-110）：

```
active → completed
active → failed
active → idle          （等待输入 / 暂停）
active → stalled
active → cancelled
idle   → active
stalled → active
stalled → cancelled
```

改为（明确 stop_agent 与 user input 两条 active→idle 路径，以及 IDLE/WAITING → ACTIVE via resume_agent）：

```
active → completed
active → failed
active → idle          （用户暂停 / stop_agent 推入）
active → stalled
active → cancelled
idle   → active        （resume_agent 或用户消息继续）
waiting → active       （resume_agent 追加指令恢复）
stalled → active
stalled → idle         （stop_agent 也可停 stalled 的）
stalled → cancelled
```

- [ ] **Step 2: three-tier-agent.md §5 工具列表补 stop_agent、reply_to_agent 改名**

找到 §5 工具设计区，追加 5.5 小节（或在 5.3/5.4 后顺序插入）：

```markdown
### 5.5 stop_agent（Sebastian 和组长共用）

```python
@tool(name="stop_agent", permission_tier=PermissionTier.LOW)
async def stop_agent(agent_type: str, session_id: str, reason: str = "") -> ToolResult:
    # 1. 权限：Sebastian 可停任何 depth=2/3；组长只能停自己派出的 depth=3
    # 2. agent_type 与 session 实际 agent_type 交叉校验
    # 3. 调 BaseAgent.cancel_session(intent="stop") 打断 stream
    # 4. status 改 IDLE，追加 [上级暂停] system message
    # 5. 发 SESSION_PAUSED 事件
```

### 5.6 resume_agent（Sebastian 和组长共用，取代原 reply_to_agent）

```python
@tool(name="resume_agent", permission_tier=PermissionTier.LOW)
async def resume_agent(agent_type: str, session_id: str, instruction: str = "") -> ToolResult:
    # 1. 同 stop_agent 的权限/交叉校验
    # 2. 接受 WAITING 或 IDLE 状态
    # 3. 有 instruction 则 append_message；无则跳过
    # 4. status 切 ACTIVE，重启 run loop
    # 5. 发 SESSION_RESUMED 事件
```
```

如果文档里有旧的 `reply_to_agent` 文字，一律改成 `resume_agent`。

- [ ] **Step 3: sebastian/capabilities/README.md 和 tools/README.md 工具清单**

```bash
grep -n "reply_to_agent" sebastian/capabilities/README.md sebastian/capabilities/tools/README.md
```

对每条命中把 `reply_to_agent` 改为 `resume_agent`，并在相邻位置追加 `stop_agent` 的简短说明：

- `stop_agent` — 暂停指定 sub-agent session（可恢复）
- `resume_agent` — 恢复 WAITING/IDLE 的 sub-agent session，可选追加指令（取代 reply_to_agent）

- [ ] **Step 4: sebastian/agents/README.md 与 permission.md**

```bash
grep -n "reply_to_agent" sebastian/agents/README.md docs/architecture/spec/agents/permission.md
```

对命中的位置把 `reply_to_agent` 改为 `resume_agent`，必要时补 `stop_agent` 说明。

- [ ] **Step 5: spec 文档状态翻面**

打开 `docs/superpowers/specs/2026-04-15-agent-stop-resume-design.md`，frontmatter：

```yaml
status: planned
```

改为：

```yaml
status: implemented
last_updated: <今日日期>
```

- [ ] **Step 6: 最终全局搜一次**

```bash
grep -rn "reply_to_agent" sebastian/ tests/ docs/architecture/ ui/
```

期望：除 `docs/superpowers/archive/` 和本计划文档本身以外，均无命中。

- [ ] **Step 7: 提交**

```bash
git add docs/ sebastian/capabilities/README.md sebastian/capabilities/tools/README.md sebastian/agents/README.md
git commit -m "docs: 同步 stop_agent/resume_agent 新工具至架构 spec 与 README

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 端到端回归

**Files:** 无代码改动

- [ ] **Step 1: 完整后端单测**

```bash
pytest tests/unit/ tests/integration/ -q
```

期望：全绿。

- [ ] **Step 2: 后端 lint/type**

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
mypy sebastian/
```

期望：无新错误（格式化未通过时用 `ruff format sebastian/ tests/` 修，重新 commit 到 Task 8 里或单独一个 chore commit）。

- [ ] **Step 3: Android 单测 + lint**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest
./gradlew :app:lintDebug
```

期望：全绿。

- [ ] **Step 4: 手动验收（可选但推荐）**

启动开发环境：

```bash
./scripts/dev.sh
```

然后在 Android 模拟器上：
1. 跟 Sebastian 说："让 forge 帮我写一个长测试文件" → delegate 一个 forge session
2. 在 sub-agent 列表页面进入该 session，看到它在跑
3. 回到主对话，跟 Sebastian 说："停下 forge 那个任务，等我确认" → 期望 Sebastian 调 `stop_agent`，ToolCallCard header 显示 "Stop Agent: Forge"
4. 进入 sub-agent session 看到 status 变 idle
5. 跟 Sebastian 说："继续吧" → 期望调 `resume_agent`，header 显示 "Resume Agent: Forge"
6. sub-agent 恢复执行

- [ ] **Step 5: 开 PR**

遵循项目 `commit-pr` 流程（`CLAUDE.md` §11）：

```bash
git checkout dev
git fetch origin main
git rebase origin/main
git push --force-with-lease
gh pr create --base main --head dev \
  --title "feat: 新增 stop_agent 工具并将 reply_to_agent 重命名为 resume_agent" \
  --body "$(cat <<'EOF'
## Summary
- 新增 stop_agent 工具：让 Sebastian / 组长可主动暂停已委派的 sub-agent session（ACTIVE/STALLED → IDLE，保留上下文可恢复）
- reply_to_agent → resume_agent：接受状态扩展到 WAITING | IDLE；instruction 可空（空=按原计划继续）；首参加 agent_type 做交叉校验
- BaseAgent.cancel_session 支持 intent=cancel|stop，_cancel_requested 改为 dict 存意图
- Android ToolCallCard 显示 "Stop Agent: {Name}" / "Resume Agent: {Name}"

## Test plan
- [x] 新增 tests/unit/capabilities/test_tool_stop_agent.py（9 用例）
- [x] 新增 tests/unit/capabilities/test_tool_resume_agent.py（8 用例）取代原 reply_to_agent 测试
- [x] 新增 tests/unit/core/test_base_agent_cancel_intent.py（3 用例）
- [x] Android 单测 ToolDisplayNameTest / ToolCallInputExtractorTest 已扩展
- [x] pytest tests/unit tests/integration 全绿
- [x] ruff check / mypy 无新错误
- [x] Android ./gradlew :app:testDebugUnitTest 全绿
- [ ] 手动：模拟器上跑一遍 delegate → stop → resume 流程（可选）
EOF
)"
```

---

## Self-Review Checklist

写完计划后自查（无须在此改动计划，仅列出在心里跑一遍）：

**1. Spec coverage**
- §2.1 两个工具 → Task 3 (resume_agent) + Task 4 (stop_agent) ✓
- §2.2 状态机复用 IDLE → Task 4 + Task 2 (cancel intent 区分 IDLE vs CANCELLED) ✓
- §3.1/3.2 stop_agent 设计 → Task 4 实现 ✓
- §3.3 幂等 → Task 4 测试 `test_stop_idle_session_is_idempotent` ✓
- §3.4 cancel_session 改 dict → Task 2 ✓
- §3.5 失败返回规范 → Task 4 测试逐条断言错误文本包含关键词 ✓
- §4.1-4.4 resume_agent 演化 → Task 3 ✓
- §5 事件 → Task 1 ✓，Task 3/4 发事件 ✓
- §6.1/6.3 权限 → Task 4 权限测试 + 组长/Sebastian 场景 ✓
- §6.4 App 显示名 → Task 7 ✓
- §7 测试要点 → Task 3/4 测试 ✓
- §8 影响面 → Task 5/6/7/8 覆盖 ✓
- §9 风险登记 → 只是文档，已包含在 spec，不需要 Task 实现

**2. 类型/签名一致性**
- `cancel_session(session_id, intent="cancel")` 在 Task 2 定义，Task 4 用 `intent="stop"` 调用 ✓
- `stop_agent(agent_type, session_id, reason="")` 在 Task 4 定义，Task 7 Android 测试 JSON 字段名对齐 ✓
- `resume_agent(agent_type, session_id, instruction="")` 在 Task 3 定义，同上 ✓
- `_cancel_requested: dict[str, str]` Task 2 定义，Task 4 stop_agent 未直接访问（通过 cancel_session 间接走），一致 ✓

**3. 无占位符**：各 Step 都有具体命令 / 代码 / 期望输出 ✓

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-15-agent-stop-resume.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 每个 Task 派发一个独立 subagent 执行，任务间我 review 差异并决定下一步，迭代最快，上下文最干净

**2. Inline Execution** — 我在本会话直接按顺序执行，每几个 Task 设 checkpoint 请你确认

**选哪个？**

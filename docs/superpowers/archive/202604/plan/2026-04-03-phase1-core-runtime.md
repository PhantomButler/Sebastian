# Phase 1 Core Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Phase 1 runtime to full streaming AgentLoop, block-level SSE events,打断机制, Task 状态机校验, AgentPool worker 槽位, 以及以 Session 为中心的 REST API。

**Architecture:** AgentLoop 改为 async generator（yield LLMStreamEvent），BaseAgent 消费 generator 并通过分发表 publish SSE 事件；打断机制靠 cancel asyncio.Task + partial 写入 history；AgentPool 管理每个 agent_type 的 3 个持久 worker 槽位。

**Tech Stack:** Python 3.12+, anthropic SDK streaming, FastAPI, asyncio, pytest-asyncio, aiofiles

**Spec:** `docs/superpowers/specs/2026-04-03-phase1-core-runtime-design.md`

---

## File Map

| 文件 | 操作 | 职责 |
|---|---|---|
| `sebastian/core/stream_events.py` | 新增 | LLMStreamEvent dataclass 类型定义 |
| `sebastian/core/agent_loop.py` | 重构 | `run()` → `stream()` async generator |
| `sebastian/core/base_agent.py` | 重构 | `run_streaming()` + `_stream_inner()` + 打断机制 |
| `sebastian/core/types.py` | 修改 | Session: `agent` → `agent_type + agent_id`；新增 `InvalidTaskTransitionError` |
| `sebastian/core/task_manager.py` | 修改 | `_transition()` 统一状态变更 + 合法性校验 |
| `sebastian/core/agent_pool.py` | 新增 | AgentPool worker 槽位管理 |
| `sebastian/protocol/events/types.py` | 修改 | 补全 block 级 EventType |
| `sebastian/store/session_store.py` | 修改 | `agent` → `agent_type + agent_id` |
| `sebastian/store/index_store.py` | 修改 | `agent` → `agent_type + agent_id` |
| `sebastian/gateway/sse.py` | 修改 | event id + 500 条缓冲 + session 级过滤 |
| `sebastian/gateway/routes/turns.py` | 修改 | 非阻塞返回 |
| `sebastian/gateway/routes/sessions.py` | 修改 | 路由补全，agent_type/agent_id 支持 |
| `sebastian/gateway/routes/agents.py` | 修改 | 返回 worker 状态 + queue_depth |
| `sebastian/orchestrator/sebas.py` | 修改 | 使用 `run_streaming()`，适配新 Session 字段 |
| `tests/unit/test_stream_events.py` | 新增 | stream event dataclass 基础测试 |
| `tests/unit/test_agent_loop.py` | 重构 | 基于 generator 的测试 |
| `tests/unit/test_base_agent.py` | 重构 | run_streaming + 打断机制测试 |
| `tests/unit/test_task_manager.py` | 修改 | 状态转换校验测试 |
| `tests/unit/test_agent_pool.py` | 新增 | acquire/release/排队测试 |
| `tests/unit/test_sse_manager.py` | 修改 | event id + 缓冲 + session 过滤测试 |

---

## Task 1: LLMStreamEvent 类型定义

**Files:**
- Create: `sebastian/core/stream_events.py`
- Create: `tests/unit/test_stream_events.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_stream_events.py
from __future__ import annotations
import dataclasses


def test_stream_event_types_are_dataclasses():
    from sebastian.core.stream_events import (
        ThinkingBlockStart, ThinkingDelta, ThinkingBlockStop,
        TextBlockStart, TextDelta, TextBlockStop,
        ToolCallBlockStart, ToolCallReady, ToolResult, TurnDone,
    )
    e = ThinkingBlockStart(block_id="b0_0")
    assert e.block_id == "b0_0"
    assert dataclasses.is_dataclass(e)

    tc = ToolCallReady(block_id="b0_2", tool_id="tu_01", name="search", inputs={"q": "x"})
    assert tc.inputs == {"q": "x"}

    done = TurnDone(full_text="hello")
    assert done.full_text == "hello"

    result = ToolResult(tool_id="tu_01", name="search", ok=True, output="data", error=None)
    assert result.ok is True
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_stream_events.py -v
```
Expected: `ModuleNotFoundError: No module named 'sebastian.core.stream_events'`

- [ ] **Step 3: 创建 `sebastian/core/stream_events.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class ThinkingBlockStart:
    block_id: str


@dataclass
class ThinkingDelta:
    block_id: str
    delta: str


@dataclass
class ThinkingBlockStop:
    block_id: str


@dataclass
class TextBlockStart:
    block_id: str


@dataclass
class TextDelta:
    block_id: str
    delta: str


@dataclass
class TextBlockStop:
    block_id: str


@dataclass
class ToolCallBlockStart:
    block_id: str
    tool_id: str
    name: str


@dataclass
class ToolCallReady:
    block_id: str
    tool_id: str
    name: str
    inputs: dict[str, Any]


@dataclass
class ToolResult:
    tool_id: str
    name: str
    ok: bool
    output: Any
    error: str | None


@dataclass
class TurnDone:
    full_text: str


LLMStreamEvent = (
    ThinkingBlockStart | ThinkingDelta | ThinkingBlockStop
    | TextBlockStart | TextDelta | TextBlockStop
    | ToolCallBlockStart | ToolCallReady | ToolResult
    | TurnDone
)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_stream_events.py -v
```
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/stream_events.py tests/unit/test_stream_events.py
git commit -m "feat(core): add LLMStreamEvent dataclass types"
```

---

## Task 2: Session 模型 agent → agent_type + agent_id

**Files:**
- Modify: `sebastian/core/types.py`
- Modify: `tests/unit/test_core_types.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/test_core_types.py
def test_session_has_agent_type_and_agent_id():
    from sebastian.core.types import Session
    s = Session(agent_type="stock", agent_id="stock_01", title="test")
    assert s.agent_type == "stock"
    assert s.agent_id == "stock_01"
    # agent 字段不再存在
    assert not hasattr(s, "agent")
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_core_types.py::test_session_has_agent_type_and_agent_id -v
```
Expected: FAIL

- [ ] **Step 3: 修改 `sebastian/core/types.py` 的 Session 类**

将：
```python
class Session(BaseModel):
    id: str = Field(...)
    agent: str
    title: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)
    task_count: int = 0
    active_task_count: int = 0
```

改为：
```python
class Session(BaseModel):
    id: str = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            + "_"
            + uuid.uuid4().hex[:6]
        )
    )
    agent_type: str
    agent_id: str
    title: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_count: int = 0
    active_task_count: int = 0
```

同文件，在 `TaskStatus` 下方新增：

```python
class InvalidTaskTransitionError(Exception):
    """Raised when a task transition is not permitted."""
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_core_types.py -v
```
Expected: all passed（旧的 Session 测试可能需要更新——见下一步）

- [ ] **Step 5: 修复使用 `agent=` 的旧测试**

搜索所有用到 `Session(... agent=` 的测试文件并修改：

```bash
grep -r "Session(" tests/ --include="*.py" -l
```

对每处 `Session(id="...", agent="sebastian", ...)` 改为 `Session(id="...", agent_type="sebastian", agent_id="sebastian_01", ...)`

- [ ] **Step 6: 运行全量测试确认**

```bash
pytest tests/unit/ -v
```
Expected: all passed（gateway 集成测试此时可能失败，下一步修）

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/types.py tests/unit/
git commit -m "feat(core): split Session.agent into agent_type + agent_id"
```

---

## Task 3: SessionStore + IndexStore 适配新 Session 字段

**Files:**
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/store/index_store.py`
- Modify: `tests/unit/test_session_store.py`
- Modify: `tests/unit/test_index_store.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/test_session_store.py
@pytest.mark.asyncio
async def test_session_store_uses_agent_type_and_id(tmp_path):
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    session = Session(agent_type="stock", agent_id="stock_01", title="test session")
    await store.create_session(session)

    retrieved = await store.get_session(session.id, agent_type="stock", agent_id="stock_01")
    assert retrieved is not None
    assert retrieved.agent_type == "stock"
    assert retrieved.agent_id == "stock_01"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_session_store.py::test_session_store_uses_agent_type_and_id -v
```
Expected: FAIL

- [ ] **Step 3: 修改 `sebastian/store/session_store.py`**

替换 `_session_dir` 和 `_session_dir_by_id` 函数：

```python
def _session_dir(sessions_dir: Path, session: Session) -> Path:
    if session.agent_type == "sebastian":
        directory = sessions_dir / "sebastian" / session.id
    else:
        directory = sessions_dir / "subagents" / session.agent_type / session.agent_id / session.id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tasks").mkdir(exist_ok=True)
    return directory


def _session_dir_by_id(
    sessions_dir: Path, session_id: str, agent_type: str, agent_id: str
) -> Path:
    if agent_type == "sebastian":
        return sessions_dir / "sebastian" / session_id
    return sessions_dir / "subagents" / agent_type / agent_id / session_id
```

将所有方法签名中的 `agent: str = "sebastian"` 替换为 `agent_type: str = "sebastian", agent_id: str = "sebastian_01"`，并将方法内部 `_session_dir_by_id(self._dir, ..., agent)` 替换为 `_session_dir_by_id(self._dir, ..., agent_type, agent_id)`。

`_write_session_meta` 内部改为：
```python
async def _write_session_meta(self, session: Session) -> None:
    directory = _session_dir_by_id(self._dir, session.id, session.agent_type, session.agent_id)
    await self._atomic_write_text(directory / "meta.json", session.model_dump_json())
```

`_session_lock` 改为：
```python
def _session_lock(self, session_id: str, agent_type: str, agent_id: str) -> asyncio.Lock:
    meta_path = (
        _session_dir_by_id(self._dir, session_id, agent_type, agent_id) / "meta.json"
    ).resolve()
    return _SESSION_LOCKS_BY_PATH.setdefault(meta_path, asyncio.Lock())
```

- [ ] **Step 4: 修改 `sebastian/store/index_store.py`**

`upsert` 中的 entry 改为：
```python
entry = {
    "id": session.id,
    "agent_type": session.agent_type,
    "agent_id": session.agent_id,
    "title": session.title,
    "status": session.status.value,
    "updated_at": session.updated_at.isoformat(),
    "task_count": session.task_count,
    "active_task_count": session.active_task_count,
}
```

`list_by_agent` 改为：
```python
async def list_by_agent_type(self, agent_type: str) -> list[dict[str, Any]]:
    return [s for s in await self._read() if s.get("agent_type") == agent_type]

async def list_by_worker(self, agent_type: str, agent_id: str) -> list[dict[str, Any]]:
    return [
        s for s in await self._read()
        if s.get("agent_type") == agent_type and s.get("agent_id") == agent_id
    ]
```

- [ ] **Step 5: 运行确认通过**

```bash
pytest tests/unit/test_session_store.py tests/unit/test_index_store.py -v
```
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/session_store.py sebastian/store/index_store.py tests/unit/test_session_store.py tests/unit/test_index_store.py
git commit -m "feat(store): adapt SessionStore and IndexStore to agent_type + agent_id"
```

---

## Task 4: EventType 补全 block 级事件

**Files:**
- Modify: `sebastian/protocol/events/types.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/test_event_bus.py
def test_block_level_event_types_exist():
    from sebastian.protocol.events.types import EventType
    assert EventType.THINKING_BLOCK_START == "thinking_block.start"
    assert EventType.THINKING_BLOCK_STOP == "thinking_block.stop"
    assert EventType.TEXT_BLOCK_START == "text_block.start"
    assert EventType.TEXT_BLOCK_STOP == "text_block.stop"
    assert EventType.TOOL_BLOCK_START == "tool_block.start"
    assert EventType.TOOL_BLOCK_STOP == "tool_block.stop"
    assert EventType.TURN_THINKING_DELTA == "turn.thinking_delta"
    assert EventType.TURN_INTERRUPTED == "turn.interrupted"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_event_bus.py::test_block_level_event_types_exist -v
```
Expected: FAIL

- [ ] **Step 3: 修改 `sebastian/protocol/events/types.py`**

在 `EventType` 中追加：

```python
class EventType(StrEnum):
    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_PLANNING_STARTED = "task.planning_started"
    TASK_PLANNING_FAILED = "task.planning_failed"
    TASK_STARTED = "task.started"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Agent coordination
    AGENT_DELEGATED = "agent.delegated"
    AGENT_DELEGATED_FAILED = "agent.delegated.failed"
    AGENT_ESCALATED = "agent.escalated"
    AGENT_RESULT_RECEIVED = "agent.result_received"

    # User interaction
    USER_INTERRUPTED = "user.interrupted"
    USER_INTERVENED = "user.intervened"
    USER_APPROVAL_REQUESTED = "user.approval_requested"
    USER_APPROVAL_GRANTED = "user.approval_granted"
    USER_APPROVAL_DENIED = "user.approval_denied"

    # Approval (external names match spec)
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"

    # Tool lifecycle
    TOOL_REGISTERED = "tool.registered"
    TOOL_RUNNING = "tool.running"
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"

    # Conversation — turn level
    TURN_RECEIVED = "turn.received"
    TURN_DELTA = "turn.delta"
    TURN_THINKING_DELTA = "turn.thinking_delta"
    TURN_RESPONSE = "turn.response"
    TURN_INTERRUPTED = "turn.interrupted"

    # Conversation — block level
    THINKING_BLOCK_START = "thinking_block.start"
    THINKING_BLOCK_STOP = "thinking_block.stop"
    TEXT_BLOCK_START = "text_block.start"
    TEXT_BLOCK_STOP = "text_block.stop"
    TOOL_BLOCK_START = "tool_block.start"
    TOOL_BLOCK_STOP = "tool_block.stop"
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_event_bus.py -v
```
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/protocol/events/types.py tests/unit/test_event_bus.py
git commit -m "feat(protocol): add block-level SSE event types"
```

---

## Task 5: AgentLoop → streaming async generator

**Files:**
- Modify: `sebastian/core/agent_loop.py`
- Modify: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: 写失败测试**

```python
# 替换 tests/unit/test_agent_loop.py 全部内容
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager


def _make_stream_ctx(raw_events: list, final_stop_reason: str = "end_turn"):
    """Build a mock context manager returned by client.messages.stream()."""
    mock_stream = MagicMock()
    mock_stream.__aiter__ = MagicMock(return_value=iter(raw_events).__aiter__()
                                       if hasattr(iter(raw_events), '__aiter__')
                                       else _async_iter(raw_events))

    async def _async_gen():
        for e in raw_events:
            yield e

    mock_stream.__aiter__ = _async_gen().__aiter__

    final_msg = MagicMock()
    final_msg.stop_reason = final_stop_reason
    mock_stream.get_final_message = AsyncMock(return_value=final_msg)
    mock_stream.current_message = MagicMock()
    mock_stream.current_message.content = []

    @asynccontextmanager
    async def _ctx():
        yield mock_stream

    return _ctx()


def _text_block_start_event(index: int):
    e = MagicMock()
    e.type = "content_block_start"
    e.index = index
    e.content_block = MagicMock()
    e.content_block.type = "text"
    return e


def _text_delta_event(text: str):
    e = MagicMock()
    e.type = "content_block_delta"
    e.delta = MagicMock()
    e.delta.type = "text_delta"
    e.delta.text = text
    return e


def _content_block_stop_event(index: int, block_type: str = "text", text: str = ""):
    e = MagicMock()
    e.type = "content_block_stop"
    e.index = index
    # Simulate stream.current_message.content[index]
    return e


@pytest.mark.asyncio
async def test_agent_loop_stream_yields_text_deltas():
    """stream() should yield TextBlockStart, TextDelta(s), TextBlockStop, TurnDone."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core.stream_events import TextBlockStart, TextDelta, TextBlockStop, TurnDone

    raw_events = [
        _text_block_start_event(0),
        _text_delta_event("Hello "),
        _text_delta_event("world"),
    ]

    # Patch content_block_stop: build a fake "text" block at index 0
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello world"

    stop_event = MagicMock()
    stop_event.type = "content_block_stop"
    stop_event.index = 0
    raw_events.append(stop_event)

    mock_stream = MagicMock()

    async def _iter():
        for ev in raw_events:
            yield ev

    mock_stream.__aiter__ = lambda self: _iter()
    final_msg = MagicMock()
    final_msg.stop_reason = "end_turn"
    mock_stream.get_final_message = AsyncMock(return_value=final_msg)
    mock_stream.current_message = MagicMock()
    mock_stream.current_message.content = [text_block]

    @asynccontextmanager
    async def _stream_ctx(*args, **kwargs):
        yield mock_stream

    mock_client = MagicMock()
    mock_client.messages.stream = _stream_ctx

    reg = CapabilityRegistry()
    loop = AgentLoop(mock_client, reg)

    collected = []
    gen = loop.stream(system="sys", messages=[{"role": "user", "content": "hi"}])
    async for event in gen:
        collected.append(event)

    types = [type(e).__name__ for e in collected]
    assert "TextBlockStart" in types
    assert "TextDelta" in types
    assert "TextBlockStop" in types
    assert "TurnDone" in types

    deltas = [e for e in collected if isinstance(e, TextDelta)]
    assert deltas[0].delta == "Hello "
    assert deltas[1].delta == "world"

    done = [e for e in collected if isinstance(e, TurnDone)]
    assert done[0].full_text == "Hello world"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_agent_loop.py::test_agent_loop_stream_yields_text_deltas -v
```
Expected: FAIL — `AgentLoop` has no `stream` method

- [ ] **Step 3: 重写 `sebastian/core/agent_loop.py`**

```python
from __future__ import annotations
import logging
from typing import Any, AsyncGenerator

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.stream_events import (
    LLMStreamEvent,
    TextBlockStart, TextDelta, TextBlockStop,
    ThinkingBlockStart, ThinkingDelta, ThinkingBlockStop,
    ToolCallBlockStart, ToolCallReady, ToolResult,
    TurnDone,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20


class AgentLoop:
    """Streaming reasoning loop: yields LLMStreamEvent, supports tool result send()."""

    def __init__(
        self,
        client: Any,
        registry: CapabilityRegistry,
        model: str = "claude-opus-4-6",
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
    ) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
        working = list(messages)
        tools = self._registry.get_all_tool_specs()

        for iteration in range(MAX_ITERATIONS):
            block_index = 0
            full_text = ""
            pending_tool_calls: list[ToolCallReady] = []
            assistant_content: list[dict[str, Any]] = []

            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 16000,
                "system": system,
                "messages": working,
            }
            if tools:
                kwargs["tools"] = tools

            async with self._client.messages.stream(**kwargs) as stream:
                async for raw in stream:
                    block_id = f"b{iteration}_{block_index}"

                    if raw.type == "content_block_start":
                        block_type = raw.content_block.type
                        if block_type == "thinking":
                            yield ThinkingBlockStart(block_id=block_id)
                        elif block_type == "text":
                            yield TextBlockStart(block_id=block_id)
                        elif block_type == "tool_use":
                            yield ToolCallBlockStart(
                                block_id=block_id,
                                tool_id=raw.content_block.id,
                                name=raw.content_block.name,
                            )

                    elif raw.type == "content_block_delta":
                        block_id = f"b{iteration}_{block_index}"
                        delta_type = raw.delta.type
                        if delta_type == "thinking_delta":
                            yield ThinkingDelta(block_id=block_id, delta=raw.delta.thinking)
                        elif delta_type == "text_delta":
                            full_text += raw.delta.text
                            yield TextDelta(block_id=block_id, delta=raw.delta.text)
                        # input_json_delta: accumulate silently, emit at block_stop

                    elif raw.type == "content_block_stop":
                        block_id = f"b{iteration}_{block_index}"
                        block = stream.current_message.content[block_index]
                        if block.type == "thinking":
                            assistant_content.append({
                                "type": "thinking",
                                "thinking": block.thinking,
                            })
                            yield ThinkingBlockStop(block_id=block_id)
                        elif block.type == "text":
                            assistant_content.append({
                                "type": "text",
                                "text": block.text,
                            })
                            yield TextBlockStop(block_id=block_id)
                        elif block.type == "tool_use":
                            tc = ToolCallReady(
                                block_id=block_id,
                                tool_id=block.id,
                                name=block.name,
                                inputs=block.input,
                            )
                            assistant_content.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            })
                            pending_tool_calls.append(tc)
                            tool_result: ToolResult | None = yield tc
                            # tool_result injected via send() from BaseAgent
                        block_index += 1

                final_msg = await stream.get_final_message()

            working.append({"role": "assistant", "content": assistant_content})

            if final_msg.stop_reason != "tool_use":
                yield TurnDone(full_text=full_text)
                return

            # Build tool_result messages for next iteration
            # Results were send()-injected into pending_tool_calls above
            tool_result_messages: list[dict[str, Any]] = []
            for tc in pending_tool_calls:
                # The last send() value for each tc was already yielded
                # We stored results via the generator protocol; rebuild from injected values
                # Note: results are injected one at a time during yield tc above
                pass

            # Collect results via a separate pass — BaseAgent injects via send()
            # pending_tool_calls hold the calls; results arrive as send() values on yield tc
            # To properly collect them, we accumulate in tool_result_msgs below
            # (populated during the block_stop handling above via the send protocol)
            working.append({"role": "user", "content": working.pop()["content"]
                            if False else []})  # placeholder — see note

        logger.warning("Reached MAX_ITERATIONS (%d)", MAX_ITERATIONS)
        yield TurnDone(full_text=full_text)
```

> **Note:** The tool result collection logic needs a cleaner approach. Revise `agent_loop.py` to accumulate tool results correctly:

```python
from __future__ import annotations
import logging
from typing import Any, AsyncGenerator

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.stream_events import (
    LLMStreamEvent, ToolResult,
    TextBlockStart, TextDelta, TextBlockStop,
    ThinkingBlockStart, ThinkingDelta, ThinkingBlockStop,
    ToolCallBlockStart, ToolCallReady, TurnDone,
)

logger = logging.getLogger(__name__)
MAX_ITERATIONS = 20


class AgentLoop:
    def __init__(self, client: Any, registry: CapabilityRegistry, model: str = "claude-opus-4-6") -> None:
        self._client = client
        self._registry = registry
        self._model = model

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
    ) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
        working = list(messages)
        tools = self._registry.get_all_tool_specs()

        for iteration in range(MAX_ITERATIONS):
            block_index = 0
            full_text = ""
            assistant_content: list[dict[str, Any]] = []
            tool_results_for_next: list[dict[str, Any]] = []

            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 16000,
                "system": system,
                "messages": working,
            }
            if tools:
                kwargs["tools"] = tools

            async with self._client.messages.stream(**kwargs) as stream:
                async for raw in stream:
                    block_id = f"b{iteration}_{block_index}"

                    if raw.type == "content_block_start":
                        bt = raw.content_block.type
                        if bt == "thinking":
                            yield ThinkingBlockStart(block_id=block_id)
                        elif bt == "text":
                            yield TextBlockStart(block_id=block_id)
                        elif bt == "tool_use":
                            yield ToolCallBlockStart(
                                block_id=block_id,
                                tool_id=raw.content_block.id,
                                name=raw.content_block.name,
                            )

                    elif raw.type == "content_block_delta":
                        dt = raw.delta.type
                        if dt == "thinking_delta":
                            yield ThinkingDelta(block_id=block_id, delta=raw.delta.thinking)
                        elif dt == "text_delta":
                            full_text += raw.delta.text
                            yield TextDelta(block_id=block_id, delta=raw.delta.text)

                    elif raw.type == "content_block_stop":
                        block = stream.current_message.content[block_index]
                        if block.type == "thinking":
                            assistant_content.append({"type": "thinking", "thinking": block.thinking})
                            yield ThinkingBlockStop(block_id=block_id)
                        elif block.type == "text":
                            assistant_content.append({"type": "text", "text": block.text})
                            yield TextBlockStop(block_id=block_id)
                        elif block.type == "tool_use":
                            tc = ToolCallReady(
                                block_id=block_id,
                                tool_id=block.id,
                                name=block.name,
                                inputs=block.input,
                            )
                            assistant_content.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            })
                            # Yield and receive the ToolResult via send()
                            injected: ToolResult | None = yield tc
                            if injected is not None:
                                tool_results_for_next.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": (
                                        str(injected.output) if injected.ok
                                        else f"Error: {injected.error}"
                                    ),
                                })
                        block_index += 1

                final_msg = await stream.get_final_message()

            working.append({"role": "assistant", "content": assistant_content})

            if final_msg.stop_reason != "tool_use":
                yield TurnDone(full_text=full_text)
                return

            working.append({"role": "user", "content": tool_results_for_next})

        logger.warning("Reached MAX_ITERATIONS (%d)", MAX_ITERATIONS)
        yield TurnDone(full_text=full_text)
```

- [ ] **Step 4: 运行新测试**

```bash
pytest tests/unit/test_agent_loop.py::test_agent_loop_stream_yields_text_deltas -v
```
Expected: PASS

- [ ] **Step 5: 运行全部 agent_loop 测试，修复旧测试**

旧测试使用 `loop.run()`，需改写为消费 `loop.stream()`：

```bash
pytest tests/unit/test_agent_loop.py -v
```

将旧的 `test_agent_loop_no_tools` 和 `test_agent_loop_single_tool_call` 改为：

```python
@pytest.mark.asyncio
async def test_agent_loop_stream_no_tools():
    """stream() with no tool_use: should yield text events and TurnDone."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core.stream_events import TurnDone

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello there!"

    raw_events = [
        _make_content_block_start(0, "text"),
        _make_text_delta("Hello there!"),
        _make_content_block_stop(0),
    ]

    mock_stream, mock_client = _build_mock_client(raw_events, [text_block], "end_turn")
    reg = CapabilityRegistry()
    loop = AgentLoop(mock_client, reg)

    events = []
    async for ev in loop.stream("sys", [{"role": "user", "content": "hi"}]):
        events.append(ev)

    done_events = [e for e in events if isinstance(e, TurnDone)]
    assert len(done_events) == 1
    assert done_events[0].full_text == "Hello there!"
```

Add helpers at top of test file:

```python
def _make_content_block_start(index: int, block_type: str, tool_id: str = "", name: str = ""):
    e = MagicMock()
    e.type = "content_block_start"
    e.index = index
    e.content_block = MagicMock()
    e.content_block.type = block_type
    e.content_block.id = tool_id
    e.content_block.name = name
    return e

def _make_text_delta(text: str):
    e = MagicMock()
    e.type = "content_block_delta"
    e.delta = MagicMock()
    e.delta.type = "text_delta"
    e.delta.text = text
    return e

def _make_content_block_stop(index: int):
    e = MagicMock()
    e.type = "content_block_stop"
    e.index = index
    return e

def _build_mock_client(raw_events, content_blocks, stop_reason):
    from contextlib import asynccontextmanager
    mock_stream = MagicMock()
    async def _iter():
        for ev in raw_events:
            yield ev
    mock_stream.__aiter__ = lambda s: _iter()
    final_msg = MagicMock()
    final_msg.stop_reason = stop_reason
    mock_stream.get_final_message = AsyncMock(return_value=final_msg)
    mock_stream.current_message = MagicMock()
    mock_stream.current_message.content = content_blocks

    @asynccontextmanager
    async def _stream_ctx(*args, **kwargs):
        yield mock_stream

    mock_client = MagicMock()
    mock_client.messages.stream = _stream_ctx
    return mock_stream, mock_client
```

- [ ] **Step 6: 运行确认全部通过**

```bash
pytest tests/unit/test_agent_loop.py -v
```
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add sebastian/core/agent_loop.py tests/unit/test_agent_loop.py
git commit -m "feat(core): rewrite AgentLoop as streaming async generator"
```

---

## Task 6: Task 状态机 _transition() + 合法性校验

**Files:**
- Modify: `sebastian/core/task_manager.py`
- Modify: `tests/unit/test_task_manager.py` (or create if not detailed enough)

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/test_task_manager.py（或新建）
@pytest.mark.asyncio
async def test_invalid_task_transition_raises(tmp_path):
    from sebastian.core.types import Task, TaskStatus, InvalidTaskTransitionError
    from sebastian.core.task_manager import TaskManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore
    from sebastian.core.types import Session

    store = SessionStore(tmp_path / "sessions")
    bus = EventBus()
    manager = TaskManager(store, bus)

    session = Session(agent_type="sebastian", agent_id="sebastian_01", title="t")
    await store.create_session(session)
    task = Task(session_id=session.id, goal="test", assigned_agent="sebastian_01")
    await store.create_task(task)

    # CREATED → RUNNING is illegal (must go through PLANNING)
    with pytest.raises(InvalidTaskTransitionError):
        await manager._transition(task, TaskStatus.RUNNING)


@pytest.mark.asyncio
async def test_terminal_state_cannot_transition(tmp_path):
    from sebastian.core.types import Task, TaskStatus, InvalidTaskTransitionError
    from sebastian.core.task_manager import TaskManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore
    from sebastian.core.types import Session

    store = SessionStore(tmp_path / "sessions")
    bus = EventBus()
    manager = TaskManager(store, bus)

    session = Session(agent_type="sebastian", agent_id="sebastian_01", title="t")
    await store.create_session(session)
    task = Task(session_id=session.id, goal="test", assigned_agent="sebastian_01",
                status=TaskStatus.COMPLETED)

    with pytest.raises(InvalidTaskTransitionError):
        await manager._transition(task, TaskStatus.RUNNING)
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_task_manager.py -k "transition" -v
```
Expected: FAIL

- [ ] **Step 3: 修改 `sebastian/core/task_manager.py`**

在文件顶部导入后，添加：

```python
from datetime import datetime, timezone
from sebastian.core.types import Task, TaskStatus, InvalidTaskTransitionError
from sebastian.protocol.events.types import Event, EventType

_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED:   {TaskStatus.PLANNING},
    TaskStatus.PLANNING:  {TaskStatus.RUNNING, TaskStatus.FAILED},
    TaskStatus.RUNNING:   {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED:    set(),
    TaskStatus.CANCELLED: set(),
}

_STATUS_TO_EVENT: dict[TaskStatus, EventType] = {
    TaskStatus.PLANNING:   EventType.TASK_PLANNING_STARTED,
    TaskStatus.RUNNING:    EventType.TASK_STARTED,
    TaskStatus.COMPLETED:  EventType.TASK_COMPLETED,
    TaskStatus.FAILED:     EventType.TASK_FAILED,
    TaskStatus.CANCELLED:  EventType.TASK_CANCELLED,
}
```

新增 `_transition` 方法（替换旧的内联状态更新逻辑）：

```python
async def _transition(
    self,
    task: Task,
    new_status: TaskStatus,
    error: str | None = None,
) -> None:
    allowed = _VALID_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise InvalidTaskTransitionError(
            f"Cannot transition task {task.id} from {task.status} to {new_status}"
        )
    task.status = new_status
    task.updated_at = datetime.now(timezone.utc)
    if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        task.completed_at = task.updated_at
    await self._store.update_task_status(
        task.session_id, task.id, new_status, task.assigned_agent
    )
    await self._sync_index(task.session_id, task.assigned_agent)
    event_type = _STATUS_TO_EVENT.get(new_status)
    if event_type:
        data: dict = {"task_id": task.id, "session_id": task.session_id}
        if error:
            data["error"] = error
        await self._bus.publish(Event(type=event_type, data=data))
```

修改 `_run()` 内部使用 `_transition`：

```python
async def _run() -> None:
    await self._transition(task, TaskStatus.PLANNING)
    await self._transition(task, TaskStatus.RUNNING)
    try:
        await fn(task)
        await self._transition(task, TaskStatus.COMPLETED)
    except asyncio.CancelledError:
        await self._transition(task, TaskStatus.CANCELLED)
        raise
    except Exception as exc:
        logger.exception("Task %s failed", task.id)
        await self._transition(task, TaskStatus.FAILED, error=str(exc))
    finally:
        self._running.pop(task.id, None)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_task_manager.py -v
```
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/task_manager.py tests/unit/test_task_manager.py
git commit -m "feat(core): add TaskManager._transition with state machine validation"
```

---

## Task 7: AgentPool worker 槽位管理

**Files:**
- Create: `sebastian/core/agent_pool.py`
- Create: `tests/unit/test_agent_pool.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_agent_pool.py
from __future__ import annotations
import asyncio
import pytest


@pytest.mark.asyncio
async def test_agent_pool_acquire_idle_worker():
    from sebastian.core.agent_pool import AgentPool, WorkerStatus
    pool = AgentPool("stock")
    worker_id = await pool.acquire()
    assert worker_id == "stock_01"
    assert pool.status()[worker_id] == WorkerStatus.BUSY


@pytest.mark.asyncio
async def test_agent_pool_release_worker():
    from sebastian.core.agent_pool import AgentPool, WorkerStatus
    pool = AgentPool("stock")
    worker_id = await pool.acquire()
    pool.release(worker_id)
    assert pool.status()[worker_id] == WorkerStatus.IDLE


@pytest.mark.asyncio
async def test_agent_pool_all_busy_queues():
    from sebastian.core.agent_pool import AgentPool
    pool = AgentPool("stock")
    # Acquire all 3
    w1 = await pool.acquire()
    w2 = await pool.acquire()
    w3 = await pool.acquire()
    assert pool.queue_depth == 0

    # 4th acquire should queue
    acquire_task = asyncio.create_task(pool.acquire())
    await asyncio.sleep(0)  # let task start
    assert pool.queue_depth == 1

    # Release one → queued task gets it
    pool.release(w1)
    w4 = await acquire_task
    assert w4 == w1
    assert pool.queue_depth == 0


@pytest.mark.asyncio
async def test_agent_pool_worker_names():
    from sebastian.core.agent_pool import AgentPool
    pool = AgentPool("code")
    workers = list(pool.status().keys())
    assert workers == ["code_01", "code_02", "code_03"]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_agent_pool.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 创建 `sebastian/core/agent_pool.py`**

```python
from __future__ import annotations
import asyncio
import logging
from enum import StrEnum

logger = logging.getLogger(__name__)


class WorkerStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"


class AgentPool:
    """Fixed worker-slot pool for one agent_type. Max 3 concurrent workers."""

    MAX_WORKERS: int = 3

    def __init__(self, agent_type: str) -> None:
        self._agent_type = agent_type
        self._workers: dict[str, WorkerStatus] = {
            f"{agent_type}_{i:02d}": WorkerStatus.IDLE
            for i in range(1, self.MAX_WORKERS + 1)
        }
        self._queue: asyncio.Queue[asyncio.Future[str]] = asyncio.Queue()

    async def acquire(self) -> str:
        """Return an idle worker_id. Suspends if all workers are busy."""
        for worker_id, status in self._workers.items():
            if status == WorkerStatus.IDLE:
                self._workers[worker_id] = WorkerStatus.BUSY
                return worker_id
        fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        await self._queue.put(fut)
        logger.debug("All %s workers busy, queuing (depth=%d)", self._agent_type, self._queue.qsize())
        return await fut

    def release(self, worker_id: str) -> None:
        """Release a worker back to the pool. Assigns to next queued waiter if any."""
        if not self._queue.empty():
            fut = self._queue.get_nowait()
            if not fut.done():
                fut.set_result(worker_id)
                return
        self._workers[worker_id] = WorkerStatus.IDLE

    def status(self) -> dict[str, WorkerStatus]:
        return dict(self._workers)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_agent_pool.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/agent_pool.py tests/unit/test_agent_pool.py
git commit -m "feat(core): add AgentPool with fixed worker slots and queue"
```

---

## Task 8: BaseAgent run_streaming() + 打断机制

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `tests/unit/test_base_agent.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/test_base_agent.py
@pytest.mark.asyncio
async def test_run_streaming_publishes_turn_events(tmp_path):
    """run_streaming() should publish TURN_RECEIVED and TURN_RESPONSE via EventBus."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    bus = EventBus()
    session = Session(agent_type="sebastian", agent_id="sebastian_01", title="test")
    await store.create_session(session)

    collected_events = []
    async def capture(event):
        collected_events.append(event)
    bus.subscribe(capture)

    mock_client = MagicMock()
    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        agent = TestAgent(CapabilityRegistry(), store, bus)

    # Patch _loop.stream to yield a simple TurnDone
    from sebastian.core.stream_events import TurnDone
    async def _fake_stream(*a, **kw):
        yield TurnDone(full_text="response text")
    agent._loop.stream = _fake_stream

    await agent.run_streaming("hello", session.id)

    types = [e.type for e in collected_events]
    assert EventType.TURN_RECEIVED in types
    assert EventType.TURN_RESPONSE in types


@pytest.mark.asyncio
async def test_run_streaming_interrupt_publishes_interrupted(tmp_path):
    """Cancelling an active stream publishes TURN_INTERRUPTED."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    bus = EventBus()
    session = Session(agent_type="sebastian", agent_id="sebastian_01", title="test")
    await store.create_session(session)

    collected_events = []
    async def capture(event):
        collected_events.append(event)
    bus.subscribe(capture)

    mock_client = MagicMock()
    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        agent = TestAgent(CapabilityRegistry(), store, bus)

    # Fake a slow stream that yields text deltas then hangs
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    async def _slow_stream(*a, **kw):
        yield TextBlockStart(block_id="b0_0")
        yield TextDelta(block_id="b0_0", delta="partial")
        await asyncio.sleep(10)  # hang until cancelled

    agent._loop.stream = _slow_stream

    # Start streaming in background, then cancel it
    stream_task = asyncio.create_task(agent.run_streaming("hello", session.id))
    await asyncio.sleep(0.05)
    stream_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stream_task

    types = [e.type for e in collected_events]
    assert EventType.TURN_INTERRUPTED in types
    interrupted = next(e for e in collected_events if e.type == EventType.TURN_INTERRUPTED)
    assert interrupted.data["partial_content"] == "partial"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_base_agent.py -k "streaming" -v
```
Expected: FAIL

- [ ] **Step 3: 重写 `sebastian/core/base_agent.py`**

```python
from __future__ import annotations
import asyncio
import dataclasses
import logging
from abc import ABC
from typing import ClassVar

import anthropic

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.agent_loop import AgentLoop
from sebastian.core.stream_events import (
    TextDelta, TurnDone, ToolCallReady, ToolResult,
    ThinkingBlockStart, ThinkingDelta, ThinkingBlockStop,
    TextBlockStart, TextBlockStop,
    ToolCallBlockStart,
)
from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.memory.working_memory import WorkingMemory
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType
from sebastian.store.session_store import SessionStore

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = (
    "You are Sebastian, a personal AI butler. You are helpful, precise, and action-oriented. "
    "You have access to tools and will use them when needed. "
    "Think step by step, act efficiently, and always confirm important actions before executing."
)

_EVENT_MAP: dict[type, EventType] = {
    ThinkingBlockStart: EventType.THINKING_BLOCK_START,
    ThinkingDelta:      EventType.TURN_THINKING_DELTA,
    ThinkingBlockStop:  EventType.THINKING_BLOCK_STOP,
    TextBlockStart:     EventType.TEXT_BLOCK_START,
    TextDelta:          EventType.TURN_DELTA,
    TextBlockStop:      EventType.TEXT_BLOCK_STOP,
    ToolCallBlockStart: EventType.TOOL_BLOCK_START,
}


class BaseAgent(ABC):
    name: str = "base_agent"
    system_prompt: str = BASE_SYSTEM_PROMPT

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        model: str | None = None,
    ) -> None:
        self._registry = registry
        self._session_store = session_store
        self._event_bus = event_bus
        self._episodic = EpisodicMemory(session_store)
        self.working_memory = WorkingMemory()
        self._active_stream: asyncio.Task | None = None

        from sebastian.config import settings
        resolved_model = model or settings.sebastian_model
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._loop = AgentLoop(self._client, registry, resolved_model)

    async def run_streaming(
        self,
        user_message: str,
        session_id: str,
        task_id: str | None = None,
    ) -> None:
        """Stream a turn through EventBus. Cancels any active stream first."""
        if self._active_stream and not self._active_stream.done():
            self._active_stream.cancel()
            try:
                await self._active_stream
            except (asyncio.CancelledError, Exception):
                pass

        await self._publish(session_id, EventType.TURN_RECEIVED, {"agent_id": self.name})

        turns = await self._episodic.get_turns(session_id, agent=self.name, limit=20)
        messages = [{"role": t.role, "content": t.content} for t in turns]
        messages.append({"role": "user", "content": user_message})
        await self._episodic.add_turn(session_id, "user", user_message, agent=self.name)

        self._active_stream = asyncio.create_task(
            self._stream_inner(messages, session_id, task_id)
        )
        await self._active_stream

    async def _stream_inner(
        self,
        messages: list[dict],
        session_id: str,
        task_id: str | None,
    ) -> None:
        full_text = ""
        gen = self._loop.stream(self.system_prompt, messages)
        send_val: ToolResult | None = None

        try:
            while True:
                try:
                    event = await gen.asend(send_val)
                    send_val = None
                except StopAsyncIteration:
                    break

                if isinstance(event, ToolCallReady):
                    await self._publish(session_id, EventType.TOOL_BLOCK_STOP, {
                        "block_id": event.block_id,
                        "tool_id": event.tool_id,
                        "name": event.name,
                        "inputs": event.inputs,
                    })
                    await self._publish(session_id, EventType.TOOL_RUNNING, {
                        "tool_id": event.tool_id,
                        "name": event.name,
                    })
                    result = await self._registry.call(event.name, **event.inputs)
                    tool_result = ToolResult(
                        tool_id=event.tool_id,
                        name=event.name,
                        ok=result.ok,
                        output=result.output,
                        error=result.error,
                    )
                    evt_type = EventType.TOOL_EXECUTED if result.ok else EventType.TOOL_FAILED
                    extra = (
                        {"result_summary": str(result.output)[:200]}
                        if result.ok
                        else {"error": result.error}
                    )
                    await self._publish(session_id, evt_type, {
                        "tool_id": event.tool_id, "name": event.name, **extra
                    })
                    send_val = tool_result
                    continue

                if isinstance(event, TurnDone):
                    await self._episodic.add_turn(
                        session_id, "assistant", event.full_text, agent=self.name
                    )
                    await self._publish(session_id, EventType.TURN_RESPONSE, {
                        "content": event.full_text,
                        "interrupted": False,
                    })
                    return

                if isinstance(event, TextDelta):
                    full_text += event.delta

                if evt_type := _EVENT_MAP.get(type(event)):
                    await self._publish(session_id, evt_type, dataclasses.asdict(event))

        except asyncio.CancelledError:
            await self._episodic.add_turn(
                session_id, "assistant", full_text, agent=self.name
            )
            await self._publish(session_id, EventType.TURN_INTERRUPTED, {
                "partial_content": full_text,
            })
            raise

    async def run(
        self,
        user_message: str,
        session_id: str,
        task_id: str | None = None,
        agent_name: str | None = None,
    ) -> str:
        """Non-streaming run for background tasks. Returns full response text."""
        agent_context = agent_name or self.name
        turns = await self._episodic.get_turns(session_id, agent=agent_context, limit=20)
        messages = [{"role": t.role, "content": t.content} for t in turns]
        messages.append({"role": "user", "content": user_message})
        await self._episodic.add_turn(session_id, "user", user_message, agent=agent_context)

        full_text = ""
        gen = self._loop.stream(self.system_prompt, messages)
        send_val: ToolResult | None = None
        while True:
            try:
                event = await gen.asend(send_val)
                send_val = None
            except StopAsyncIteration:
                break
            if isinstance(event, ToolCallReady):
                result = await self._registry.call(event.name, **event.inputs)
                send_val = ToolResult(
                    tool_id=event.tool_id, name=event.name,
                    ok=result.ok, output=result.output, error=result.error,
                )
            elif isinstance(event, TurnDone):
                full_text = event.full_text
                break
            elif isinstance(event, TextDelta):
                full_text += event.delta

        await self._episodic.add_turn(session_id, "assistant", full_text, agent=agent_context)
        return full_text

    async def _publish(self, session_id: str, event_type: EventType, data: dict) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(Event(
            type=event_type,
            data={"session_id": session_id, **data},
        ))
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_base_agent.py -v
```
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent.py
git commit -m "feat(core): add BaseAgent.run_streaming with interrupt mechanism"
```

---

## Task 9: SSEManager — event id + 缓冲 + session 过滤

**Files:**
- Modify: `sebastian/gateway/sse.py`
- Modify: `tests/unit/test_sse_manager.py`

- [ ] **Step 1: 写失败测试**

```python
# 替换 tests/unit/test_sse_manager.py
from __future__ import annotations
import asyncio
import json
import pytest


@pytest.mark.asyncio
async def test_sse_event_has_id_field():
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    manager = SSEManager(bus)
    gen = manager.stream()
    task = asyncio.create_task(anext(gen))
    await asyncio.sleep(0)
    await bus.publish(Event(type=EventType.TURN_RESPONSE, data={"session_id": "s1"}))
    chunk = await task
    assert chunk.startswith("id: ")
    lines = chunk.strip().split("\n")
    assert lines[0].startswith("id: ")
    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload["type"] == "turn.response"


@pytest.mark.asyncio
async def test_sse_session_stream_filters_by_session():
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    manager = SSEManager(bus)

    # Subscribe to session s1 only
    gen = manager.stream(session_id="s1")
    task = asyncio.create_task(anext(gen))
    await asyncio.sleep(0)

    # Publish event for s2 — should be filtered
    await bus.publish(Event(type=EventType.TURN_DELTA, data={"session_id": "s2", "delta": "x"}))
    await asyncio.sleep(0)

    # Publish event for s1 — should arrive
    await bus.publish(Event(type=EventType.TURN_DELTA, data={"session_id": "s1", "delta": "y"}))
    chunk = await task
    payload = json.loads(chunk.split("\n")[1].removeprefix("data: "))
    assert payload["data"]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_sse_reconnect_replays_from_last_event_id():
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    manager = SSEManager(bus)

    # Publish 3 events before connecting
    for i in range(3):
        await bus.publish(Event(type=EventType.TURN_DELTA, data={"session_id": "s1", "n": i}))

    # Connect with Last-Event-ID = 1 (replay from event 2 onward)
    chunks = []
    gen = manager.stream(last_event_id=1)
    for _ in range(2):
        try:
            chunks.append(await asyncio.wait_for(anext(gen), timeout=0.5))
        except asyncio.TimeoutError:
            break

    assert len(chunks) == 2
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_sse_manager.py -v
```
Expected: FAIL

- [ ] **Step 3: 重写 `sebastian/gateway/sse.py`**

```python
from __future__ import annotations
import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncGenerator

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event

logger = logging.getLogger(__name__)

BUFFER_SIZE = 500


class SSEManager:
    """Manages SSE client connections with event id, replay buffer, session filtering."""

    def __init__(self, event_bus: EventBus) -> None:
        self._queues: list[tuple[asyncio.Queue[Event | None], str | None]] = []
        self._buffer: deque[tuple[int, Event]] = deque(maxlen=BUFFER_SIZE)
        self._counter: int = 0
        event_bus.subscribe(self._on_event)

    async def _on_event(self, event: Event) -> None:
        self._counter += 1
        seq = self._counter
        self._buffer.append((seq, event))
        for q, session_filter in list(self._queues):
            if session_filter and event.data.get("session_id") != session_filter:
                continue
            try:
                q.put_nowait((seq, event))
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event %s", event.type)

    async def stream(
        self,
        session_id: str | None = None,
        last_event_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        q: asyncio.Queue[tuple[int, Event] | None] = asyncio.Queue(maxsize=200)
        self._queues.append((q, session_id))

        # Replay buffered events after last_event_id
        if last_event_id is not None:
            for seq, event in self._buffer:
                if seq <= last_event_id:
                    continue
                if session_id and event.data.get("session_id") != session_id:
                    continue
                q.put_nowait((seq, event))

        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                seq, event = item
                payload = json.dumps({
                    "type": event.type.value,
                    "data": event.data | {"ts": event.ts.isoformat()},
                })
                yield f"id: {seq}\ndata: {payload}\n\n"
        finally:
            self._queues = [(q2, f) for q2, f in self._queues if q2 is not q]
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_sse_manager.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/sse.py tests/unit/test_sse_manager.py
git commit -m "feat(gateway): SSEManager with event id, replay buffer, session filter"
```

---

## Task 10: Gateway 路由更新

**Files:**
- Modify: `sebastian/gateway/routes/turns.py`
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/gateway/routes/agents.py`
- Modify: `sebastian/gateway/routes/stream.py`

- [ ] **Step 1: 修改 `sebastian/gateway/routes/turns.py`**

```python
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sebastian.gateway.auth import create_access_token, require_auth, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(tags=["turns"])


class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SendTurnRequest(BaseModel):
    content: str
    session_id: str | None = None


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    from sebastian.config import settings
    stored_hash = settings.sebastian_owner_password_hash
    if not stored_hash or not verify_password(body.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = create_access_token({"sub": settings.sebastian_owner_name, "role": "owner"})
    return TokenResponse(access_token=token)


@router.post("/turns")
async def send_turn(
    body: SendTurnRequest,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state

    session = await state.sebastian.get_or_create_session(body.session_id, body.content)
    # Non-blocking: fire and forget, content arrives via SSE
    asyncio.create_task(state.sebastian.run_streaming(body.content, session.id))
    return {
        "session_id": session.id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 2: 修改 `sebastian/gateway/routes/sessions.py`**

```python
from __future__ import annotations
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["sessions"])


@router.get("/sessions")
async def list_sessions(
    agent_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    sessions = await state.index_store.list_all()
    if agent_type:
        sessions = [s for s in sessions if s.get("agent_type") == agent_type]
    if status:
        sessions = [s for s in sessions if s.get("status") == status]
    total = len(sessions)
    return {"sessions": sessions[offset: offset + limit], "total": total}


@router.get("/agents/{agent_type}/sessions")
async def list_agent_type_sessions(
    agent_type: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    sessions = await state.index_store.list_by_agent_type(agent_type)
    return {"agent_type": agent_type, "sessions": sessions}


@router.get("/agents/{agent_type}/workers/{agent_id}/sessions")
async def list_worker_sessions(
    agent_type: str,
    agent_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    sessions = await state.index_store.list_by_worker(agent_type, agent_id)
    return {"agent_type": agent_type, "agent_id": agent_id, "sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    agent_type: str = "sebastian",
    agent_id: str = "sebastian_01",
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    session = await state.session_store.get_session(
        session_id, agent_type=agent_type, agent_id=agent_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await state.session_store.get_messages(
        session_id, agent_type=agent_type, agent_id=agent_id, limit=50
    )
    return {"session": session.model_dump(mode="json"), "messages": messages}


class SendTurnBody(BaseModel):
    content: str


@router.post("/sessions/{session_id}/turns")
async def send_turn_to_session(
    session_id: str,
    body: SendTurnBody,
    agent_type: str = "sebastian",
    agent_id: str = "sebastian_01",
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    session = await state.session_store.get_session(
        session_id, agent_type=agent_type, agent_id=agent_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    asyncio.create_task(state.sebastian.run_streaming(body.content, session_id))

    from sebastian.protocol.events.bus import bus
    from sebastian.protocol.events.types import Event, EventType
    await bus.publish(Event(
        type=EventType.USER_INTERVENED,
        data={"agent_type": agent_type, "agent_id": agent_id,
              "session_id": session_id, "message": body.content[:200]},
    ))
    return {"session_id": session_id, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/sessions/{session_id}/tasks")
async def list_session_tasks(
    session_id: str,
    agent_type: str = "sebastian",
    agent_id: str = "sebastian_01",
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    tasks = await state.session_store.list_tasks(
        session_id, agent_type=agent_type, agent_id=agent_id
    )
    return {"tasks": [t.model_dump(mode="json") for t in tasks]}


@router.get("/sessions/{session_id}/tasks/{task_id}")
async def get_task(
    session_id: str,
    task_id: str,
    agent_type: str = "sebastian",
    agent_id: str = "sebastian_01",
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    task = await state.session_store.get_task(
        session_id, task_id, agent_type=agent_type, agent_id=agent_id
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.model_dump(mode="json")


@router.post("/sessions/{session_id}/tasks/{task_id}/cancel")
async def cancel_task(
    session_id: str,
    task_id: str,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    from sebastian.core.types import InvalidTaskTransitionError
    try:
        cancelled = await state.sebastian._task_manager.cancel(task_id)
    except InvalidTaskTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e), headers={"X-Error-Code": "INVALID_TASK_TRANSITION"})
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found or not running")
    return {"ok": True}
```

- [ ] **Step 3: 修改 `sebastian/gateway/routes/agents.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents(_auth: dict = Depends(require_auth)) -> dict:
    import sebastian.gateway.state as state
    agents = []
    for agent_type, pool in state.agent_pools.items():
        worker_status = pool.status()
        workers = [
            {
                "agent_id": wid,
                "status": status.value,
                "session_id": state.worker_sessions.get(wid),
            }
            for wid, status in worker_status.items()
        ]
        agents.append({
            "agent_type": agent_type,
            "workers": workers,
            "queue_depth": pool.queue_depth,
        })
    return {"agents": agents}


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 4: 修改 `sebastian/gateway/routes/stream.py` 支持 session 级别 SSE**

```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def global_stream(
    request: Request,
    last_event_id: int | None = None,
    _auth: dict = Depends(require_auth),
) -> StreamingResponse:
    import sebastian.gateway.state as state

    async def event_generator():
        async for chunk in state.sse_manager.stream(last_event_id=last_event_id):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/stream")
async def session_stream(
    session_id: str,
    request: Request,
    last_event_id: int | None = None,
    _auth: dict = Depends(require_auth),
) -> StreamingResponse:
    import sebastian.gateway.state as state

    async def event_generator():
        async for chunk in state.sse_manager.stream(
            session_id=session_id, last_event_id=last_event_id
        ):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 5: 更新 `sebastian/gateway/state.py` 添加 agent_pools + worker_sessions**

```python
# 在 state.py 中新增（现有内容保留）
from sebastian.core.agent_pool import AgentPool

# 在 init 函数或全局变量中增加：
agent_pools: dict[str, AgentPool] = {}
worker_sessions: dict[str, str | None] = {}   # worker_id → current session_id
```

- [ ] **Step 6: 运行全量测试**

```bash
pytest tests/ -v --tb=short
```

修复任何因接口变更导致的失败（主要是集成测试里硬编码了 `agent=` 的地方）。

- [ ] **Step 7: Commit**

```bash
git add sebastian/gateway/routes/ sebastian/gateway/state.py
git commit -m "feat(gateway): update routes for agent_type/agent_id, non-blocking turns, session SSE"
```

---

## Task 11: Sebastian orchestrator 适配

**Files:**
- Modify: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: 修改 `sebastian/orchestrator/sebas.py`**

`get_or_create_session` 中 `Session(agent=...)` 改为 `Session(agent_type="sebastian", agent_id="sebastian_01", ...)`：

```python
async def get_or_create_session(
    self, session_id: str | None, first_message: str
) -> Session:
    if session_id:
        existing = await self._session_store.get_session(
            session_id, agent_type="sebastian", agent_id="sebastian_01"
        )
        if existing is not None:
            existing.updated_at = datetime.now(timezone.utc)
            await self._session_store.update_session(existing)
            await self._index.upsert(existing)
            return existing

    session = Session(
        agent_type="sebastian",
        agent_id="sebastian_01",
        title=first_message[:40],
    )
    await self._session_store.create_session(session)
    await self._index.upsert(session)
    return session
```

`chat()` 改为调用 `run_streaming()`：

```python
async def chat(self, user_message: str, session_id: str) -> None:
    """Non-blocking: starts streaming, returns immediately. Content arrives via SSE."""
    await self.run_streaming(user_message, session_id)
```

- [ ] **Step 2: 修复 sebas 单元测试**

```bash
pytest tests/unit/test_sebas.py -v
```

将测试中 `Session(agent="sebastian", ...)` 全部改为 `Session(agent_type="sebastian", agent_id="sebastian_01", ...)`。

- [ ] **Step 3: 运行全量测试**

```bash
pytest tests/ -v --tb=short
```
Expected: all passed

- [ ] **Step 4: Commit**

```bash
git add sebastian/orchestrator/sebas.py tests/unit/test_sebas.py
git commit -m "feat(orchestrator): adapt Sebastian to run_streaming and agent_type/agent_id"
```

---

## Task 12: 全量验证

- [ ] **Step 1: 运行完整测试套件**

```bash
pytest tests/ -v
```
Expected: all passed, 0 failures

- [ ] **Step 2: 运行 lint**

```bash
ruff check sebastian/ tests/
mypy sebastian/ --ignore-missing-imports
```

修复所有错误。

- [ ] **Step 3: 手动冒烟测试（可选，有 gateway 环境时）**

```bash
# 启动 gateway
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload

# 登录
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"your-password"}' | jq .

# 发送消息（非阻塞，立即返回）
curl -s -X POST http://127.0.0.1:8000/api/v1/turns \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"hello"}' | jq .
# Expected: {"session_id":"...","ts":"..."}

# 监听 SSE 事件流
curl -N http://127.0.0.1:8000/api/v1/stream \
  -H "Authorization: Bearer TOKEN"
# Expected: stream of id:/data: events including turn.received, turn.delta, turn.response
```

- [ ] **Step 4: 最终 commit**

```bash
git add -A
git commit -m "chore: final cleanup after Phase 1 core runtime implementation"
```

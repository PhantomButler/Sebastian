# Android PENDING 状态与即时停止 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Android 对话页消除"发送完到首字到达"的视觉空窗，让用户全程有反馈且可即时停止；修复后端 `_active_streams` 登记前的 cancel 竞态。

**Architecture:** 后端 `BaseAgent` 增加 `_pending_cancel_intents` 预取消字典 + 60s TTL，堵住 REST 返回到 stream 登记的竞态。前端合并 `ComposerState.SENDING` 到 `PENDING`，新增 `AgentAnimState.PENDING`，顶部胶囊新增 BREATHING（彩虹呼吸）档位，SendButton 在 PENDING 下即显示可点停止，补 `turn.cancelled` 事件消费路径。

**Tech Stack:** Python 3.12 + asyncio + FastAPI；Kotlin + Jetpack Compose + Hilt；JUnit4 + mockito-kotlin + Turbine；pytest + pytest-asyncio。

**Spec:** [docs/superpowers/specs/2026-04-17-android-pending-state-design.md](../specs/2026-04-17-android-pending-state-design.md)

---

## Part A — 后端：`_pending_cancel_intents` 竞态兜底

### Task 1: `cancel_session` 在流未登记时写入预取消

**Files:**
- Modify: `sebastian/core/base_agent.py:120-125`（成员初始化）
- Modify: `sebastian/core/base_agent.py:606-634`（`cancel_session` 方法）
- Test: `tests/unit/core/test_base_agent_pending_cancel.py`（新建）

- [ ] **Step 1: 写失败的单测 — `cancel_session` 对未登记 stream 返回 True 并写入预取消**

文件：`tests/unit/core/test_base_agent_pending_cancel.py`

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sebastian.core.base_agent import BaseAgent
from sebastian.core.types import Session
from sebastian.store.session_store import SessionStore


@pytest.fixture
async def agent(tmp_path: Path):
    class DummyAgent(BaseAgent):
        name = "sebastian"

    session_store = SessionStore(tmp_path / "sessions")
    await session_store.create_session(Session(id="s1", agent_type="sebastian", title="S1"))
    gate = MagicMock()
    return DummyAgent(gate=gate, session_store=session_store)


@pytest.mark.asyncio
async def test_cancel_session_registers_pending_when_no_active_stream(agent) -> None:
    # No run_streaming has been invoked; _active_streams is empty.
    cancelled = await agent.cancel_session("s1", intent="cancel")

    assert cancelled is True
    assert agent._pending_cancel_intents["s1"] == "cancel"


@pytest.mark.asyncio
async def test_cancel_session_registers_pending_with_stop_intent(agent) -> None:
    cancelled = await agent.cancel_session("s1", intent="stop")

    assert cancelled is True
    assert agent._pending_cancel_intents["s1"] == "stop"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/core/test_base_agent_pending_cancel.py -v`
Expected: FAIL — `AttributeError: 'DummyAgent' object has no attribute '_pending_cancel_intents'`

- [ ] **Step 3: 在 BaseAgent 加字段 + cancel_session 分支**

Edit `sebastian/core/base_agent.py`：

在 `__init__`（约 line 120-125）字段列表末尾新增：

```python
self._active_streams: dict[str, asyncio.Task[str]] = {}  # session_id → task
# session_id → intent: "cancel" ends as cancelled; "stop" keeps context for resume.
self._cancel_requested: dict[str, CancelIntent] = {}
# session_id → completed cancel intent, available for outer consumers after teardown.
self._completed_cancel_intents: dict[str, CancelIntent] = {}
# session_id → pre-cancel intent registered before the stream task is live.
# Consumed by run_streaming immediately after registering _active_streams.
self._pending_cancel_intents: dict[str, CancelIntent] = {}
# session_id → asyncio.TimerHandle for pending-cancel TTL cleanup
self._pending_cancel_timers: dict[str, asyncio.TimerHandle] = {}
self._partial_buffer: dict[str, str] = {}
```

改 `cancel_session`（约 line 606-634），把 "no active stream → return False" 分支替换为"写入 pending"：

```python
async def cancel_session(self, session_id: str, intent: CancelIntent = "cancel") -> bool:
    """Cancel the active streaming turn for session_id.

    If no stream is registered yet (race between REST return and
    run_streaming registering _active_streams), record the intent in
    _pending_cancel_intents so run_streaming consumes it on registration.

    Returns True if a stream was cancelled OR a pending cancel was registered;
    False only if the intent is invalid (raised) — never silently False.
    """
    validated_intent = self._validate_cancel_intent(intent)
    stream = self._active_streams.get(session_id)
    if stream is None or stream.done():
        # Pre-cancel: run_streaming will consume this on _active_streams registration.
        self._pending_cancel_intents[session_id] = validated_intent
        self._schedule_pending_cancel_cleanup(session_id)
        return True
    previous = self._cancel_requested.get(session_id)
    if previous is not None and previous != validated_intent:
        logger.warning(
            "cancel_session overriding pending intent for session %s: %s -> %s",
            session_id,
            previous,
            validated_intent,
        )
    self._cancel_requested[session_id] = validated_intent
    stream.cancel()
    try:
        await stream
    except (asyncio.CancelledError, Exception):
        pass
    return True


def _schedule_pending_cancel_cleanup(self, session_id: str) -> None:
    """Expire _pending_cancel_intents[session_id] after 60s to avoid leaks
    when run_streaming never starts (e.g. turn aborted during setup)."""
    previous = self._pending_cancel_timers.pop(session_id, None)
    if previous is not None:
        previous.cancel()
    loop = asyncio.get_event_loop()
    handle = loop.call_later(60.0, self._expire_pending_cancel, session_id)
    self._pending_cancel_timers[session_id] = handle


def _expire_pending_cancel(self, session_id: str) -> None:
    self._pending_cancel_intents.pop(session_id, None)
    self._pending_cancel_timers.pop(session_id, None)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/core/test_base_agent_pending_cancel.py -v`
Expected: PASS 两条。

- [ ] **Step 5: 跑既有取消测试确认未回归**

Run: `pytest tests/unit/core/test_base_agent_cancel_intent.py -v`
Expected: 全部 PASS（活跃 stream 取消路径语义未变）。

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_base_agent_pending_cancel.py
git commit -m "feat(core): cancel_session 支持流未登记时预取消

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: `run_streaming` 消费预取消立即中止

**Files:**
- Modify: `sebastian/core/base_agent.py:335-360`（`run_streaming` 登记 + finally）
- Test: `tests/unit/core/test_base_agent_pending_cancel.py`（追加）

- [ ] **Step 1: 追加失败测试 — 预取消存在时 run_streaming 立即中止并发 `turn.cancelled`**

文件末尾追加：

```python
import asyncio

from sebastian.core.stream_events import TextBlockStart, TextDelta
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType


def _install_slow_stream(agent) -> asyncio.Event:
    started = asyncio.Event()

    async def slow_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="partial")
        started.set()
        await asyncio.sleep(10)

    agent._loop.stream = slow_stream  # type: ignore[attr-defined]
    return started


@pytest.mark.asyncio
async def test_run_streaming_consumes_pending_cancel_on_registration(tmp_path: Path) -> None:
    """REST 200 后用户立即点停止 → pending cancel 写入 → run_streaming 登记后立即消费."""
    class DummyAgent(BaseAgent):
        name = "sebastian"

    session_store = SessionStore(tmp_path / "sessions")
    await session_store.create_session(Session(id="s1", agent_type="sebastian", title="S1"))
    events: list[Event] = []

    class RecordingBus(EventBus):
        async def publish(self, event: Event) -> None:
            events.append(event)

    gate = MagicMock()
    agent = DummyAgent(gate=gate, session_store=session_store, event_bus=RecordingBus())
    _install_slow_stream(agent)

    # Simulate race: user cancels before run_streaming registers _active_streams.
    await agent.cancel_session("s1", intent="cancel")
    assert "s1" in agent._pending_cancel_intents

    with pytest.raises(asyncio.CancelledError):
        await agent.run_streaming("hello", "s1")

    # Pending intent consumed.
    assert "s1" not in agent._pending_cancel_intents
    # Cancel was recorded for teardown.
    assert agent.consume_cancel_intent("s1") == "cancel"
    # turn.cancelled was emitted.
    assert any(e.type == EventType.TURN_CANCELLED for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/core/test_base_agent_pending_cancel.py::test_run_streaming_consumes_pending_cancel_on_registration -v`
Expected: FAIL — stream 会正常跑到 `await asyncio.sleep(10)`，测试超时或断言 `pending_cancel_intents` 未消费失败。

- [ ] **Step 3: 在 run_streaming 登记处消费预取消**

Edit `sebastian/core/base_agent.py` 约 line 335-350。原代码：

```python
        current_stream = asyncio.create_task(
            self._stream_inner(
                messages=messages,
                session_id=session_id,
                task_id=task_id,
                agent_context=agent_context,
                thinking_effort=thinking_effort_for_llm,
            )
        )
        self._active_streams[session_id] = current_stream
        try:
            return await current_stream
```

改为：

```python
        current_stream = asyncio.create_task(
            self._stream_inner(
                messages=messages,
                session_id=session_id,
                task_id=task_id,
                agent_context=agent_context,
                thinking_effort=thinking_effort_for_llm,
            )
        )
        self._active_streams[session_id] = current_stream

        # Consume pre-cancel: user clicked stop before we finished setup.
        pending_intent = self._pending_cancel_intents.pop(session_id, None)
        pending_timer = self._pending_cancel_timers.pop(session_id, None)
        if pending_timer is not None:
            pending_timer.cancel()
        if pending_intent is not None:
            self._cancel_requested[session_id] = pending_intent
            current_stream.cancel()

        try:
            return await current_stream
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/core/test_base_agent_pending_cancel.py -v`
Expected: PASS 三条。

- [ ] **Step 5: 跑全量 base_agent 相关测试确认未回归**

Run: `pytest tests/unit/core/ -v -k base_agent`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_base_agent_pending_cancel.py
git commit -m "feat(core): run_streaming 登记后消费预取消立即中止

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: TTL 到期自清理

**Files:**
- Test: `tests/unit/core/test_base_agent_pending_cancel.py`（追加）

实现已在 Task 1 包含 `_schedule_pending_cancel_cleanup`，本任务只补测试。

- [ ] **Step 1: 追加失败测试 — 60s 后 pending intent 自动清空**

```python
@pytest.mark.asyncio
async def test_pending_cancel_ttl_expiry(agent) -> None:
    await agent.cancel_session("s1", intent="cancel")
    assert "s1" in agent._pending_cancel_intents

    # Trigger TTL manually (the handle is a real asyncio TimerHandle; invoking
    # its callback directly avoids sleeping 60 real seconds in tests).
    agent._expire_pending_cancel("s1")

    assert "s1" not in agent._pending_cancel_intents
    assert "s1" not in agent._pending_cancel_timers
```

- [ ] **Step 2: 跑测试确认通过（实现已在 Task 1 就位）**

Run: `pytest tests/unit/core/test_base_agent_pending_cancel.py::test_pending_cancel_ttl_expiry -v`
Expected: PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_base_agent_pending_cancel.py
git commit -m "test(core): 验证 pending cancel 60s TTL 清理

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Gateway 集成测试覆盖 REST 200 → 立即 cancel 不 404

**Files:**
- Modify: `tests/integration/gateway/test_gateway_sessions.py`（追加）

- [ ] **Step 1: 写集成测试**

在 `tests/integration/gateway/test_gateway_sessions.py` 末尾追加（参考文件内既有 `cancel` 相关测试结构）：

```python
@pytest.mark.asyncio
async def test_cancel_right_after_turn_returns_not_404(gateway_client, monkeypatch) -> None:
    """REST 200 后立刻 POST /cancel — 不应 404 even when _active_streams 尚未登记."""
    import sebastian.gateway.state as state

    # Slow run_streaming setup: insert an artificial delay before _active_streams registration
    # by patching session_store.get_session_for_agent_type to sleep.
    original_get = state.session_store.get_session_for_agent_type

    async def slow_get(session_id: str, agent_type: str):
        await asyncio.sleep(0.3)
        return await original_get(session_id, agent_type)

    monkeypatch.setattr(state.session_store, "get_session_for_agent_type", slow_get)

    turn_resp = await gateway_client.post("/api/v1/turns", json={"content": "hello"})
    assert turn_resp.status_code == 200
    session_id = turn_resp.json()["session_id"]

    # Cancel immediately — still within the 300ms setup window.
    cancel_resp = await gateway_client.post(f"/api/v1/sessions/{session_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json() == {"ok": True}

    # Eventually the agent clears pending intent.
    await asyncio.sleep(0.5)
    agent = state.sebastian
    assert session_id not in agent._pending_cancel_intents
    assert session_id not in agent._active_streams
```

- [ ] **Step 2: 跑测试确认通过**

Run: `pytest tests/integration/gateway/test_gateway_sessions.py::test_cancel_right_after_turn_returns_not_404 -v`
Expected: PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/integration/gateway/test_gateway_sessions.py
git commit -m "test(gateway): REST 200 后立即 cancel 不 404 竞态集成测试

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: 更新后端文档

**Files:**
- Modify: `sebastian/core/README.md`
- Modify: `sebastian/gateway/routes/README.md`

- [ ] **Step 1: 更新 `sebastian/core/README.md`**

在 `BaseAgent` cancel 机制相关小节（若无则在最合适位置新增）补一段：

```markdown
### Cancel 三段式生命周期

| 字典 | 语义 | 消费方 |
|------|------|--------|
| `_pending_cancel_intents[sid]` | 流尚未登记时记录的预取消 intent（REST 已返回、`_active_streams` 未写入） | `run_streaming` 登记 `_active_streams` 后立即消费 |
| `_cancel_requested[sid]` | 流运行中被取消的 intent | `run_streaming` finally 块 |
| `_completed_cancel_intents[sid]` | 流已终止的取消 intent，供外部（如 resume 工具）消费 | `consume_cancel_intent()` |

`_pending_cancel_intents` 条目带 60s TTL（`_schedule_pending_cancel_cleanup` / `_expire_pending_cancel`），防止 turn 从未真正启动时泄漏。
```

- [ ] **Step 2: 更新 `sebastian/gateway/routes/README.md`**

在「修改导航」表里补 `POST /sessions/{id}/cancel`（若缺失）：

```markdown
| `POST /sessions/{id}/cancel` — 取消 session 当前 turn（含未登记流的预取消兜底） | [sessions.py:389](sessions.py) |
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/core/README.md sebastian/gateway/routes/README.md
git commit -m "docs(core,gateway): 记录 pending cancel 语义与 session cancel 端点

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Part B — Android 协议层：`turn.cancelled` 事件

### Task 6: `StreamEvent.TurnCancelled` 类型

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/SseFrameParserTest.kt`（若不存在则新建；存在则追加）

- [ ] **Step 1: 写失败 parser 测试**

在 `SseFrameParserTest.kt` 追加（若文件不存在按既有 test 目录结构创建）：

```kotlin
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.StreamEvent
import org.junit.Assert.assertEquals
import org.junit.Test

class SseFrameParserTurnCancelledTest {
    @Test
    fun `parses turn_cancelled into TurnCancelled`() {
        val raw = """{"type":"turn.cancelled","data":{"session_id":"s1","partial_content":"half"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(StreamEvent.TurnCancelled("s1", "half"), event)
    }

    @Test
    fun `parses turn_cancelled without partial_content`() {
        val raw = """{"type":"turn.cancelled","data":{"session_id":"s1"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(StreamEvent.TurnCancelled("s1", ""), event)
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*SseFrameParserTurnCancelledTest*'`
Expected: FAIL — `Unresolved reference: TurnCancelled`。

- [ ] **Step 3: 在 StreamEvent 加密封子类**

Edit `data/model/StreamEvent.kt`，在 `TurnInterrupted` 下一行加：

```kotlin
data class TurnCancelled(val sessionId: String, val partialContent: String) : StreamEvent()
```

- [ ] **Step 4: 在 parser 加分支**

Edit `data/remote/dto/SseFrameDto.kt`，在 `"turn.interrupted"` 那一行下方加：

```kotlin
"turn.cancelled" -> StreamEvent.TurnCancelled(data.getString("session_id"), data.optString("partial_content", ""))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*SseFrameParserTurnCancelledTest*'`
Expected: PASS 两条。

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/SseFrameParserTurnCancelledTest.kt
git commit -m "feat(android/data): 解析 turn.cancelled SSE 事件

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: ChatViewModel handle `TurnCancelled`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt:261-271`（`handleEvent` 的 `TurnInterrupted` 分支旁边）
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`（追加）

- [ ] **Step 1: 追加失败测试**

在 `ChatViewModelTest.kt` 末尾追加：

```kotlin
@Test
fun `TurnCancelled event flushes deltas and resets to IDLE_EMPTY`() = vmTest {
    activateSession()
    viewModel.uiState.test {
        awaitItem() // post-session state

        sseFlow.emit(StreamEvent.TurnReceived("s1"))
        sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0"))
        sseFlow.emit(StreamEvent.TextDelta("s1", "b0", "hello"))
        dispatcher.scheduler.advanceTimeBy(200)
        awaitItem() // streaming state

        sseFlow.emit(StreamEvent.TurnCancelled("s1", "hello"))
        dispatcher.scheduler.advanceTimeBy(200)

        val state = awaitItem()
        assertEquals(ComposerState.IDLE_EMPTY, state.composerState)
        assertEquals(AgentAnimState.IDLE, state.agentAnimState)
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.TurnCancelled*'`
Expected: FAIL — 状态未回到 IDLE_EMPTY（`TurnCancelled` 走了 `else -> Unit`）。

- [ ] **Step 3: handleEvent 新增 TurnCancelled 分支**

Edit `viewmodel/ChatViewModel.kt`，在 `TurnInterrupted` 分支（约 line 261-271）下方追加，复用相同清理逻辑：

```kotlin
is StreamEvent.TurnCancelled -> {
    flushPendingDeltasForCurrentMessage()
    currentAssistantMessageId = null
    pendingTurnSessionId = null
    _uiState.update {
        it.copy(
            composerState = ComposerState.IDLE_EMPTY,
            agentAnimState = AgentAnimState.IDLE,
        )
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.TurnCancelled*'`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android/vm): handleEvent 处理 TurnCancelled 事件

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Part C — Android 状态机：PENDING

### Task 8: 引入 `PENDING`，移除 `SENDING`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt:31-39, 130-319, 456-465`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`（追加）

- [ ] **Step 1: 追加失败测试 — sendMessage 进入 PENDING / PENDING**

```kotlin
@Test
fun `sendMessage enters PENDING and stays PENDING through sendTurn success`() = vmTest {
    activateSession()
    viewModel.uiState.test {
        awaitItem() // post-session

        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(50)

        val immediate = awaitItem()
        assertEquals(ComposerState.PENDING, immediate.composerState)
        assertEquals(AgentAnimState.PENDING, immediate.agentAnimState)

        dispatcher.scheduler.advanceTimeBy(500)  // let sendTurn.onSuccess fire
        val afterRest = awaitItem()
        // REST 返回不再重置 composer —— 仍是 PENDING
        assertEquals(ComposerState.PENDING, afterRest.composerState)
        assertEquals(AgentAnimState.PENDING, afterRest.agentAnimState)
    }
}

@Test
fun `first BlockStart transitions PENDING to STREAMING`() = vmTest {
    activateSession()
    viewModel.sendMessage("hi")
    dispatcher.scheduler.advanceTimeBy(500)

    viewModel.uiState.test {
        awaitItem() // current PENDING

        sseFlow.emit(StreamEvent.TurnReceived("s1"))
        dispatcher.scheduler.advanceTimeBy(50)
        // TurnReceived 不切状态 —— 仍是 PENDING
        // (no awaitItem; state unchanged)

        sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0"))
        dispatcher.scheduler.advanceTimeBy(200)
        val state = awaitItem()
        assertEquals(ComposerState.STREAMING, state.composerState)
        assertEquals(AgentAnimState.STREAMING, state.agentAnimState)
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest*'`
Expected: FAIL — 新测试 + 任何断言 `SENDING` 的既有测试（若有）。

- [ ] **Step 3: 改 enum 与状态转移**

Edit `viewmodel/ChatViewModel.kt`：

Line 31-33：

```kotlin
enum class ComposerState { IDLE_EMPTY, IDLE_READY, PENDING, STREAMING, CANCELLING }

enum class AgentAnimState { IDLE, PENDING, THINKING, STREAMING, WORKING }
```

Line 288-294（`sendMessage` 入口更新）：

```kotlin
_uiState.update { state ->
    state.copy(
        messages = state.messages + userMsg,
        composerState = ComposerState.PENDING,
        agentAnimState = AgentAnimState.PENDING,
        scrollFollowState = ScrollFollowState.FOLLOWING,
    )
}
```

Line 297-313（`sendTurn.onSuccess` 不再改 composerState / agentAnimState）：

```kotlin
chatRepository.sendTurn(currentSessionId, text)
    .onSuccess { returnedSessionId ->
        // REST returned — DO NOT clear PENDING; SSE events drive exit.
        if (currentSessionId == null || currentSessionId != returnedSessionId) {
            _uiState.update { it.copy(activeSessionId = returnedSessionId) }
            startSseCollection(replayFromStart = true)
            sessionRepository.loadSessions()
        } else {
            if (sseJob?.isActive != true) {
                startSseCollection(replayFromStart = true)
            }
        }
    }
    .onFailure { e ->
        _uiState.update {
            it.copy(
                composerState = ComposerState.IDLE_READY,
                agentAnimState = AgentAnimState.IDLE,
                error = e.message,
            )
        }
    }
```

Line 144-147（`connectionFailed` 分支把 SENDING 换成 PENDING）：

```kotlin
composerState = if (state.composerState == ComposerState.PENDING ||
    state.composerState == ComposerState.STREAMING
) ComposerState.IDLE_EMPTY else state.composerState,
```

Line 456-459（`onAppStart` 跳过条件把 SENDING 换成 PENDING）：找到类似条件的 if 判断并替换（保持跳过语义不变）：

```kotlin
if (state.composerState == ComposerState.STREAMING ||
    state.composerState == ComposerState.PENDING ||
    state.composerState == ComposerState.CANCELLING ||
    state.composerState == ComposerState.IDLE_READY
)
```

全局搜索 `ComposerState.SENDING` 与 `AgentAnimState` 其它引用，确认没有遗漏。

`agentAnimState` 原本由 BlockStart 事件设置为 THINKING / STREAMING / WORKING —— 保持原逻辑（line 163, 190, 221），不动。

- [ ] **Step 4: 跑全部 ChatViewModel 测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest*'`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android/vm): 引入 PENDING 状态合并 SENDING 及 REST 返回后空窗

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: `sendTurnJob` 引用与本地取消

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt:279-319, 378-389`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`（追加）

- [ ] **Step 1: 追加失败测试**

```kotlin
@Test
fun `cancelTurn with null activeSessionId cancels sendTurnJob and returns to IDLE_READY`() = vmTest {
    // 模拟首次对话：没有 activeSessionId
    // 需要阻止 sendTurn 返回，以测试 PENDING 期间 cancel
    runBlocking {
        whenever(chatRepository.sendTurn(any(), any())).doSuspendableAnswer {
            kotlinx.coroutines.delay(10_000)  // simulate slow REST
            Result.success("s1")
        }
    }

    viewModel.uiState.test {
        awaitItem() // initial IDLE_EMPTY

        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(50)
        val pending = awaitItem()
        assertEquals(ComposerState.PENDING, pending.composerState)

        viewModel.cancelTurn()
        dispatcher.scheduler.advanceTimeBy(50)

        val afterCancel = awaitItem()
        assertEquals(ComposerState.IDLE_READY, afterCancel.composerState)
        // 用户气泡保留
        assertTrue(afterCancel.messages.any { it.role == MessageRole.USER && it.text == "hi" })
    }
}
```

（`doSuspendableAnswer` 从 `org.mockito.kotlin.doSuspendableAnswer` 导入；若项目未用过，import 对应符号。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.cancelTurn_with_null*'`
Expected: FAIL — `cancelTurn` 在 `activeSessionId == null` 时 `return` 不变状态。

- [ ] **Step 3: 保存 `sendTurnJob` 并实现本地取消分支**

Edit `viewmodel/ChatViewModel.kt`：

在类成员区域（与 `sseJob` 并列，约 line 108 附近）加：

```kotlin
private var sendTurnJob: Job? = null
```

`sendMessage` 内把 `viewModelScope.launch(...)` 改为存 `Job`（约 line 295-318）：

```kotlin
sendTurnJob = viewModelScope.launch(dispatcher) {
    chatRepository.sendTurn(currentSessionId, text)
        .onSuccess { returnedSessionId ->
            // … 同 Task 8 修改后内容
        }
        .onFailure { e ->
            _uiState.update {
                it.copy(
                    composerState = ComposerState.IDLE_READY,
                    agentAnimState = AgentAnimState.IDLE,
                    error = e.message,
                )
            }
        }
}
```

改 `cancelTurn`（约 line 378-389）：

```kotlin
fun cancelTurn() {
    val sessionId = _uiState.value.activeSessionId
    if (sessionId == null) {
        // PENDING before REST returned: no remote turn yet. Cancel local job,
        // go to IDLE_READY, keep user bubble & composer text for edit/retry.
        sendTurnJob?.cancel()
        sendTurnJob = null
        _uiState.update {
            it.copy(
                composerState = ComposerState.IDLE_READY,
                agentAnimState = AgentAnimState.IDLE,
            )
        }
        return
    }
    _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
    viewModelScope.launch(dispatcher) {
        withTimeoutOrNull(5_000L) {
            chatRepository.cancelTurn(sessionId)
                .onFailure { e ->
                    _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY, error = e.message) }
                }
        } ?: _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY) }
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.cancelTurn*'`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android/vm): PENDING 期间无 sessionId 本地取消并保留 Composer

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 10: PENDING 15s 超时 + 前台累计计时

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`（追加）

- [ ] **Step 1: 追加失败测试**

```kotlin
@Test
fun `pending timeout emits slow-response hint after 15s with no events`() = vmTest {
    activateSession()
    viewModel.toasts.test {
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(14_000)
        expectNoEvents()

        dispatcher.scheduler.advanceTimeBy(2_000)  // cross 15s boundary
        val toast = awaitItem()
        assertTrue(toast.message.contains("响应较慢"))
    }
}

@Test
fun `pending timeout is cancelled when any SSE event arrives`() = vmTest {
    activateSession()
    viewModel.toasts.test {
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(500)

        sseFlow.emit(StreamEvent.TurnReceived("s1"))
        dispatcher.scheduler.advanceTimeBy(20_000)

        expectNoEvents()  // 计时被事件抵消
    }
}

@Test
fun `pending timeout is paused on onAppStop and resumed on onAppStart`() = vmTest {
    activateSession()
    viewModel.toasts.test {
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(10_000)

        viewModel.onAppStop()
        dispatcher.scheduler.advanceTimeBy(60_000)  // 后台 60s 不应触发
        expectNoEvents()

        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(4_000)   // 再 4s 还没到剩余 5s
        expectNoEvents()

        dispatcher.scheduler.advanceTimeBy(2_000)   // 累计前台 16s，触发
        val toast = awaitItem()
        assertTrue(toast.message.contains("响应较慢"))
    }
}
```

（假设 `viewModel.toasts` 是 `SharedFlow<ToastMessage>`；如项目 ToastCenter 接口是另一个命名，按实际替换。若 ToastCenter 是全局 singleton，改为从 singleton 收。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.pending_timeout*'`
Expected: FAIL — 无超时机制。

- [ ] **Step 3: 实现前台累计计时**

Edit `viewmodel/ChatViewModel.kt`。添加成员：

```kotlin
private var pendingTimeoutJob: Job? = null
private var pendingTimeoutElapsedMs: Long = 0L  // 前台累计已走时长
private var pendingTimeoutStartAtMs: Long = 0L  // 当前计时段启动时间戳
```

新增方法：

```kotlin
private fun startPendingTimeout() {
    pendingTimeoutElapsedMs = 0L
    launchPendingTimeoutSegment(remaining = PENDING_TIMEOUT_MS)
}

private fun launchPendingTimeoutSegment(remaining: Long) {
    pendingTimeoutJob?.cancel()
    pendingTimeoutStartAtMs = System.currentTimeMillis()
    pendingTimeoutJob = viewModelScope.launch(dispatcher) {
        delay(remaining)
        toastCenter.showToast("响应较慢，可点停止后重试")
    }
}

private fun pausePendingTimeout() {
    if (pendingTimeoutJob?.isActive == true) {
        pendingTimeoutElapsedMs += System.currentTimeMillis() - pendingTimeoutStartAtMs
        pendingTimeoutJob?.cancel()
        pendingTimeoutJob = null
    }
}

private fun resumePendingTimeoutIfNeeded() {
    if (_uiState.value.composerState != ComposerState.PENDING) return
    val remaining = (PENDING_TIMEOUT_MS - pendingTimeoutElapsedMs).coerceAtLeast(0L)
    if (remaining == 0L) return
    launchPendingTimeoutSegment(remaining)
}

private fun cancelPendingTimeout() {
    pendingTimeoutJob?.cancel()
    pendingTimeoutJob = null
    pendingTimeoutElapsedMs = 0L
}

companion object {
    private const val PENDING_TIMEOUT_MS = 15_000L
}
```

挂点：

- `sendMessage()` 的 `_uiState.update {... composerState = PENDING ...}` 之后调 `startPendingTimeout()`
- `handleEvent()` 入口（任意事件到达）：若 `pendingTimeoutJob != null` 调 `cancelPendingTimeout()`（放在 when 之前，这样 TurnReceived / 任何事件都算）
- `cancelTurn()` 两个分支都调 `cancelPendingTimeout()`
- `onAppStop()` 调 `pausePendingTimeout()`
- `onAppStart()` 调 `resumePendingTimeoutIfNeeded()`
- TurnResponse / TurnInterrupted / TurnCancelled 分支也调 `cancelPendingTimeout()`（其实 handleEvent 入口已覆盖，但在这些终止事件显式清除防御）

（`toastCenter` 假设可注入；若 ChatViewModel 目前未持有 `ToastCenter`，则走和全局 ToastCenter 同款方式注入。若项目是通过 SharedFlow 全局 singleton 则 `ToastCenter.showToast(...)` 直接调用。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.pending_timeout*'`
Expected: PASS 三条。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android/vm): PENDING 15s 前台累计计时与超时提示

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: `onAppStart` PENDING 分支 — getMessages 决定去向

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt:450-467`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`（追加）

- [ ] **Step 1: 追加失败测试**

```kotlin
@Test
fun `onAppStart in PENDING with assistant-done last message resets to IDLE_EMPTY`() = vmTest {
    activateSession()
    viewModel.sendMessage("hi")
    dispatcher.scheduler.advanceTimeBy(500)

    // Simulate backend finished turn while backgrounded — getMessages returns assistant-done.
    runBlocking {
        whenever(chatRepository.getMessages("s1")).thenReturn(
            Result.success(listOf(
                Message(id = "m1", sessionId = "s1", role = MessageRole.USER, text = "hi"),
                Message(
                    id = "m2",
                    sessionId = "s1",
                    role = MessageRole.ASSISTANT,
                    blocks = listOf(ContentBlock.TextBlock(blockId = "b0", text = "done", done = true)),
                ),
            ))
        )
    }

    viewModel.onAppStop()
    dispatcher.scheduler.advanceTimeBy(100)
    viewModel.onAppStart()
    dispatcher.scheduler.advanceTimeBy(300)

    viewModel.uiState.test {
        val state = awaitItem()
        assertEquals(ComposerState.IDLE_EMPTY, state.composerState)
        assertEquals(AgentAnimState.IDLE, state.agentAnimState)
    }
}

@Test
fun `onAppStart in PENDING with user-only last message stays PENDING`() = vmTest {
    activateSession()
    viewModel.sendMessage("hi")
    dispatcher.scheduler.advanceTimeBy(500)

    runBlocking {
        whenever(chatRepository.getMessages("s1")).thenReturn(
            Result.success(listOf(
                Message(id = "m1", sessionId = "s1", role = MessageRole.USER, text = "hi"),
            ))
        )
    }

    viewModel.onAppStop()
    viewModel.onAppStart()
    dispatcher.scheduler.advanceTimeBy(300)

    viewModel.uiState.test {
        val state = awaitItem()
        assertEquals(ComposerState.PENDING, state.composerState)
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.onAppStart_in_PENDING*'`
Expected: FAIL — 当前 onAppStart 会跳过 PENDING 或走 switchSession。

- [ ] **Step 3: 实现 PENDING 专用分支**

Edit `viewmodel/ChatViewModel.kt`。`onAppStart()` 在现有跳过条件之后、调 `switchSession` 之前插入 PENDING 分支：

```kotlin
fun onAppStart() {
    val state = _uiState.value
    val sessionId = state.activeSessionId ?: return

    if (state.composerState == ComposerState.PENDING) {
        // 后台期 turn 可能已完成；用 getMessages 断言最后一条是否已是 assistant-done。
        viewModelScope.launch(dispatcher) {
            chatRepository.getMessages(sessionId)
                .onSuccess { msgs ->
                    val last = msgs.lastOrNull()
                    val turnDone = last?.role == MessageRole.ASSISTANT &&
                        last.blocks.lastOrNull()?.let { (it as? ContentBlock.TextBlock)?.done == true } == true
                    if (turnDone) {
                        cancelPendingTimeout()
                        _uiState.update {
                            it.copy(
                                messages = msgs,
                                composerState = ComposerState.IDLE_EMPTY,
                                agentAnimState = AgentAnimState.IDLE,
                            )
                        }
                    } else {
                        // 保持 PENDING；重建 SSE 连接由 Last-Event-ID 回放补齐
                    }
                    startSseCollection(replayFromStart = false)
                    resumePendingTimeoutIfNeeded()
                }
        }
        return
    }

    // 原有跳过条件
    if (state.composerState == ComposerState.STREAMING ||
        state.composerState == ComposerState.CANCELLING ||
        state.composerState == ComposerState.IDLE_READY
    ) {
        startSseCollection(replayFromStart = false)
        return
    }

    // 默认路径（维持既有行为）
    switchSession(sessionId)
}
```

（注意：`ContentBlock.TextBlock.done` 已是现有字段；`lastOrNull()` 为简化，若项目里 last block 可能是 Thinking / Tool 需要精确化——按 spec §7.1 的"最新一条角色是 assistant 且完成"判断。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest.onAppStart_in_PENDING*'`
Expected: PASS 两条。

- [ ] **Step 5: 跑全部 ChatViewModel 测试确认未回归**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests '*ChatViewModelTest*'`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android/vm): onAppStart 在 PENDING 下用 getMessages 判断去向

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Part D — Android UI：SendButton + AgentPill

### Task 12: SendButton PENDING 可点停止

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/SendButton.kt`

- [ ] **Step 1: 改 state-table 注释**

Edit `SendButton.kt` 顶部 KDoc 表格：

```kotlin
/**
 * 发送 / 停止 按钮（液态玻璃风格）
 *
 * | state       | 外观                      | 可点击 |
 * |-------------|--------------------------|-------|
 * | IDLE_EMPTY  | Neutral 玻璃圆（禁用）      | 否    |
 * | IDLE_READY  | Primary 玻璃圆 + 发送图标   | 是    |
 * | PENDING     | Primary 玻璃圆 + 停止图标   | 是    |
 * | STREAMING   | Primary 玻璃圆 + 停止图标   | 是    |
 * | CANCELLING  | Neutral 玻璃圆 + 进度环     | 否    |
 */
```

- [ ] **Step 2: 改 `isEnabled` / `tint` / `onClick` 判断**

同文件约 line 43-53：

```kotlin
val isEnabled = state == ComposerState.IDLE_READY ||
    state == ComposerState.STREAMING ||
    state == ComposerState.PENDING
val tint = if (state == ComposerState.IDLE_READY ||
    state == ComposerState.STREAMING ||
    state == ComposerState.PENDING
) GlassButtonTint.Primary else GlassButtonTint.Neutral

val onClick: () -> Unit = when (state) {
    ComposerState.IDLE_READY -> onSend
    ComposerState.STREAMING, ComposerState.PENDING -> onStop
    else -> ({})
}
```

- [ ] **Step 3: 改 `AnimatedContent` 分支**

约 line 70-90，把 `SENDING` 对应分支改为 `PENDING` 显示停止图标（与 STREAMING 并列）；保留 `CANCELLING` 进度环：

```kotlin
when (targetState) {
    ComposerState.IDLE_EMPTY, ComposerState.IDLE_READY -> Icon(
        imageVector = SebastianIcons.SendAction,
        contentDescription = "发送",
        tint = if (targetState == ComposerState.IDLE_READY)
            MaterialTheme.colorScheme.onPrimary
        else
            MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f),
    )
    ComposerState.PENDING, ComposerState.STREAMING -> Icon(
        imageVector = SebastianIcons.StopAction,
        contentDescription = "停止",
        tint = MaterialTheme.colorScheme.onPrimary,
    )
    ComposerState.CANCELLING -> CircularProgressIndicator(
        modifier = Modifier.size(20.dp),
        strokeWidth = 2.dp,
        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
    )
}
```

- [ ] **Step 4: 编译**

Run: `cd ui/mobile-android && ./gradlew :app:compileDebugKotlin`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/SendButton.kt
git commit -m "feat(android/ui): SendButton PENDING 态显示可点停止

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 13: 彩虹辅色 + BreathingHalo composable

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/Color.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt`

- [ ] **Step 1: 加彩虹辅色**

Edit `ui/theme/Color.kt`，在 `AgentAccentDark` 下方追加：

```kotlin
val AgentAccentLight = Color(0xFF6FC3FF)
val AgentAccentDark = Color(0xFF9FD6FF)

// Rainbow breathing halo for PENDING state (multi-hue sweep around AgentAccent).
val AgentRainbowPurpleLight = Color(0xFF9F7BFF)
val AgentRainbowPurpleDark = Color(0xFFB79BFF)
val AgentRainbowCyanLight = Color(0xFF7BE0D1)
val AgentRainbowCyanDark = Color(0xFF9BEAE0)
```

- [ ] **Step 2: 实现 `BreathingHalo` composable**

在 `AgentPillAnimations.kt` 追加（若文件内有 `OrbsAnimation` / `HudAnimation`，风格对齐）：

```kotlin
/**
 * PENDING 档位的边缘 halo：
 * - 彩虹渐变（蓝 → 紫 → 青 → 蓝）环形 gradient，每 2.4s 缓慢旋转 360°
 * - 整体 alpha 在 0.35 ↔ 0.75 之间呼吸，周期 1.6s
 * - 半径与 THINKING / ACTIVE 保持一致，只盖在 pill 边缘
 *
 * 不依赖 accent 单色 —— 用三色循环 SweepGradient。
 */
@Composable
fun BreathingHalo(
    modifier: Modifier = Modifier,
    glowAlphaScale: Float = 1f,
) {
    val isDark = isSystemInDarkTheme()
    val primary = if (isDark) AgentAccentDark else AgentAccentLight
    val purple = if (isDark) AgentRainbowPurpleDark else AgentRainbowPurpleLight
    val cyan = if (isDark) AgentRainbowCyanDark else AgentRainbowCyanLight

    val infinite = rememberInfiniteTransition(label = "breathing_halo")
    val rotation by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2400, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "rotation",
    )
    val alpha by infinite.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.75f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "alpha",
    )

    Canvas(modifier = modifier.size(24.dp)) {
        val brush = Brush.sweepGradient(
            listOf(primary, purple, cyan, primary),
        )
        rotate(rotation) {
            drawCircle(
                brush = brush,
                radius = size.minDimension / 2f,
                alpha = alpha * glowAlphaScale,
                style = Stroke(width = 4.dp.toPx()),
            )
        }
    }
}
```

补齐 import（`androidx.compose.animation.core.*`、`androidx.compose.foundation.Canvas`、`androidx.compose.ui.graphics.Brush`、`rotate` 等）。

- [ ] **Step 3: 编译**

Run: `cd ui/mobile-android && ./gradlew :app:compileDebugKotlin`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/theme/Color.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPillAnimations.kt
git commit -m "feat(android/ui): 新增 BreathingHalo 彩虹呼吸动画与辅色

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 14: AgentPill 接入 BREATHING 档

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt`

- [ ] **Step 1: 加 BREATHING 档位并映射**

Edit `AgentPill.kt`：

Line 44（`AgentPillMode` 枚举）扩展：

```kotlin
enum class AgentPillMode { COLLAPSED, BREATHING, THINKING, ACTIVE }
```

Line 46-50 `toPillMode()` 扩展：

```kotlin
fun AgentAnimState.toPillMode(): AgentPillMode = when (this) {
    AgentAnimState.IDLE -> AgentPillMode.COLLAPSED
    AgentAnimState.PENDING -> AgentPillMode.BREATHING
    AgentAnimState.THINKING -> AgentPillMode.THINKING
    AgentAnimState.STREAMING, AgentAnimState.WORKING -> AgentPillMode.ACTIVE
}
```

Line 88-93 `stateLabel` 扩展：

```kotlin
val stateLabel = when (stableMode) {
    AgentPillMode.COLLAPSED -> null
    AgentPillMode.BREATHING -> "等待响应"
    AgentPillMode.THINKING -> "正在思考"
    AgentPillMode.ACTIVE -> "正在响应"
}
```

Line 116-144 `AnimatedVisibility` / `AnimatedContent` 内 `when (mode)` 增加 BREATHING 分支：

```kotlin
when (mode) {
    AgentPillMode.BREATHING -> BreathingHalo(glowAlphaScale = glowScale)
    AgentPillMode.THINKING -> OrbsAnimation(
        accent = accent,
        glowAlphaScale = glowScale,
    )
    AgentPillMode.ACTIVE -> HudAnimation(
        accent = accent,
        glowAlphaScale = glowScale,
    )
    AgentPillMode.COLLAPSED -> Spacer(Modifier.size(0.dp))
}
```

- [ ] **Step 2: 编译**

Run: `cd ui/mobile-android && ./gradlew :app:compileDebugKotlin`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: 运行单元测试整体（抽烟）**

Run: `cd ui/mobile-android && ./gradlew :app:testDebugUnitTest`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/AgentPill.kt
git commit -m "feat(android/ui): AgentPill 新增 BREATHING 档位映射 PENDING

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Part E — 文档

### Task 15: 更新 Android ViewModel README 状态机表

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md`

- [ ] **Step 1: 改 `ComposerState` / `AgentAnimState` 表**

在该 README 的状态机表改为：

```markdown
| `ComposerState` | IDLE_EMPTY / IDLE_READY / PENDING / STREAMING / CANCELLING |
| `AgentAnimState` | IDLE / PENDING / THINKING / STREAMING / WORKING |
```

并在下方补一段：

```markdown
### PENDING 语义

- 进入：`sendMessage()` 入口
- 持续：REST 200 → 首个 SSE BlockStart 事件（`TurnReceived` 不触发切换）
- 退出：首个 `ThinkingBlockStart` / `TextBlockStart` / `ToolBlockStart`，或 `TurnCancelled` / `TurnInterrupted` / `TurnResponse`
- `SendButton` 显示可点停止；无 `activeSessionId` 时点停止走本地取消（保留 Composer 文本 + 用户气泡）
- 15s 前台累计超时触发"响应较慢"提示，`onAppStop` 暂停计时 / `onAppStart` 按剩余时长恢复
- `onAppStart` 在 PENDING 下调 `getMessages` 判断后台期是否已完成 turn
```

- [ ] **Step 2: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md
git commit -m "docs(android/vm): 更新 PENDING 状态机与 onAppStart 分支说明

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Part F — 联调验收

### Task 16: 本地联调四条路径

**Files:** 无代码改动，只是人工 / 半自动验证。

- [ ] **Step 1: 起开发环境**

```bash
# 后端
./scripts/dev.sh &

# 模拟器
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed

# App（以当前工作区代码装）
cd ui/mobile-android && ./gradlew installDebug
```

App 内 Settings → Connection 填 `http://10.0.2.2:8824`。

- [ ] **Step 2: 路径 1 — 正常响应**

发送一条消息。断言：
- 顶部胶囊立刻显示 BreathingHalo 彩虹呼吸
- SendButton 变停止图标可点
- 首字到达时胶囊过渡到 THINKING / ACTIVE

- [ ] **Step 3: 路径 2 — PENDING 期间点停止**

发送后立刻点停止。断言：
- 胶囊从 BREATHING 回到 COLLAPSED
- SendButton 回到 IDLE_EMPTY
- 用户气泡保留
- Gateway 日志显示 `POST /cancel` 返回 200（不是 404）

- [ ] **Step 4: 路径 3 — PENDING 期间切后台再回来**

发送后立刻按 Home，等 5s 再回前台。断言：
- 若后台期 turn 已完成 → 回来看到完整 assistant 回复，composer 到 IDLE_EMPTY
- 若后台期 turn 未完成 → 胶囊保持 BREATHING，SSE 回放补齐首字后自然过渡

- [ ] **Step 5: 路径 4 — 慢 LLM 触发 15s 超时**

手动把 provider 切到慢 endpoint（或后端临时插入 sleep），发消息。断言：
- 15s 到达后 Toast 提示"响应较慢"
- 切后台 10s 回前台不会提前触发（前台累计计时）

- [ ] **Step 6: 把观察结果写入本计划文件末尾**

简短记录四条路径结果（pass / 发现的 issue）。若有 issue 则不 commit，回退到对应 task 修复。

- [ ] **Step 7: Commit 验收记录**

```bash
git add docs/superpowers/plans/2026-04-17-android-pending-state.md
git commit -m "docs(plan): 记录 PENDING 状态联调四路径验收结果

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 联调验收记录（实施后回填）

_由实施者填写：_

- 路径 1 — 正常响应：
- 路径 2 — PENDING 期间点停止：
- 路径 3 — 切后台再回来：
- 路径 4 — 15s 超时提示：

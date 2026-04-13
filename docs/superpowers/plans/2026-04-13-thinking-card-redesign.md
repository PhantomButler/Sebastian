# ThinkingCard 极简风格重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将思考卡片重设计为 DeepSeek 极简风格：无背景容器、显示耗时、行式布局，同时后端下发 `duration_ms`。

**Architecture:** 后端在 `ThinkingBlockStop` 事件注入计时（`time.monotonic()` 差值），SSE 下发 `duration_ms`；Android 端数据模型透传该字段到 `ThinkingBlock`；`ThinkingCard.kt` 全量重写为无 Card 容器的极简行式 UI。

**Tech Stack:** Python 3.12 + dataclasses, Kotlin + Jetpack Compose Material3, org.json (Android SSE 解析)

---

## File Map

| 文件 | 操作 | 说明 |
|------|------|------|
| `sebastian/core/stream_events.py` | Modify | `ThinkingBlockStop` 增加 `duration_ms` |
| `sebastian/core/base_agent.py` | Modify | 计时并注入 `duration_ms` |
| `tests/unit/test_thinking_duration.py` | Create | 后端计时集成测试 |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt` | Modify | `ThinkingBlockStop` 增加 `durationMs` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt` | Modify | `ThinkingBlock` 增加 `durationMs` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt` | Modify | 解析 `duration_ms` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Modify | `ThinkingBlockStop` 分支透传 `durationMs` |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ThinkingCard.kt` | Rewrite | 极简行式 UI |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ThinkingCardTest.kt` | Create | `formatThinkingDuration` 单元测试 |

---

## Task 1: 后端 — `ThinkingBlockStop` 增加 `duration_ms`

**Files:**
- Modify: `sebastian/core/stream_events.py`

- [ ] **Step 1: 修改 `ThinkingBlockStop` dataclass**

打开 `sebastian/core/stream_events.py`，将 `ThinkingBlockStop` 改为：

```python
@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str  # full accumulated thinking text for this block
    signature: str | None = None
    duration_ms: int | None = None  # wall-clock ms from ThinkingBlockStart to stop
```

- [ ] **Step 2: 确认无语法错误**

```bash
cd /Users/ericw/work/code/ai/sebastian
python -c "from sebastian.core.stream_events import ThinkingBlockStop; print(ThinkingBlockStop(block_id='b', thinking='t', duration_ms=1500))"
```

期望输出：`ThinkingBlockStop(block_id='b', thinking='t', signature=None, duration_ms=1500)`

- [ ] **Step 3: Commit**

```bash
git add sebastian/core/stream_events.py
git commit -m "feat(core): ThinkingBlockStop 增加 duration_ms 字段"
```

---

## Task 2: 后端 — `base_agent.py` 计时并注入 `duration_ms`

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Create: `tests/unit/test_thinking_duration.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_thinking_duration.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
)
from tests.unit.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_thinking_block_stop_includes_duration_ms() -> None:
    """ThinkingBlockStop SSE payload 应包含正值 duration_ms。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore
    from sebastian.memory.episodic_memory import EpisodicMemory

    published: list[dict] = []

    provider = MockLLMProvider(
        [
            ThinkingBlockStart(block_id="b0_0"),
            ThinkingDelta(block_id="b0_0", delta="hmm"),
            ThinkingBlockStop(block_id="b0_0", thinking="hmm"),
            TextBlockStart(block_id="b0_1"),
            TextDelta(block_id="b0_1", delta="ok"),
            TextBlockStop(block_id="b0_1", text="ok"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    original_publish = None

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    # Capture _publish calls
    async def capture_publish(session_id, event_type, payload):
        published.append({"type": event_type, "data": payload})

    agent._publish = capture_publish  # type: ignore[method-assign]

    await agent.run("hi", session_id="test_sess_01")

    stop_events = [e for e in published if "thinking_block" in str(e["type"]) and "stop" in str(e["type"])]
    assert len(stop_events) == 1
    duration_ms = stop_events[0]["data"].get("duration_ms")
    assert duration_ms is not None
    assert isinstance(duration_ms, int)
    assert duration_ms >= 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_thinking_duration.py -v
```

期望：FAIL（`duration_ms` 为 `None`）

- [ ] **Step 3: 在 `base_agent.py` 中加计时逻辑**

在 `_stream_inner` 方法内（`gen = self._loop.stream(...)` 之后，`while True:` 循环顶部之前）添加计时 dict：

```python
_thinking_start: dict[str, float] = {}
```

然后在循环体内，**在** `stream_event_type = _STREAM_EVENT_TYPES.get(type(event))` **之前**插入：

```python
if isinstance(event, ThinkingBlockStart):
    _thinking_start[event.block_id] = time.monotonic()

if isinstance(event, ThinkingBlockStop):
    start = _thinking_start.pop(event.block_id, None)
    if start is not None:
        event.duration_ms = int((time.monotonic() - start) * 1000)
```

确认文件顶部已有 `import time`（如没有则添加到标准库 import 区）。

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_thinking_duration.py -v
```

期望：PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_thinking_duration.py
git commit -m "feat(core): base_agent 追踪思考块耗时并注入 duration_ms"
```

---

## Task 3: Android — 数据模型增加 `durationMs`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`

- [ ] **Step 1: 修改 `StreamEvent.ThinkingBlockStop`**

打开 `data/model/StreamEvent.kt`，将：

```kotlin
data class ThinkingBlockStop(val sessionId: String, val blockId: String) : StreamEvent()
```

改为：

```kotlin
data class ThinkingBlockStop(
    val sessionId: String,
    val blockId: String,
    val durationMs: Long = 0,
) : StreamEvent()
```

- [ ] **Step 2: 修改 `ContentBlock.ThinkingBlock`**

打开 `data/model/ContentBlock.kt`，将：

```kotlin
data class ThinkingBlock(
    override val blockId: String,
    val text: String,
    val done: Boolean = false,
    val expanded: Boolean = false,
) : ContentBlock()
```

改为：

```kotlin
data class ThinkingBlock(
    override val blockId: String,
    val text: String,
    val done: Boolean = false,
    val expanded: Boolean = false,
    val durationMs: Long? = null,
) : ContentBlock()
```

- [ ] **Step 3: 编译确认无报错**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
```

期望：`BUILD SUCCESSFUL`

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt
git commit -m "feat(android/model): ThinkingBlockStop + ThinkingBlock 增加 durationMs"
```

---

## Task 4: Android — SSE 解析层透传 `durationMs`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`

- [ ] **Step 1: 修改 `thinking_block.stop` 解析分支**

打开 `SseFrameDto.kt`，将：

```kotlin
"thinking_block.stop" -> StreamEvent.ThinkingBlockStop(data.getString("session_id"), data.getString("block_id"))
```

改为：

```kotlin
"thinking_block.stop" -> StreamEvent.ThinkingBlockStop(
    sessionId  = data.getString("session_id"),
    blockId    = data.getString("block_id"),
    durationMs = data.optLong("duration_ms", 0L),
)
```

- [ ] **Step 2: 编译确认无报错**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
```

期望：`BUILD SUCCESSFUL`

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt
git commit -m "feat(android/sse): 解析 ThinkingBlockStop.duration_ms"
```

---

## Task 5: Android — ViewModel 透传 `durationMs`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

- [ ] **Step 1: 修改 `ThinkingBlockStop` 处理分支**

在 `ChatViewModel.kt` 中找到：

```kotlin
is StreamEvent.ThinkingBlockStop -> {
    updateBlockInCurrentMessage(event.blockId) { existing ->
        if (existing is ContentBlock.ThinkingBlock) existing.copy(done = true)
        else existing
    }
```

改为：

```kotlin
is StreamEvent.ThinkingBlockStop -> {
    updateBlockInCurrentMessage(event.blockId) { existing ->
        if (existing is ContentBlock.ThinkingBlock)
            existing.copy(
                done = true,
                durationMs = event.durationMs.takeIf { it > 0L },
            )
        else existing
    }
```

- [ ] **Step 2: 编译确认无报错**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
```

期望：`BUILD SUCCESSFUL`

- [ ] **Step 3: 运行现有 ViewModel 测试**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest" 2>&1 | tail -30
```

期望：所有已有测试 PASS

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
git commit -m "feat(android/vm): ThinkingBlockStop 透传 durationMs 到 ThinkingBlock"
```

---

## Task 6: Android — `ThinkingCard.kt` 极简 UI 重写

**Files:**
- Rewrite: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ThinkingCard.kt`
- Create: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ThinkingCardTest.kt`

- [ ] **Step 1: 写 `formatThinkingDuration` 单元测试**

新建 `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ThinkingCardTest.kt`：

```kotlin
package com.sebastian.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class ThinkingCardTest {

    @Test
    fun `formatThinkingDuration returns seconds only when under 60s`() {
        assertEquals("0s", formatThinkingDuration(0L))
        assertEquals("3s", formatThinkingDuration(3_000L))
        assertEquals("59s", formatThinkingDuration(59_999L))
    }

    @Test
    fun `formatThinkingDuration returns minutes and seconds at 60s boundary`() {
        assertEquals("1m 0s", formatThinkingDuration(60_000L))
        assertEquals("1m 25s", formatThinkingDuration(85_000L))
        assertEquals("2m 5s", formatThinkingDuration(125_000L))
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ThinkingCardTest" 2>&1 | tail -20
```

期望：FAIL（`formatThinkingDuration` 未定义）

- [ ] **Step 3: 重写 `ThinkingCard.kt`**

完整替换 `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ThinkingCard.kt`：

```kotlin
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.ui.common.AnimationTokens

internal fun formatThinkingDuration(ms: Long): String {
    val s = ms / 1000L
    return if (s < 60L) "${s}s" else "${s / 60L}m ${s % 60L}s"
}

@Composable
fun ThinkingCard(
    block: ContentBlock.ThinkingBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val pulseAlpha = remember { Animatable(AnimationTokens.THINKING_PULSE_MIN_ALPHA) }

    LaunchedEffect(block.done) {
        if (!block.done) {
            while (true) {
                pulseAlpha.animateTo(
                    targetValue = AnimationTokens.THINKING_PULSE_MAX_ALPHA,
                    animationSpec = tween(
                        durationMillis = AnimationTokens.THINKING_PULSE_DURATION_MS,
                        easing = AnimationTokens.THINKING_PULSE_EASING,
                    ),
                )
                pulseAlpha.animateTo(
                    targetValue = AnimationTokens.THINKING_PULSE_MIN_ALPHA,
                    animationSpec = tween(
                        durationMillis = AnimationTokens.THINKING_PULSE_DURATION_MS,
                        easing = AnimationTokens.THINKING_PULSE_EASING,
                    ),
                )
            }
        } else {
            pulseAlpha.snapTo(1f)
        }
    }

    val label = if (block.done) {
        val d = block.durationMs
        if (d != null && d > 0L) "Thought for ${formatThinkingDuration(d)}" else "Thought"
    } else {
        "Thinking"
    }

    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggle)
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!block.done) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .alpha(pulseAlpha.value)
                        .background(MaterialTheme.colorScheme.primary, CircleShape),
                )
                Spacer(Modifier.width(8.dp))
            }

            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )

            Icon(
                imageVector = when {
                    !block.done -> Icons.AutoMirrored.Filled.KeyboardArrowRight
                    block.expanded -> Icons.Default.KeyboardArrowUp
                    else -> Icons.Default.KeyboardArrowDown
                },
                contentDescription = if (block.expanded) "折叠" else "展开",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp),
            )
        }

        AnimatedVisibility(
            visible = block.expanded,
            enter = expandVertically(),
            exit = shrinkVertically(),
        ) {
            Column {
                HorizontalDivider(
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
                    thickness = 1.dp,
                )
                Text(
                    text = block.text,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            }
        }
    }
}
```

- [ ] **Step 4: 运行单元测试确认通过**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ThinkingCardTest" 2>&1 | tail -20
```

期望：PASS（2 tests）

- [ ] **Step 5: 编译全量确认无报错**

```bash
cd ui/mobile-android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -20
```

期望：`BUILD SUCCESSFUL`

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ThinkingCard.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ThinkingCardTest.kt
git commit -m "feat(android/ui): ThinkingCard 极简风格重写，显示耗时"
```

---

## 端到端验证

1. 启动后端：`uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8823 --reload`
2. 启动模拟器，`npx expo run:android`（或 `npx expo start` 若 APK 已装）
3. App Settings 填入 `http://10.0.2.2:8823`，发一条需要思考的消息
4. 确认流式阶段显示「Thinking ›」，左侧圆点呼吸动画
5. 点击可展开/折叠思考内容
6. 完成后确认显示「Thought for Xs」或「Thought for Xm Ys」
7. 后端日志检查 `thinking_block.stop` payload 含 `duration_ms` 正整数值
8. `durationMs = null` 降级：可临时将后端 `duration_ms` 注释掉，确认 done 后显示「Thought」不崩溃

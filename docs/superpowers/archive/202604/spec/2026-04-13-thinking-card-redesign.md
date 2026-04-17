---
integrated_to: core/runtime.md + mobile/streaming.md
integrated_at: 2026-04-16
---

# ThinkingCard 极简风格重设计

**日期：** 2026-04-13
**范围：** 后端 stream_events + Android 数据模型 + ThinkingCard UI

---

## Context

当前 `ThinkingCard` 使用 `Card` 容器（`surfaceVariant` 背景 + 圆角）+ `Psychology` 图标，视觉偏重，与消息流割裂。目标是对齐 DeepSeek App 的极简思考卡片风格：无背景容器、行式布局、显示耗时。

---

## 变更范围

### 1. 后端 — `sebastian/core/stream_events.py`

`ThinkingBlockStop` 增加 `duration_ms` 字段：

```python
@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str
    signature: str | None = None
    duration_ms: int | None = None  # 新增
```

### 2. 后端 — `sebastian/core/base_agent.py`

在 `_stream_inner` 方法内：
- 收到 `ThinkingBlockStart` 事件时，用 `time.monotonic()` 记录开始时间（按 `block_id` 存入局部 dict）
- 发出 `ThinkingBlockStop` 时，计算差值注入 `duration_ms`（单位 ms，取整）

### 3. Android — `StreamEvent.kt`

```kotlin
data class ThinkingBlockStop(
    val sessionId: String,
    val blockId: String,
    val durationMs: Long = 0,   // 新增
) : StreamEvent()
```

### 4. Android — `ContentBlock.kt`

```kotlin
data class ThinkingBlock(
    override val blockId: String,
    val text: String,
    val done: Boolean = false,
    val expanded: Boolean = false,
    val durationMs: Long? = null,   // 新增
) : ContentBlock()
```

### 5. Android — `data/remote/dto/SseFrameDto.kt`

`parseByType` 中 `thinking_block.stop` 分支，增加读取 `data.optLong("duration_ms", 0)`：

```kotlin
"thinking_block.stop" -> StreamEvent.ThinkingBlockStop(
    sessionId = data.getString("session_id"),
    blockId   = data.getString("block_id"),
    durationMs = data.optLong("duration_ms", 0),
)
```

### 6. Android — `viewmodel/ChatViewModel.kt`

`ThinkingBlockStop` 处理分支，`copy` 时同步写入 `durationMs`：

```kotlin
is StreamEvent.ThinkingBlockStop -> {
    updateBlockInCurrentMessage(event.blockId) { existing ->
        if (existing is ContentBlock.ThinkingBlock)
            existing.copy(done = true, durationMs = event.durationMs.takeIf { it > 0 })
        else existing
    }
}
```

### 6. Android — `ThinkingCard.kt` 重写

#### 耗时格式函数

```kotlin
private fun formatDuration(ms: Long): String {
    val s = ms / 1000
    return if (s < 60) "${s}s" else "${s / 60}m ${s % 60}s"
}
```

#### 布局结构

```
┌── Row（fillMaxWidth，clickable，padding 4dp v / 0dp h）──────────────┐
│  [●圆点 8dp，呼吸动画，仅 thinking 中可见]                              │
│  [文字："Thinking" | "Thought for Xs"]   weight=1                    │
│  [Icon：chevron_right（thinking）| arrow_down/up（done）]             │
└──────────────────────────────────────────────────────────────────────┘
AnimatedVisibility（expanded）
  HorizontalDivider（1dp，outline 色）
  Text（block.text，bodySmall，onSurfaceVariant，padding 0dp h / 8dp v）
```

#### 状态说明

| 状态 | 圆点 | 文字 | Icon |
|------|------|------|------|
| thinking（`!done`） | 可见，呼吸动画 | `Thinking` | `chevron_right` |
| done（`done=true`） | 不可见 | `Thought for Xs` / `Thought for Xm Ys` | `keyboard_arrow_down/up` |

- 两态均可点击展开/折叠（`onToggle`）
- 无 `Card` 容器，无背景色，完全融入消息流
- 圆点：`Box`（8dp × 8dp，`CircleShape`，`primary` 色），用现有 `THINKING_PULSE` token 做 alpha 呼吸动画

---

## 验证步骤

1. 启动后端 + Android 模拟器
2. 发一条需要思考的消息，确认：
   - 流式阶段显示「Thinking ›」，圆点呼吸动画正常
   - 点击可展开/折叠思考内容
   - 完成后显示「Thought for Xs」或「Thought for Xm Ys」（视实际耗时）
   - 展开时出现分隔线 + 思考文本
3. 检查后端 SSE 日志，确认 `thinking_block.stop` payload 含 `duration_ms` 字段
4. `durationMs = null`（旧数据/后端未传）时，done 状态降级显示「Thought」（不带耗时）

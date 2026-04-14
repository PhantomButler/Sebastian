---
version: "1.0"
last_updated: 2026-04-11
status: in-progress
---

# 流式渲染与连接层

*← [Mobile Spec 索引](INDEX.md)*

---

## 1. SSE 连接架构

### 1.1 线程模型

```
后端 Gateway
    │
    │ HTTP/SSE
    ▼
OkHttp EventSource（IO Thread）
    │ callbackFlow
    ▼
Flow<StreamEvent>（IO Dispatcher）
    │ 增量 Markdown 解析 / 事件路由
    ▼
ChatViewModel.uiState: StateFlow<ChatUiState>（Default Dispatcher）
    │ collectAsState()
    ▼
Compose（Main Thread）— 只做 recomposition
```

Main Thread 全程只负责 Compose 重组，不碰任何网络或解析逻辑。

### 1.2 连接生命周期

```kotlin
class SseClient @Inject constructor(
    private val okHttpClient: OkHttpClient,
    private val connectivityManager: ConnectivityManager,
) {
    // Lifecycle-aware：由 ViewModel 在 viewModelScope 中收集
    // onStart 时 collect，onStop 时 scope 取消自动断开，无泄漏
    fun sessionStream(sessionId: String, lastEventId: String?): Flow<StreamEvent>
    fun globalStream(): Flow<StreamEvent>
}
```

**连接策略**：

| 场景 | 行为 |
|------|------|
| App 进入前台（`ON_START`）| 启动 SSE 连接 |
| App 进入后台（`ON_STOP`）| ViewModel scope 取消，连接自动断开 |
| 网络断开 | `ConnectivityManager` 回调感知，标记 `isOffline = true` |
| 网络恢复 | 自动触发重连，带 `Last-Event-ID` 补偿断线期间事件 |
| SSE 错误 | 指数退避重连（1s / 2s / 4s），最多 3 次，失败后显示离线 Banner |

### 1.3 Last-Event-ID 补偿

与 RN 版相同的逻辑，但在 IO 线程原子更新，无竞态问题：

- 新会话 / 进行中会话（最后消息为 user）：携带 `Last-Event-ID: 0` 请求全量回放
- 已完成会话（最后消息为 assistant）：不带 ID，只订阅新事件
- 断线重连：携带最后收到的 event ID，续接

---

## 2. 消息内容模型

消息由有序的 `ContentBlock` 列表组成，顺序即渲染顺序：

```kotlin
sealed class ContentBlock {
    data class TextBlock(
        val blockId: String,
        val text: String,
        val done: Boolean,           // true = 流式完成，可渲染 Markdown
    ) : ContentBlock()

    data class ThinkingBlock(
        val blockId: String,
        val text: String,
        val done: Boolean,
    ) : ContentBlock()

    data class ToolBlock(
        val toolId: String,
        val name: String,
        val input: String,           // JSON 字符串
        val status: ToolStatus,      // running / done / failed
        val result: ToolResult?,
    ) : ContentBlock()

    // Phase 2 新增
    data class ImageBlock(
        val url: String,
        val altText: String? = null,
    ) : ContentBlock()

    // Phase 2 新增
    data class FileBlock(
        val name: String,
        val url: String,
        val sizeBytes: Long,
    ) : ContentBlock()
}

sealed class ToolResult {
    data class Text(val content: String) : ToolResult()
    data class Image(val url: String) : ToolResult()  // Phase 2
}
```

`ImageBlock` 在 `tool.executed` 结果含图片 URL 时由前端自动插入，后端协议扩展见 Phase 2。

---

## 3. 流式 Markdown 渲染

### 3.1 核心策略：块级增量渲染

```
已完成的 TextBlock（done=true）→ 后台协程 Markwon 解析 → AnnotatedString → Compose Text
进行中的 TextBlock（done=false）→ 纯文本直接渲染 → Compose Text
```

视觉效果：已完成段落立即呈现 Markdown 样式（标题、加粗、列表），光标所在的当前段落为纯文本，块完成时无缝切换，无整体跳变闪烁。

### 3.2 数据流

```kotlin
// IO Dispatcher — 不占 Main Thread
private fun parseMarkdown(text: String): AnnotatedString =
    withContext(Dispatchers.IO) {
        markwon.toMarkdown(text).toAnnotatedString()
    }
```

```kotlin
// ViewModel 中，每个 TextBlock 完成时触发一次解析
case StreamEvent.TextBlockStop -> {
    val block = findBlock(blockId)
    val rendered = parseMarkdown(block.text)  // IO 线程
    updateBlock(blockId, block.copy(rendered = rendered, done = true))
}
```

### 3.3 Delta 节流（50ms flush）

SSE delta 以原始速度到达，直接更新 UI 会产生不必要的重组压力。在 IO 协程中缓冲 50ms 统一 flush：

```kotlin
// IO 线程缓冲，约 20fps，视觉上无感知
val deltaBuffer = MutableStateFlow("")
deltaBuffer
    .debounce(50)
    .collect { buffered -> updateStreamingText(blockId, buffered) }
```

换行符触发立即 flush（保证新行及时出现），其余 delta 在缓冲窗口内合并。

---

## 4. 流式输出动画

### 4.1 逐块淡入（Phase 1）

每次 delta flush 后新增的内容片段以 `200ms` 淡入动画出现：

```kotlin
data class AnimatedChunk(
    val content: AnnotatedString,
    val alpha: Animatable<Float, AnimationVector1D> = Animatable(0f),
)

// 新 chunk 加入时（在协程中，不阻塞 Main Thread）
val chunk = AnimatedChunk(newContent)
chunks.add(chunk)
chunk.alpha.animateTo(1f, tween(durationMillis = 200))
```

```kotlin
// Compose 渲染
chunks.forEach { chunk ->
    Text(
        text = chunk.content,
        modifier = Modifier.graphicsLayer { alpha = chunk.alpha.value }
    )
}
```

视觉感知：已渲染内容保持不动，新内容从透明淡入，无打字机逐字符效果，更接近 Gemini 的「批次涌现」感。

### 4.2 梯度遮罩扫描（Phase 3 升级）

在 Phase 1 淡入基础上，给每个新 chunk 叠加从左到右的梯度遮罩动画，视觉上呈现文字「从左侧隐现」的扫描效果。

通过自定义 `Modifier.streamingReveal()` 实现，对已有 chunk 无影响，可独立于核心渲染逻辑随时叠加：

```kotlin
// Phase 3 时只需给 AnimatedChunk 的 Text 加这一个 Modifier
Modifier.drawWithContent {
    clipRect(0f, 0f, size.width * revealProgress.value, size.height) {
        this@drawWithContent.drawContent()
    }
}
```

---

## 5. 滚动跟随逻辑

### 5.1 状态定义

```kotlin
enum class ScrollFollowState {
    FOLLOWING,      // 跟随底部（新内容到达时自动滚动）
    DETACHED,       // 用户主动上滑，停止跟随
    NEAR_BOTTOM,    // 用户滚动回接近底部（距底 < 200dp），恢复跟随
}
```

### 5.2 规则

| 事件 | 行为 |
|------|------|
| 流式 delta 到达 + `FOLLOWING` | 滚动到底部（`animated = false`，避免动画堆积）|
| 用户开始拖动列表（`onDragStarted`）| 切换到 `DETACHED` |
| 用户拖动结束，距底 < 200dp | 切换回 `FOLLOWING` |
| 用户拖动结束，距底 ≥ 200dp | 保持 `DETACHED`，显示「回到底部」浮动按钮 |
| 用户点击「回到底部」按钮 | 滚动到底部，切换回 `FOLLOWING`（`animated = true`）|
| 新一条用户消息发出 | 强制切换回 `FOLLOWING`，滚动到底部 |

### 5.3 原生实现优势

Compose `LazyColumn` 的 `rememberLazyListState()` 提供精确的 `firstVisibleItemScrollOffset` 和 `layoutInfo`，可精准计算「距底距离」。`scrollToItem()` / `animateScrollToItem()` 直接操作，无 JS Thread 竞态，滚动跟随稳定性远超 RN 版 FlatList + `scrollToOffset(99999)` 的方案。

---

## 6. 动画状态语言

Sebastian 的工作状态通过 Header 区域（或消息区域入口）的视觉动画传达，目标是让用户直觉感知 Agent 状态，类似「贾维斯在呼吸」的自然感。

所有动画参数统一定义在 `AnimationTokens.kt`，修改参数不需要触碰各组件：

```kotlin
object AnimationTokens {
    // Thinking：慢呼吸光晕
    val thinkingPulseDuration = 2000       // ms，一次呼吸周期
    val thinkingPulseMinAlpha = 0.4f
    val thinkingPulseMaxAlpha = 1.0f
    val thinkingPulseEasing = FastOutSlowInEasing

    // Streaming：chunk 淡入（光标闪烁为 Phase 2，暂不实现）
    val streamingChunkFadeIn = 200         // ms，新 chunk 淡入

    // Working（工具调用进行中）：脉冲环
    val workingPulseDuration = 1200        // ms
    val workingRingColor = 0xFF4CAF50      // 绿色

    // 状态切换：AnimatedContent crossfade
    val stateTransitionDuration = 300      // ms
}
```

**四种状态的视觉表现**：

| 状态 | 触发条件 | 动画 |
|------|---------|------|
| `idle` | 无进行中操作 | 无动画，静止 |
| `thinking` | `thinking_block.start` 到 `thinking_block.stop` | Header 图标慢速呼吸光晕（alpha 0.4 → 1.0，2s 周期，`InfiniteTransition`）|
| `streaming` | `text_block.start` 到 `text_block.stop` | 逐块淡入（光标闪烁 Phase 2）|
| `working` | `tool.running` 到 `tool.executed` | 工具卡片左侧脉冲圆点（橙色跳动），工具组 Header 转动进度环 |

状态切换通过 `AnimatedContent` 完成，各状态之间 crossfade 300ms，不跳变。

---

*← [Mobile Spec 索引](INDEX.md)*

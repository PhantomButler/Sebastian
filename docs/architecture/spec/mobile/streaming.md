---
version: "1.2"
last_updated: 2026-04-17
status: implemented
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
        val durationMs: Long? = null,   // thinking 耗时（ms），来自后端 thinking_block.stop 事件
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

基于 **multiplatform-markdown-renderer v0.40.2**（mikepenz/multiplatform-markdown-renderer），纯 Compose 原生实现。

### 3.1 核心策略：统一渲染路径

```
所有 TextBlock（done 与否）→ MarkdownView(String) → 库内 remember(content) 缓存解析
```

所有状态（流式中、完成态、历史加载）走同一路径 `MarkdownView(text = block.text)`，库内部用 `rememberMarkdownState(retainState = true)` 缓存解析结果。无预解析层，无 `CharSequence` 中间态，历史加载和流式渲染无差别处理。

> **技术选型决策**：替换原先的 Markwon（`io.noties.markwon`）+ `AndroidView(TextView)` 方案。Markwon 基于 TextView，在 Compose 中需 AndroidView 包装，导致流式→完成态布局跳变、大列表滚动性能不佳、历史会话因 `renderedMarkdown=null` 降级为纯文本。新库是纯 Composable，消除上述所有问题。

### 3.2 依赖配置（`app/build.gradle.kts`）

```kotlin
// libs.versions.toml: mikepenz-markdown = "0.40.2"
implementation(libs.mikepenz.markdown.android)   // com.mikepenz:multiplatform-markdown-renderer-android
implementation(libs.mikepenz.markdown.m3)         // Material 3 主题零配置继承
implementation(libs.mikepenz.markdown.code)       // 代码高亮（基于 Highlights 库）
```

已移除所有 `io.noties.markwon:*` 依赖。

### 3.3 组件结构

**`MarkdownView.kt`**

```kotlin
@Composable
fun MarkdownView(text: String, modifier: Modifier = Modifier) {
    val markdownState = rememberMarkdownState(text, retainState = true)
    Markdown(
        markdownState = markdownState,
        modifier = modifier,
        colors = MarkdownDefaults.colors(),
        typography = MarkdownDefaults.typography(),
        components = MarkdownDefaults.components(),
    )
}
```

**`MarkdownDefaults.kt`** — 集中管理所有 markdown 样式配置

```kotlin
object MarkdownDefaults {
    @Composable fun colors(): MarkdownColors         // 跟随 MaterialTheme
    @Composable fun typography(): MarkdownTypography // 跟随 MaterialTheme.typography
    @Composable fun components(): MarkdownComponents // 注册代码块高亮
}
```

> **实现差异**：原设计为独立 `CodeBlockView.kt` 文件，实际实现将代码块渲染逻辑合并进 `MarkdownDefaults.kt`，通过 `MarkdownHighlightedCodeBlock` / `MarkdownHighlightedCodeFence` 组件注入 `MarkdownComponents`，使用 `SyntaxThemes.atom(darkMode = isDark)` 语法高亮配色。

**视觉规格**：

| 元素 | 规格 |
|------|------|
| 正文 | `bodyLarge`（16sp），行高 1.5x |
| H1/H2/H3 | `headlineMedium` / `titleLarge` / `titleMedium` |
| 列表 | 正文字号，左缩进 16dp |
| 引用块 `>` | 左侧 3dp 主题色竖线，文字 alpha 0.7 |
| 代码块 | 固定深色背景（`#1E1E1E`），等宽字体 13sp，水平可滚动，复制按钮 |
| 行内代码 | 等宽字体，`onSurface` 叠 8% alpha 背景，圆角 4dp |
| 链接 | `primary` 色，可跳转 |

### 3.4 数据模型

`TextBlock` 无 `renderedMarkdown` 字段，Markdown 解析在 Composable 渲染时由库内部处理：

```kotlin
data class TextBlock(
    override val blockId: String,
    val text: String,
    val done: Boolean = false,  // 流式淡入动画的 isDone 判断
) : ContentBlock()
```

`ChatViewModel` 的 `TextBlockStop` handler 简化为只做 flush + `done=true`，无异步 parse 协程。

### 3.5 Delta 节流（50ms flush）

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

## 6. ThinkingCard 极简风格

对标 DeepSeek App 的极简思考卡片：无 Card 容器、行式布局、显示耗时。完全融入消息流，无背景色，无圆角容器。

### 6.1 布局结构

```
┌── Row（fillMaxWidth，clickable，padding 4dp v / 0dp h）──────────────┐
│  [●圆点 8dp，呼吸动画，仅 thinking 中可见]                              │
│  [文字："Thinking" | "Thought for Xs"]   weight=1                    │
│  [Icon：chevron_right（thinking）| arrow_down/up（done）]             │
└──────────────────────────────────────────────────────────────────────┘
AnimatedVisibility（expanded）
  左侧装饰线（dot + verticalLine，primary 色）
  Text（block.text，bodySmall，onSurfaceVariant）
```

### 6.2 状态表现

| 状态 | 圆点 | 文字 | Icon |
|------|------|------|------|
| thinking（`!done`） | 可见，呼吸动画 | `Thinking` | `chevron_right` |
| done（`done=true`） | 不可见 | `Thought for Xs` / `Thought for Xm Ys` | `keyboard_arrow_down/up` |

两态均可点击展开/折叠。圆点使用 `AnimationTokens` 中 `THINKING_PULSE` 的 alpha 呼吸动画。

### 6.3 耗时格式

```kotlin
fun formatThinkingDuration(ms: Long): String {
    val s = ms / 1000
    return if (s < 60) "${s}s" else "${s / 60}m ${s % 60}s"
}
```

`durationMs == null`（旧数据 / 后端未传）时，done 状态降级显示 `Thought`（不带耗时）。

### 6.4 数据链路

后端 `thinking_block.stop` SSE 事件携带 `duration_ms` → `SseFrameDto` 解析 → `StreamEvent.ThinkingBlockStop.durationMs` → `ChatViewModel` 写入 `ContentBlock.ThinkingBlock.durationMs` → `ThinkingCard` 读取并格式化显示。

---

## 7. 动画状态语言

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

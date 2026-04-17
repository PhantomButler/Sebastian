---
integrated_to: mobile/streaming.md
integrated_at: 2026-04-17
---

# Markdown 渲染升级设计文档

**日期**：2026-04-14  
**状态**：已批准  
**范围**：Android App — 助手消息 `TextBlock` 正文渲染层

---

## 背景与问题

当前 Markdown 渲染基于 Markwon（`io.noties.markwon`），通过 `AndroidView(TextView)` 包装进 Compose，存在以下问题：

1. **历史会话不渲染 Markdown**：`toDomain()` 构造的 `TextBlock` 仅有 `done=true`、`renderedMarkdown=null`，`switchSession()` 加载历史后从不触发解析，UI 降级为纯文本 `Text()`
2. **流式→完成态布局跳变**：流式中用 Compose `Text`，`TextBlockStop` 后切换为 `AndroidView(TextView)`，是两个不同 Composable 节点，造成明显排版跳变
3. **Markwon 插件不足**：只有 `StrikethroughPlugin` + `TablePlugin`，缺语法高亮、链接、GFM Task List
4. **AndroidView 性能**：大量消息时 `AndroidView` 回收策略不如原生 Composable，滚动有卡顿感

---

## 决策

### 技术选型

替换为 **multiplatform-markdown-renderer v0.40.2**（mikepenz/multiplatform-markdown-renderer）：

- 纯 Compose 原生实现，消除 AndroidView 包装
- 专有 `-m3` 模块，Material 3 主题零配置继承
- 独立代码高亮模块（`-code`），基于 Highlights 库
- LazyColumn 支持大文档，活跃维护（2026-04-07 最新发布）

排除方案：
- **compose-richtext**：官方标注 experimental，roadmap 不明确
- **FluidMarkdown**（Ant Group）：文档中文为主，长期维护不确定
- **compose-markdown**（jeziellago）：无语法高亮，不支持 LazyColumn

### 架构方案

采用**方案 A（纯 Composable 渲染，移除预解析层）**：

新库的 `Markdown(content: String)` 是原生 Composable，内部用 `remember(content)` 缓存解析。直接传入 `block.text` 字符串渲染，无需预解析为 `CharSequence`，历史加载和流式渲染走同一路径。

---

## 变更范围

**仅修改助手消息 `TextBlock` 正文渲染区**，以下组件不动：
- 用户消息气泡
- ThinkingCard（思考卡片）
- ToolCallCard（工具调用卡片）

---

## 组件设计

### 新增依赖（`app/build.gradle.kts`）

```kotlin
val markdownVersion = "0.40.2"
implementation("com.mikepenz:multiplatform-markdown-renderer-android:$markdownVersion")
implementation("com.mikepenz:multiplatform-markdown-renderer-m3:$markdownVersion")
implementation("com.mikepenz:multiplatform-markdown-renderer-code:$markdownVersion")
```

删除所有 `io.noties.markwon:*` 依赖。

### `common/MarkdownView.kt`（重写）

```kotlin
@Composable
fun MarkdownView(
    text: String,
    modifier: Modifier = Modifier,
)
```

- 直接调用库的 `Markdown()` composable
- 传入 `MarkdownDefaults.colors()`、`MarkdownDefaults.typography()`、`MarkdownDefaults.components()`
- 不再接收 `CharSequence`，调用方统一传 `String`

### `common/MarkdownDefaults.kt`（新建）

集中管理所有 markdown 样式配置：

```kotlin
object MarkdownDefaults {
    @Composable fun colors(): MarkdownColors         // 跟随 MaterialTheme
    @Composable fun typography(): MarkdownTypography // 跟随 MaterialTheme.typography
    @Composable fun components(): MarkdownComponents // 注册 CodeBlockView
}
```

### `common/CodeBlockView.kt`（新建）

作为代码块的自定义渲染器注入库的 `MarkdownComponents`：

**布局结构：**

```
┌──────────────────────────────────────────┐
│  Column                                  │
│  ┌────────────────────────────────────┐  │
│  │ Row (Header, 36dp)                 │  │
│  │  Text(language, alpha=0.6)  [Copy] │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ HorizontalScrollable               │  │
│  │   SelectionContainer               │  │
│  │     Text(highlighted, mono, 13sp)  │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

**样式规格：**
- 背景：`#1E1E1E`（固定深色，不跟随系统 Light/Dark）
- 默认代码文字颜色：`#D4D4D4`（VS Code Dark+ 配色）
- 圆角：8dp，内边距：水平 16dp / 垂直 12dp
- 语法高亮：`multiplatform-markdown-renderer-code` 的 `CodeHighlighter`，语言名自动匹配
- 复制按钮：点击后图标切换为「✓」，1.5s 后 reset，使用 `LocalClipboardManager`
- 水平可滚动（长行不换行）

**手势冲突说明**：`SlidingThreePaneLayout` 已在第 98–107 行通过 `change.isConsumed` 检测子组件消费，代码块的 `Modifier.horizontalScroll()` 会正确标记事件为已消费，三面板自动退出。到达代码块边界后需抬起手指重新滑动触发面板切换，这是标准移动交互行为。

---

## 视觉规格

### 正文排版

| 元素 | 规格 |
|------|------|
| 正文 | `bodyLarge`（16sp），行高 1.5x |
| `#` H1 | `headlineMedium`，底部 8dp |
| `##` H2 | `titleLarge`，底部 6dp |
| `###` H3 | `titleMedium`，底部 4dp |
| 列表 | 正文字号，左缩进 16dp，行间距 4dp |
| 引用块 `>` | 左侧 3dp 主题色竖线，内容缩进，文字 alpha 0.7 |
| 分隔线 `---` | 1dp，`onSurface.copy(alpha=0.12)` |
| 链接 | `primary` 色，点击可跳转 |
| 删除线 | `onSurface.copy(alpha=0.5)` |
| GFM Task List | 不可交互复选框图标 |

### 行内代码

等宽字体，`onSurface` 叠 8% alpha 背景，左右 4dp padding，圆角 4dp。

---

## 数据模型变更

### `ContentBlock.TextBlock`

```kotlin
// 删除 renderedMarkdown 字段
data class TextBlock(
    override val blockId: String,
    val text: String,
    val done: Boolean = false,
    // renderedMarkdown: CharSequence? — 已删除
) : ContentBlock()
```

`done` 字段保留（流式淡入动画的 `isDone` 判断仍需要）。

---

## 数据流变更

```
改前：
TextDelta → flusher(50ms) → TextBlock.text
TextBlockStop → parse(IO) → TextBlock.renderedMarkdown → MarkdownView(CharSequence)
历史加载 → TextBlock(done=true, renderedMarkdown=null) → Text() 纯文本降级

改后：
TextDelta → flusher(50ms) → TextBlock.text → MarkdownView(String) [库内 remember 缓存]
TextBlockStop → TextBlock(done=true) → MarkdownView(String) [同一路径]
历史加载 → TextBlock(done=true) → MarkdownView(String) [自动修复]
```

---

## `ChatViewModel` 变更

`TextBlockStop` handler 简化为只做 flush + `done=true`，删除异步 parse 协程：

```kotlin
is StreamEvent.TextBlockStop -> {
    val msgId = currentAssistantMessageId ?: return
    val pendingText = pendingDeltas.remove(event.blockId)?.toString() ?: ""
    if (pendingText.isNotEmpty()) {
        updateBlockById(msgId, event.blockId) { existing ->
            if (existing is ContentBlock.TextBlock)
                existing.copy(text = existing.text + pendingText)
            else existing
        }
    }
    updateBlockById(msgId, event.blockId) { existing ->
        if (existing is ContentBlock.TextBlock) existing.copy(done = true)
        else existing
    }
}
```

同时删除：`markdownParser` 注入字段、parse 相关 `withContext(dispatcher)` 协程块。

---

## `StreamingMessage.kt` 变更

`TextBlock` 渲染从三分支简化为一行：

```kotlin
// 改前
is ContentBlock.TextBlock -> {
    if (block.done && block.renderedMarkdown != null) {
        MarkdownView(markdown = block.renderedMarkdown, ...)
    } else {
        Text(text = block.text, ...)
    }
}

// 改后
is ContentBlock.TextBlock -> {
    MarkdownView(text = block.text, ...)
}
```

---

## 文件变更汇总

| 操作 | 文件 |
|------|------|
| 删除 | `data/local/MarkdownParser.kt` |
| 删除 | `data/local/MarkwonMarkdownParser.kt` |
| 修改 | `data/model/ContentBlock.kt`（删 `renderedMarkdown`） |
| 修改 | `viewmodel/ChatViewModel.kt`（删 parse 逻辑、删 markdownParser 注入） |
| 修改 | `di/` 中 MarkdownParser 绑定（删除） |
| 重写 | `ui/common/MarkdownView.kt` |
| 新建 | `ui/common/MarkdownDefaults.kt` |
| 新建 | `ui/common/CodeBlockView.kt` |
| 修改 | `ui/chat/StreamingMessage.kt`（简化 TextBlock 分支） |
| 修改 | `app/build.gradle.kts`（替换 Markwon 依赖） |

---

## 测试要点

1. 历史会话加载后 TextBlock 正确渲染 Markdown（标题、列表、代码块）
2. 流式输出全程渲染 Markdown，无纯文本→格式文本跳变
3. 代码块语法高亮正确，复制按钮可用
4. 代码块横向滚动与三面板手势不冲突
5. Light/Dark 主题切换时正文样式跟随，代码块背景保持深色
6. 长对话（20+ 条消息）滚动流畅，无明显卡顿

# Markdown 渲染升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 multiplatform-markdown-renderer v0.40.2 替换 Markwon，修复历史会话不渲染 Markdown、流式切换跳变两个 bug，并升级代码块视觉为深色背景 + 语法高亮 + 复制按钮。

**Architecture:** 删除预解析层（MarkdownParser 接口 + 实现 + DI），TextBlock 直接持有原始文本字符串，MarkdownView 在渲染侧调用库的 `Markdown()` composable（内部 `remember(content)` 缓存解析），流式和历史加载走同一路径。

**Tech Stack:** multiplatform-markdown-renderer-android/m3/code 0.40.2，Jetpack Compose，Material 3，intellij-markdown（库内部解析器）。

---

## 文件变更总览

| 操作 | 路径 |
|------|------|
| 删除 | `app/src/main/java/com/sebastian/android/data/local/MarkdownParser.kt` |
| 删除 | `app/src/main/java/com/sebastian/android/data/local/MarkwonMarkdownParser.kt` |
| 删除 | `app/src/main/java/com/sebastian/android/di/MarkdownModule.kt` |
| 修改 | `gradle/libs.versions.toml` |
| 修改 | `app/build.gradle.kts` |
| 修改 | `app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` |
| 修改 | `app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt` |
| 重写 | `app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt` |
| 新建 | `app/src/main/java/com/sebastian/android/ui/common/MarkdownDefaults.kt` |
| 新建 | `app/src/main/java/com/sebastian/android/ui/common/CodeBlockView.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt` |

所有路径相对于 `ui/mobile-android/`。

---

## Task 1: Gradle — 替换 Markwon 为 mikepenz-markdown

**Files:**
- Modify: `ui/mobile-android/gradle/libs.versions.toml`
- Modify: `ui/mobile-android/app/build.gradle.kts`

- [ ] **Step 1: 更新 libs.versions.toml**

在 `[versions]` 中，删除 `markwon = "4.6.2"`，新增：
```toml
mikepenz-markdown = "0.40.2"
```

在 `[libraries]` 的 `# Image + Markdown` 注释区块下，删除三行 markwon 条目：
```toml
markwon-core = { group = "io.noties.markwon", name = "core", version.ref = "markwon" }
markwon-strikethrough = { group = "io.noties.markwon", name = "ext-strikethrough", version.ref = "markwon" }
markwon-tables = { group = "io.noties.markwon", name = "ext-tables", version.ref = "markwon" }
```

替换为三行 mikepenz 条目：
```toml
mikepenz-markdown-android = { group = "com.mikepenz", name = "multiplatform-markdown-renderer-android", version.ref = "mikepenz-markdown" }
mikepenz-markdown-m3 = { group = "com.mikepenz", name = "multiplatform-markdown-renderer-m3", version.ref = "mikepenz-markdown" }
mikepenz-markdown-code = { group = "com.mikepenz", name = "multiplatform-markdown-renderer-code", version.ref = "mikepenz-markdown" }
```

- [ ] **Step 2: 更新 build.gradle.kts**

在 `app/build.gradle.kts` 中，删除：
```kotlin
implementation(libs.markwon.core)
implementation(libs.markwon.strikethrough)
implementation(libs.markwon.tables)
```

替换为：
```kotlin
implementation(libs.mikepenz.markdown.android)
implementation(libs.mikepenz.markdown.m3)
implementation(libs.mikepenz.markdown.code)
```

- [ ] **Step 3: Gradle sync 验证**

```bash
cd ui/mobile-android
./gradlew :app:assembleDebug 2>&1 | tail -5
```

预期：此时因为 `MarkdownModule.kt` 仍引用 `MarkwonMarkdownParser`，**会编译失败**，这是正常的——后续任务会修复。  
只要 Gradle dependency resolution 成功（能下载到 mikepenz 包）即可，看日志确认没有 `Could not resolve` 错误。

---

## Task 2: 删除 Markwon 相关文件

**Files:**
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/MarkdownParser.kt`
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/MarkwonMarkdownParser.kt`
- Delete: `ui/mobile-android/app/src/main/java/com/sebastian/android/di/MarkdownModule.kt`

- [ ] **Step 1: 删除三个文件**

```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/MarkdownParser.kt
rm ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/MarkwonMarkdownParser.kt
rm ui/mobile-android/app/src/main/java/com/sebastian/android/di/MarkdownModule.kt
```

- [ ] **Step 2: 确认删除**

```bash
ls ui/mobile-android/app/src/main/java/com/sebastian/android/data/local/
ls ui/mobile-android/app/src/main/java/com/sebastian/android/di/
```

预期：`MarkdownParser.kt`、`MarkwonMarkdownParser.kt` 不存在；`MarkdownModule.kt` 不存在。  
此时 `ChatViewModel.kt` 和 `ChatViewModelTest.kt` 仍引用这些类，编译仍会失败 — 后续任务修复。

---

## Task 3: 简化 ContentBlock.TextBlock — 删除 renderedMarkdown 字段

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`

- [ ] **Step 1: 删除 renderedMarkdown 字段**

将 `ContentBlock.kt` 中的 `TextBlock` 改为：

```kotlin
package com.sebastian.android.data.model

sealed class ContentBlock {
    abstract val blockId: String

    val isDone: Boolean get() = when (this) {
        is TextBlock     -> done
        is ThinkingBlock -> done
        is ToolBlock     -> status == ToolStatus.DONE || status == ToolStatus.FAILED
    }

    data class TextBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean = false,
    ) : ContentBlock()

    data class ThinkingBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean = false,
        val expanded: Boolean = false,
        val durationMs: Long? = null,
    ) : ContentBlock()

    data class ToolBlock(
        override val blockId: String,
        val toolId: String,
        val name: String,
        val inputs: String,
        val status: ToolStatus,
        val resultSummary: String? = null,
        val error: String? = null,
        val expanded: Boolean = false,
    ) : ContentBlock()
}

enum class ToolStatus { PENDING, RUNNING, DONE, FAILED }
```

---

## Task 4: 更新 ChatViewModelTest — 先修复测试（TDD）

**Files:**
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: 删除 markdownParser 相关引用**

从 `ChatViewModelTest.kt` 中做以下 4 处修改：

**删除** 第 4 行 import：
```kotlin
import com.sebastian.android.data.local.MarkdownParser
```

**删除** 第 46 行字段声明：
```kotlin
private lateinit var markdownParser: MarkdownParser
```

**删除** 第 60–61 行 mock 初始化：
```kotlin
markdownParser = mock()
whenever(markdownParser.parse(any())).thenAnswer { it.arguments[0] as String }
```

**修改** 第 73 行 ViewModel 构造（删除 `markdownParser` 参数）：
```kotlin
// 改前
viewModel = ChatViewModel(chatRepository, sessionRepository, settingsRepository, networkMonitor, markdownParser, dispatcher)
// 改后
viewModel = ChatViewModel(chatRepository, sessionRepository, settingsRepository, networkMonitor, dispatcher)
```

**修改** 第 268 行同样的构造调用：
```kotlin
// 改前
viewModel = ChatViewModel(failingRepo, sessionRepository, settingsRepository, networkMonitor, markdownParser, dispatcher)
// 改后
viewModel = ChatViewModel(failingRepo, sessionRepository, settingsRepository, networkMonitor, dispatcher)
```

- [ ] **Step 2: 确认测试此时编译失败（ViewModel 未改）**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest 2>&1 | grep -E "error:|FAILED" | head -10
```

预期：编译错误 — `ChatViewModel` 构造函数参数不匹配，这说明测试先于实现到位。

---

## Task 5: 更新 ChatViewModel — 删除 markdownParser，简化 TextBlockStop

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`

- [ ] **Step 1: 删除 markdownParser 注入，简化 TextBlockStop handler**

将 `ChatViewModel.kt` 头部依赖区，删除：
```kotlin
import com.sebastian.android.data.local.MarkdownParser
```
和
```kotlin
import kotlinx.coroutines.withContext
```
（若 withContext 无其他用处则删除）

将类构造函数参数删除 `markdownParser` 一行：
```kotlin
// 改前
@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val settingsRepository: SettingsRepository,
    private val networkMonitor: NetworkMonitor,
    private val markdownParser: MarkdownParser,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel()

// 改后
@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val settingsRepository: SettingsRepository,
    private val networkMonitor: NetworkMonitor,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel()
```

将 `TextBlockStop` 的 handler 替换为：
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

旧的异步 parse 协程（`viewModelScope.launch(dispatcher) { val rawText = ... val rendered = withContext ... }`）完整删除。

- [ ] **Step 2: 运行测试，确认全部通过**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest 2>&1 | tail -15
```

预期输出包含：
```
ChatViewModelTest > text_block_stop marks block as done PASSED
ChatViewModelTest > text_delta appends to TextBlock PASSED
ChatViewModelTest > composerState returns to IDLE_EMPTY after turn_response PASSED
...
BUILD SUCCESSFUL
```

- [ ] **Step 3: 提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt \
        app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt \
        app/src/main/java/com/sebastian/android/data/local \
        app/src/main/java/com/sebastian/android/di/MarkdownModule.kt \
        gradle/libs.versions.toml \
        app/build.gradle.kts
git commit -m "refactor(android): 移除 MarkdownParser 预解析层，切换 mikepenz-markdown 依赖

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 新建 MarkdownDefaults.kt

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/MarkdownDefaults.kt`

- [ ] **Step 1: 创建文件**

```kotlin
package com.sebastian.android.ui.common

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.sp
import com.mikepenz.markdown.compose.components.markdownComponents
import com.mikepenz.markdown.m3.markdownColor
import com.mikepenz.markdown.m3.markdownTypography
import com.mikepenz.markdown.model.MarkdownColors
import com.mikepenz.markdown.model.MarkdownComponents
import com.mikepenz.markdown.model.MarkdownTypography

object MarkdownDefaults {

    @Composable
    fun colors(): MarkdownColors = markdownColor(
        text = MaterialTheme.colorScheme.onSurface,
        linkText = MaterialTheme.colorScheme.primary,
        inlineCodeText = MaterialTheme.colorScheme.onSurface,
        inlineCodeBackground = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f),
        dividerColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f),
    )

    @Composable
    fun typography(): MarkdownTypography = markdownTypography(
        h1 = MaterialTheme.typography.headlineMedium,
        h2 = MaterialTheme.typography.titleLarge,
        h3 = MaterialTheme.typography.titleMedium,
        h4 = MaterialTheme.typography.titleSmall,
        h5 = MaterialTheme.typography.bodyLarge,
        h6 = MaterialTheme.typography.bodyMedium,
        text = MaterialTheme.typography.bodyLarge,
        code = TextStyle(
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            lineHeight = 20.sp,
        ),
        inlineCode = MaterialTheme.typography.bodyMedium.copy(
            fontFamily = FontFamily.Monospace,
        ),
    )

    @Composable
    fun components(): MarkdownComponents = markdownComponents(
        codeFence = { model ->
            // 从 AST 节点提取语言标识和代码内容
            // intellij-markdown token type names: FENCE_LANG, CODE_FENCE_CONTENT
            val language = model.node.children
                ?.firstOrNull { it.type.name == "FENCE_LANG" }
                ?.getTextInNode(model.content)
                ?.trim()
                ?.toString() ?: ""
            val code = model.node.children
                ?.filter { it.type.name == "CODE_FENCE_CONTENT" }
                ?.joinToString("") { it.getTextInNode(model.content) }
                ?.trimEnd() ?: ""
            CodeBlockView(code = code, language = language)
        },
    )
}
```

> **注意**：`model.node.children` 和 `getTextInNode` 来自 intellij-markdown 库（已被 multiplatform-markdown-renderer 传递依赖）。如果编译时找不到这些符号，检查实际的 `MarkdownComponentModel` 类定义，通常可以通过 `model.node` 访问 ASTNode 以及 `model.content` 获取完整 markdown 文本。如果库版本提供了更高层级的 utility extension，优先用那个。

- [ ] **Step 2: 编译验证（允许 CodeBlockView 尚未创建时报错）**

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin 2>&1 | grep -v "^w:" | grep -E "error:|CodeBlockView" | head -10
```

预期：只有 `CodeBlockView unresolved reference` 的错误（Task 7 解决），其余无编译错误。

---

## Task 7: 新建 CodeBlockView.kt

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/CodeBlockView.kt`

- [ ] **Step 1: 创建文件**

```kotlin
package com.sebastian.android.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val CodeBackground = Color(0xFF1E1E1E)
private val CodeTextColor = Color(0xFFD4D4D4)
private val CodeLabelAlpha = 0.6f

@Composable
fun CodeBlockView(
    code: String,
    language: String,
    modifier: Modifier = Modifier,
) {
    var isCopied by remember { mutableStateOf(false) }
    val clipboardManager = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    val scrollState = rememberScrollState()
    val displayLanguage = language.ifEmpty { "code" }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(CodeBackground),
    ) {
        // ── Header: language label + copy button ──────────────────
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(36.dp)
                .padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = displayLanguage,
                style = MaterialTheme.typography.labelSmall.copy(
                    fontFamily = FontFamily.Monospace,
                    color = CodeTextColor.copy(alpha = CodeLabelAlpha),
                ),
            )
            IconButton(
                onClick = {
                    clipboardManager.setText(AnnotatedString(code))
                    isCopied = true
                    scope.launch {
                        delay(1_500L)
                        isCopied = false
                    }
                },
                modifier = Modifier.size(28.dp),
            ) {
                Icon(
                    imageVector = if (isCopied) Icons.Default.Check else Icons.Default.ContentCopy,
                    contentDescription = if (isCopied) "已复制" else "复制代码",
                    tint = CodeTextColor.copy(alpha = CodeLabelAlpha),
                    modifier = Modifier.size(14.dp),
                )
            }
        }

        // ── Code content: horizontal scroll, monospace ────────────
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(scrollState)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            SelectionContainer {
                Text(
                    text = code,
                    style = TextStyle(
                        fontFamily = FontFamily.Monospace,
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = CodeTextColor,
                    ),
                    softWrap = false,
                )
            }
        }
    }
}
```

> **语法高亮 TODO**：`-code` 模块（`multiplatform-markdown-renderer-code`）提供 `rememberHighlighter()` 等 API 来生成带颜色 span 的 `AnnotatedString`。当前实现先用纯色文本确保结构正确，可在此 PR 后单独添加高亮：将 `Text(text = code, ...)` 替换为 `Text(text = highlighter.highlight(code, language), ...)`。

- [ ] **Step 2: 编译验证**

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin 2>&1 | grep -v "^w:" | grep "error:" | head -10
```

预期：无编译错误。

---

## Task 8: 重写 MarkdownView.kt

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt`

- [ ] **Step 1: 完整替换文件内容**

```kotlin
package com.sebastian.android.ui.common

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.mikepenz.markdown.m3.Markdown

/**
 * 渲染 Markdown 字符串。
 * 底层使用 multiplatform-markdown-renderer（纯 Compose，无 AndroidView 包装）。
 * 样式配置统一在 [MarkdownDefaults] 中定义。
 * 库内部对 content 做 remember(content) 缓存，50ms 节流下重解析开销可忽略。
 */
@Composable
fun MarkdownView(
    text: String,
    modifier: Modifier = Modifier,
) {
    Markdown(
        content = text,
        modifier = modifier,
        colors = MarkdownDefaults.colors(),
        typography = MarkdownDefaults.typography(),
        components = MarkdownDefaults.components(),
    )
}
```

- [ ] **Step 2: 编译验证**

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin 2>&1 | grep -v "^w:" | grep "error:" | head -10
```

预期：无编译错误。

---

## Task 9: 简化 StreamingMessage.kt — TextBlock 统一走 MarkdownView

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt`

- [ ] **Step 1: 简化 TextBlock 渲染分支**

在 `AssistantMessageBlocks` 的 `when (block)` 中，找到 `is ContentBlock.TextBlock ->` 分支，将其从：

```kotlin
is ContentBlock.TextBlock -> {
    if (block.done && block.renderedMarkdown != null) {
        MarkdownView(
            markdown = block.renderedMarkdown,
            modifier = Modifier
                .fillMaxWidth()
                .alpha(alpha),
        )
    } else {
        // Streaming in progress OR parse pending — show plain text
        Text(
            text = block.text,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier
                .fillMaxWidth()
                .alpha(alpha),
        )
    }
}
```

替换为：

```kotlin
is ContentBlock.TextBlock -> MarkdownView(
    text = block.text,
    modifier = Modifier
        .fillMaxWidth()
        .alpha(alpha),
)
```

同时删除 `StreamingMessage.kt` 中不再使用的 import：
```kotlin
import androidx.compose.material3.Text
```
（如果 Text 在文件其他地方还在用则保留，比如 `UserMessageBubble` 里仍用 `Text`，请保留）

**注意**：`UserMessageBubble` 中的 `Text` 组件不受影响，不要动。

- [ ] **Step 2: 删除 MarkdownView 对 CharSequence 类型的 import（如果有残留）**

```bash
grep -n "CharSequence\|renderedMarkdown" \
  ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt
```

预期：无输出（这两个引用已不存在）。

- [ ] **Step 3: 全量编译 + 测试**

```bash
cd ui/mobile-android
./gradlew :app:assembleDebug 2>&1 | tail -5
./gradlew :app:testDebugUnitTest 2>&1 | tail -10
```

预期：
```
BUILD SUCCESSFUL
...
BUILD SUCCESSFUL
```

- [ ] **Step 4: 提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt \
        app/src/main/java/com/sebastian/android/ui/common/MarkdownDefaults.kt \
        app/src/main/java/com/sebastian/android/ui/common/CodeBlockView.kt \
        app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt
git commit -m "feat(android): 替换 Markdown 渲染引擎为 multiplatform-markdown-renderer

- MarkdownView 重写为纯 Compose，消除 AndroidView 包装
- MarkdownDefaults 集中管理颜色/排版/组件配置
- CodeBlockView 深色背景 + 复制按钮代码块
- StreamingMessage 流式和历史加载统一走 MarkdownView

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 手动验证清单

完成所有 Task 后，在模拟器上做以下检查：

- [ ] 切换到一个有历史消息的会话，确认 Markdown（标题/列表/粗体）正确渲染
- [ ] 发送新消息，确认流式输出全程有 Markdown 格式，无纯文本→格式文本跳变
- [ ] 发送包含代码块的消息，确认深色背景渲染，复制按钮可用（图标切换为 ✓，1.5s 恢复）
- [ ] 在代码块内横向滑动，确认代码块内容先滚动；到达边界后抬起手指重新滑可触发面板切换
- [ ] 切换 Light/Dark 主题，确认正文样式跟随，代码块背景保持 `#1E1E1E`
- [ ] 打开 20+ 条消息的会话，上下滚动，确认无明显卡顿

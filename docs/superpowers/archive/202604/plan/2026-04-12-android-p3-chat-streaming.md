# Android Phase 1 — Plan 3: Chat & Streaming

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现完整的聊天主界面：`ChatViewModel` 收 SSE 事件驱动状态机、消息列表（流式 TextBlock / ThinkingCard / ToolCallCard）、块级增量 Markdown 渲染、逐块淡入动画、滚动跟随逻辑、Agent 状态动画（idle/thinking/streaming/working）、ApprovalDialog，以及升级 `ChatScreen` 为完整三面板。

**Architecture:** `ChatViewModel` 在 `viewModelScope(IO)` 中收集 SSE `Flow<StreamEvent>`，通过分发表更新 `StateFlow<ChatUiState>`。Compose Main Thread 只做 `collectAsState()` → recomposition。已完成的 `TextBlock`（`done=true`）在 IO 协程经 Markwon 解析为 `Spanned`，通过 `AndroidView { TextView }` 渲染；流式中的 `TextBlock`（`done=false`）直接 `Text()` 输出纯文本。新增 delta 以 `Animatable(0f→1f)` 淡入 200ms。

**Tech Stack:** Markwon 4.6, Compose `AndroidView`, `Animatable`, `InfiniteTransition`, `LazyListState`

**依赖：** Plan 1 + Plan 2 完成（ChatRepository, SettingsRepository, NavController 可用）

---

## 文件结构

```
app/src/main/java/com/sebastian/android/
├── ui/
│   ├── chat/
│   │   ├── ChatScreen.kt                     # 升级为完整三面板（替换 Plan 2 版本）
│   │   ├── SessionPanel.kt                   # 充实会话列表（替换 Plan 2 骨架）
│   │   ├── MessageList.kt                    # LazyColumn 消息列表 + 滚动跟随
│   │   ├── StreamingMessage.kt               # 单条 assistant 消息（blocks 渲染）
│   │   ├── ThinkingCard.kt                   # 思考过程折叠卡片
│   │   └── ToolCallCard.kt                   # 工具调用卡片
│   └── common/
│       ├── AnimationTokens.kt                # 统一动画参数常量
│       ├── ApprovalDialog.kt                 # 审批弹窗
│       └── MarkdownView.kt                   # Markwon AndroidView 封装
├── viewmodel/
│   ├── ChatViewModel.kt
│   └── SessionViewModel.kt
app/src/test/java/com/sebastian/android/
└── viewmodel/
    └── ChatViewModelTest.kt
```

---

### Task 1: AnimationTokens

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/common/AnimationTokens.kt`

- [ ] **Step 1: 创建 `AnimationTokens.kt`**

```kotlin
// com/sebastian/android/ui/common/AnimationTokens.kt
package com.sebastian.android.ui.common

import androidx.compose.animation.core.FastOutSlowInEasing

object AnimationTokens {
    // Thinking：慢呼吸光晕
    const val THINKING_PULSE_DURATION_MS = 2000
    const val THINKING_PULSE_MIN_ALPHA = 0.4f
    const val THINKING_PULSE_MAX_ALPHA = 1.0f
    val THINKING_PULSE_EASING = FastOutSlowInEasing

    // Streaming：新 chunk 淡入
    const val STREAMING_CHUNK_FADE_IN_MS = 200

    // Working（工具调用进行中）：脉冲
    const val WORKING_PULSE_DURATION_MS = 1200

    // 状态切换 crossfade
    const val STATE_TRANSITION_DURATION_MS = 300
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/common/AnimationTokens.kt
git commit -m "feat(android): AnimationTokens 统一动画参数"
```

---

### Task 2: MarkdownView（Markwon AndroidView 封装）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt`

- [ ] **Step 1: 创建 `MarkdownView.kt`**

```kotlin
// com/sebastian/android/ui/common/MarkdownView.kt
package com.sebastian.android.ui.common

import android.widget.TextView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.material3.MaterialTheme
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin

/**
 * 已完成的 TextBlock 渲染：Markwon 在调用前已在 IO 线程解析为 CharSequence，
 * 此组件仅在 Main Thread 调用 TextView.text = spanned。
 *
 * 流式进行中的 TextBlock 使用 Compose Text() 直接渲染纯文本（见 StreamingMessage.kt）。
 */
@Composable
fun MarkdownView(
    markdown: String,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val textColor = MaterialTheme.colorScheme.onSurface.toArgb()

    val markwon = remember(context) {
        Markwon.builder(context)
            .usePlugin(StrikethroughPlugin.create())
            .usePlugin(TablePlugin.create(context))
            .build()
    }

    AndroidView(
        factory = { ctx ->
            TextView(ctx).apply {
                setTextColor(textColor)
                textSize = 16f
                lineSpacingMultiplier = 1.4f
            }
        },
        update = { textView ->
            textView.setTextColor(textColor)
            markwon.setMarkdown(textView, markdown)
        },
        modifier = modifier,
    )
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/common/MarkdownView.kt
git commit -m "feat(android): MarkdownView（Markwon + AndroidView，IO 线程解析）"
```

---

### Task 3: ChatViewModel（TDD）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Create: `app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: 写 ChatViewModel 的失败测试**

```kotlin
// app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {

    private lateinit var chatRepository: ChatRepository
    private lateinit var settingsRepository: SettingsRepository
    private lateinit var viewModel: ChatViewModel
    private val dispatcher = StandardTestDispatcher()
    private val sseFlow = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)
    private val serverUrlFlow = MutableStateFlow("http://test.local:8823")

    @Before
    fun setup() {
        chatRepository = mock()
        settingsRepository = mock()
        whenever(settingsRepository.serverUrl).thenReturn(serverUrlFlow)
        whenever(chatRepository.sessionStream(any(), any(), any())).thenReturn(sseFlow)
        whenever(chatRepository.globalStream(any(), any())).thenReturn(flowOf())
        viewModel = ChatViewModel(chatRepository, settingsRepository, dispatcher)
    }

    @Test
    fun `initial state is IDLE_EMPTY`() = runTest(dispatcher) {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(ComposerState.IDLE_EMPTY, state.composerState)
            assertTrue(state.messages.isEmpty())
        }
    }

    @Test
    fun `text_block_start creates new streaming TextBlock`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial

            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            val assistantMsg = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
            assertFalse(assistantMsg == null)
            val block = assistantMsg!!.blocks.find { it.blockId == "b0_0" }
            assertTrue(block is ContentBlock.TextBlock)
            assertFalse((block as ContentBlock.TextBlock).done)
        }
    }

    @Test
    fun `text_delta appends to TextBlock`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "好的"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "，我来帮你"))
            dispatcher.scheduler.advanceUntilIdle()

            // 消费直到包含文本的状态
            var found = false
            while (!found) {
                val state = awaitItem()
                val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                    ?.blocks?.find { it.blockId == "b0_0" }
                if (block is ContentBlock.TextBlock && block.text.contains("我来帮你")) {
                    found = true
                    assertEquals("好的，我来帮你", block.text)
                }
            }
        }
    }

    @Test
    fun `text_block_stop marks block as done`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "完成"))
            sseFlow.emit(StreamEvent.TextBlockStop("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            var found = false
            while (!found) {
                val state = awaitItem()
                val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                    ?.blocks?.find { it.blockId == "b0_0" }
                if (block is ContentBlock.TextBlock && block.done) {
                    found = true
                }
            }
            assertTrue(found)
        }
    }

    @Test
    fun `thinking_block_start creates ThinkingBlock`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.ThinkingBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                ?.blocks?.find { it.blockId == "b0_0" }
            assertTrue(block is ContentBlock.ThinkingBlock)
        }
    }

    @Test
    fun `composerState becomes STREAMING during text block`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            assertEquals(ComposerState.STREAMING, state.composerState)
        }
    }

    @Test
    fun `composerState returns to IDLE_EMPTY after turn_response`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextBlockStop("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TurnResponse("s1", "完成"))
            dispatcher.scheduler.advanceUntilIdle()

            var found = false
            while (!found) {
                val state = awaitItem()
                if (state.composerState == ComposerState.IDLE_EMPTY) found = true
            }
            assertTrue(found)
        }
    }

    @Test
    fun `approval_requested creates pending approval`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.ApprovalRequested("s1", "ap_1", "删除文件 foo.txt"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            assertEquals(1, state.pendingApprovals.size)
            assertEquals("ap_1", state.pendingApprovals[0].approvalId)
        }
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "*.ChatViewModelTest"
```

预期：FAILED — `ChatViewModel`、`ComposerState` 未定义。

- [ ] **Step 3: 创建 `ChatViewModel.kt`**

```kotlin
// com/sebastian/android/viewmodel/ChatViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID
import javax.inject.Inject

enum class ComposerState { IDLE_EMPTY, IDLE_READY, SENDING, STREAMING, CANCELLING }
enum class ScrollFollowState { FOLLOWING, DETACHED, NEAR_BOTTOM }
enum class AgentAnimState { IDLE, THINKING, STREAMING, WORKING }

data class PendingApproval(
    val approvalId: String,
    val sessionId: String,
    val description: String,
)

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeThinkingEffort: ThinkingEffort = ThinkingEffort.AUTO,
    val isOffline: Boolean = false,
    val pendingApprovals: List<PendingApproval> = emptyList(),
    val error: String? = null,
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val settingsRepository: SettingsRepository,
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    // 当前正在构建的 assistant 消息 ID
    private var currentAssistantMessageId: String? = null

    init {
        startSseCollection()
    }

    private fun startSseCollection() {
        viewModelScope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isBlank()) return@launch
            // Sebastian 主会话用全局流，sessionId = "main"
            chatRepository.sessionStream(baseUrl, "main")
                .collect { event -> handleEvent(event) }
        }
    }

    private fun handleEvent(event: StreamEvent) {
        when (event) {
            is StreamEvent.TurnReceived -> {
                val msgId = UUID.randomUUID().toString()
                currentAssistantMessageId = msgId
                _uiState.update { state ->
                    state.copy(
                        composerState = ComposerState.SENDING,
                        messages = state.messages + Message(
                            id = msgId,
                            sessionId = "main",
                            role = MessageRole.ASSISTANT,
                        ),
                    )
                }
            }

            is StreamEvent.ThinkingBlockStart -> {
                updateAssistantBlocks { blocks ->
                    blocks + ContentBlock.ThinkingBlock(blockId = event.blockId, text = "", done = false)
                }
                _uiState.update { it.copy(agentAnimState = AgentAnimState.THINKING) }
            }

            is StreamEvent.ThinkingDelta -> {
                updateBlock(event.blockId) { block ->
                    if (block is ContentBlock.ThinkingBlock) block.copy(text = block.text + event.delta) else block
                }
            }

            is StreamEvent.ThinkingBlockStop -> {
                updateBlock(event.blockId) { block ->
                    if (block is ContentBlock.ThinkingBlock) block.copy(done = true) else block
                }
            }

            is StreamEvent.TextBlockStart -> {
                updateAssistantBlocks { blocks ->
                    blocks + ContentBlock.TextBlock(blockId = event.blockId, text = "", done = false)
                }
                _uiState.update { it.copy(composerState = ComposerState.STREAMING, agentAnimState = AgentAnimState.STREAMING) }
            }

            is StreamEvent.TextDelta -> {
                updateBlock(event.blockId) { block ->
                    if (block is ContentBlock.TextBlock) block.copy(text = block.text + event.delta) else block
                }
            }

            is StreamEvent.TextBlockStop -> {
                updateBlock(event.blockId) { block ->
                    if (block is ContentBlock.TextBlock) block.copy(done = true) else block
                }
            }

            is StreamEvent.ToolBlockStart -> {
                updateAssistantBlocks { blocks ->
                    blocks + ContentBlock.ToolBlock(
                        blockId = event.blockId,
                        toolId = event.toolId,
                        name = event.name,
                        inputs = "",
                        status = ToolStatus.PENDING,
                    )
                }
            }

            is StreamEvent.ToolBlockStop -> {
                updateBlock(event.blockId) { block ->
                    if (block is ContentBlock.ToolBlock) block.copy(inputs = event.inputs) else block
                }
            }

            is StreamEvent.ToolRunning -> {
                updateBlockByToolId(event.toolId) { block ->
                    if (block is ContentBlock.ToolBlock) block.copy(status = ToolStatus.RUNNING) else block
                }
                _uiState.update { it.copy(agentAnimState = AgentAnimState.WORKING) }
            }

            is StreamEvent.ToolExecuted -> {
                updateBlockByToolId(event.toolId) { block ->
                    if (block is ContentBlock.ToolBlock) block.copy(status = ToolStatus.DONE, resultSummary = event.resultSummary) else block
                }
            }

            is StreamEvent.ToolFailed -> {
                updateBlockByToolId(event.toolId) { block ->
                    if (block is ContentBlock.ToolBlock) block.copy(status = ToolStatus.FAILED, error = event.error) else block
                }
            }

            is StreamEvent.TurnResponse -> {
                currentAssistantMessageId = null
                _uiState.update {
                    it.copy(
                        composerState = ComposerState.IDLE_EMPTY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
                }
            }

            is StreamEvent.TurnInterrupted -> {
                _uiState.update {
                    it.copy(
                        composerState = ComposerState.IDLE_EMPTY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
                }
            }

            is StreamEvent.ApprovalRequested -> {
                _uiState.update { state ->
                    state.copy(
                        pendingApprovals = state.pendingApprovals + PendingApproval(
                            approvalId = event.approvalId,
                            sessionId = event.sessionId,
                            description = event.description,
                        )
                    )
                }
            }

            is StreamEvent.ApprovalGranted, is StreamEvent.ApprovalDenied -> {
                val id = if (event is StreamEvent.ApprovalGranted) event.approvalId else (event as StreamEvent.ApprovalDenied).approvalId
                _uiState.update { state ->
                    state.copy(pendingApprovals = state.pendingApprovals.filter { it.approvalId != id })
                }
            }

            else -> { /* task events, unknown: ignore */ }
        }
    }

    // ---- 发送 / 取消 ----

    fun sendMessage(text: String) {
        if (text.isBlank()) return
        val userMsg = Message(
            id = UUID.randomUUID().toString(),
            sessionId = "main",
            role = MessageRole.USER,
            text = text,
        )
        _uiState.update { state ->
            state.copy(
                messages = state.messages + userMsg,
                composerState = ComposerState.SENDING,
                scrollFollowState = ScrollFollowState.FOLLOWING,
            )
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.sendTurn(text, _uiState.value.activeThinkingEffort)
                .onFailure { e ->
                    _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                }
        }
    }

    fun cancelTurn() {
        _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
        // 后端无专用 cancel endpoint，停止 SSE 即可（ViewModel scope 取消后 SSE 自动断）
        // Plan 4 中通过重启 SSE 连接实现
    }

    fun setEffort(effort: ThinkingEffort) {
        _uiState.update { it.copy(activeThinkingEffort = effort) }
    }

    fun grantApproval(approvalId: String) {
        viewModelScope.launch(dispatcher) {
            chatRepository.grantApproval(approvalId)
        }
    }

    fun denyApproval(approvalId: String) {
        viewModelScope.launch(dispatcher) {
            chatRepository.denyApproval(approvalId)
        }
    }

    fun onUserScrolled() {
        _uiState.update { it.copy(scrollFollowState = ScrollFollowState.DETACHED) }
    }

    fun onScrolledNearBottom() {
        _uiState.update { it.copy(scrollFollowState = ScrollFollowState.NEAR_BOTTOM) }
    }

    fun onScrolledToBottom() {
        _uiState.update { it.copy(scrollFollowState = ScrollFollowState.FOLLOWING) }
    }

    fun toggleThinkingBlock(blockId: String) {
        updateBlock(blockId) { block ->
            if (block is ContentBlock.ThinkingBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun toggleToolBlock(blockId: String) {
        updateBlock(blockId) { block ->
            if (block is ContentBlock.ToolBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }

    // ---- 内部工具方法 ----

    private fun updateAssistantBlocks(transform: (List<ContentBlock>) -> List<ContentBlock>) {
        val msgId = currentAssistantMessageId ?: return
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    if (msg.id == msgId) msg.copy(blocks = transform(msg.blocks)) else msg
                }
            )
        }
    }

    private fun updateBlock(blockId: String, transform: (ContentBlock) -> ContentBlock) {
        val msgId = currentAssistantMessageId ?: return
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    if (msg.id == msgId) {
                        msg.copy(blocks = msg.blocks.map { block ->
                            if (block.blockId == blockId) transform(block) else block
                        })
                    } else msg
                }
            )
        }
    }

    private fun updateBlockByToolId(toolId: String, transform: (ContentBlock) -> ContentBlock) {
        val msgId = currentAssistantMessageId ?: return
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    if (msg.id == msgId) {
                        msg.copy(blocks = msg.blocks.map { block ->
                            if (block is ContentBlock.ToolBlock && block.toolId == toolId) transform(block) else block
                        })
                    } else msg
                }
            )
        }
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "*.ChatViewModelTest"
```

预期：7 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android): ChatViewModel SSE 事件驱动状态机 + 单元测试（TDD）"
```

---

### Task 4: ApprovalDialog

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/common/ApprovalDialog.kt`

- [ ] **Step 1: 创建 `ApprovalDialog.kt`**

```kotlin
// com/sebastian/android/ui/common/ApprovalDialog.kt
package com.sebastian.android.ui.common

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.sebastian.android.viewmodel.PendingApproval

@Composable
fun ApprovalDialog(
    approval: PendingApproval,
    onGrant: (String) -> Unit,
    onDeny: (String) -> Unit,
) {
    AlertDialog(
        onDismissRequest = { /* 不允许点击外部关闭，必须明确操作 */ },
        title = { Text("Sebastian 请求授权") },
        text = { Text(approval.description) },
        confirmButton = {
            Button(onClick = { onGrant(approval.approvalId) }) {
                Text("允许")
            }
        },
        dismissButton = {
            OutlinedButton(
                onClick = { onDeny(approval.approvalId) },
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.error,
                ),
            ) {
                Text("拒绝")
            }
        },
    )
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/common/ApprovalDialog.kt
git commit -m "feat(android): ApprovalDialog 审批弹窗"
```

---

### Task 5: ThinkingCard

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/ThinkingCard.kt`

- [ ] **Step 1: 创建 `ThinkingCard.kt`**

```kotlin
// com/sebastian/android/ui/chat/ThinkingCard.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.ui.common.AnimationTokens

@Composable
fun ThinkingCard(
    block: ContentBlock.ThinkingBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // 思考进行中：图标呼吸动画
    val infiniteTransition = rememberInfiniteTransition(label = "thinking_pulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = AnimationTokens.THINKING_PULSE_MIN_ALPHA,
        targetValue = AnimationTokens.THINKING_PULSE_MAX_ALPHA,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = AnimationTokens.THINKING_PULSE_DURATION_MS,
                easing = AnimationTokens.THINKING_PULSE_EASING,
            ),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "thinking_alpha",
    )

    Card(
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column {
            // Header（始终可见，点击折叠/展开）
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onToggle)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Default.Psychology,
                    contentDescription = "思考",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = if (!block.done) Modifier.alpha(pulseAlpha) else Modifier,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = if (block.done) "思考过程" else "思考中…",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.weight(1f),
                )
                Icon(
                    imageVector = if (block.expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    contentDescription = if (block.expanded) "折叠" else "展开",
                )
            }

            // Body（展开时显示）
            AnimatedVisibility(
                visible = block.expanded,
                enter = expandVertically(),
                exit = shrinkVertically(),
            ) {
                Text(
                    text = block.text,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                )
            }
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/ThinkingCard.kt
git commit -m "feat(android): ThinkingCard 思考过程折叠卡片（呼吸动画 + 展开）"
```

---

### Task 6: ToolCallCard

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/ToolCallCard.kt`

- [ ] **Step 1: 创建 `ToolCallCard.kt`**

```kotlin
// com/sebastian/android/ui/chat/ToolCallCard.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.ui.common.AnimationTokens

@Composable
fun ToolCallCard(
    block: ContentBlock.ToolBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "tool_pulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.5f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = AnimationTokens.WORKING_PULSE_DURATION_MS),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "tool_alpha",
    )

    Card(
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        ),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onToggle)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 状态图标
                when (block.status) {
                    ToolStatus.PENDING, ToolStatus.RUNNING -> CircularProgressIndicator(
                        modifier = Modifier
                            .size(20.dp)
                            .alpha(if (block.status == ToolStatus.RUNNING) pulseAlpha else 1f),
                        strokeWidth = 2.dp,
                    )
                    ToolStatus.DONE -> Icon(
                        Icons.Default.Check,
                        contentDescription = "完成",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(20.dp),
                    )
                    ToolStatus.FAILED -> Icon(
                        Icons.Default.Close,
                        contentDescription = "失败",
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(20.dp),
                    )
                }

                Spacer(Modifier.width(8.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = block.name,
                        style = MaterialTheme.typography.labelLarge,
                    )
                    block.resultSummary?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    block.error?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }

                Icon(
                    imageVector = if (block.expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    contentDescription = null,
                )
            }

            AnimatedVisibility(
                visible = block.expanded,
                enter = expandVertically(),
                exit = shrinkVertically(),
            ) {
                Text(
                    text = "输入：${block.inputs}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                )
            }
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/ToolCallCard.kt
git commit -m "feat(android): ToolCallCard 工具调用卡片（进度 + 折叠）"
```

---

### Task 7: StreamingMessage（ContentBlock 渲染 + 淡入动画）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt`

- [ ] **Step 1: 创建 `StreamingMessage.kt`**

```kotlin
// com/sebastian/android/ui/chat/StreamingMessage.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.ui.common.AnimationTokens
import com.sebastian.android.ui.common.MarkdownView

/**
 * 渲染单条消息（user 或 assistant）。
 * 每个 ContentBlock 独立渲染，新增 block 触发 Animatable 淡入。
 */
@Composable
fun MessageBubble(
    message: Message,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val isUser = message.role == MessageRole.USER

    if (isUser) {
        UserMessageBubble(text = message.text, modifier = modifier)
    } else {
        AssistantMessageBlocks(
            blocks = message.blocks,
            onToggleThinking = onToggleThinking,
            onToggleTool = onToggleTool,
            modifier = modifier,
        )
    }
}

@Composable
private fun UserMessageBubble(text: String, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 48.dp, end = 16.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier
                .background(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    shape = RoundedCornerShape(16.dp, 4.dp, 16.dp, 16.dp),
                )
                .padding(horizontal = 12.dp, vertical = 8.dp),
        )
    }
}

@Composable
private fun AssistantMessageBlocks(
    blocks: List<ContentBlock>,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    // 跟踪已渲染 blockId，新 block 触发淡入
    val knownIds = remember { mutableStateListOf<String>() }
    val alphaMap = remember { mutableMapOf<String, Animatable<Float, *>>() }

    LaunchedEffect(blocks.size) {
        val newBlocks = blocks.filter { it.blockId !in knownIds }
        for (block in newBlocks) {
            knownIds.add(block.blockId)
            val anim = Animatable(0f)
            alphaMap[block.blockId] = anim
            anim.animateTo(
                targetValue = 1f,
                animationSpec = androidx.compose.animation.core.tween(
                    durationMillis = AnimationTokens.STREAMING_CHUNK_FADE_IN_MS,
                )
            )
        }
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
    ) {
        blocks.forEach { block ->
            val alpha = alphaMap[block.blockId]?.value ?: 1f
            when (block) {
                is ContentBlock.ThinkingBlock -> ThinkingCard(
                    block = block,
                    onToggle = { onToggleThinking(block.blockId) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .alpha(alpha),
                )

                is ContentBlock.ToolBlock -> ToolCallCard(
                    block = block,
                    onToggle = { onToggleTool(block.blockId) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .alpha(alpha),
                )

                is ContentBlock.TextBlock -> {
                    if (block.done) {
                        // 已完成：Markwon 渲染
                        MarkdownView(
                            markdown = block.text,
                            modifier = Modifier
                                .fillMaxWidth()
                                .alpha(alpha),
                        )
                    } else {
                        // 流式进行中：纯文本 + 光标
                        Text(
                            text = block.text + "▍",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier
                                .fillMaxWidth()
                                .alpha(alpha),
                        )
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt
git commit -m "feat(android): StreamingMessage 块级渲染 + Animatable 淡入动画"
```

---

### Task 8: MessageList（LazyColumn + 滚动跟随）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt`

- [ ] **Step 1: 创建 `MessageList.kt`**

```kotlin
// com/sebastian/android/ui/chat/MessageList.kt
package com.sebastian.android.ui.chat

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Message
import com.sebastian.android.viewmodel.ScrollFollowState

@Composable
fun MessageList(
    messages: List<Message>,
    scrollFollowState: ScrollFollowState,
    onUserScrolled: () -> Unit,
    onScrolledNearBottom: () -> Unit,
    onScrolledToBottom: () -> Unit,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()

    // 检测用户拖动（开始拖动 → DETACHED）
    val isScrollInProgress by remember { derivedStateOf { listState.isScrollInProgress } }

    // 检测是否接近底部（距底 < 200dp）
    val isNearBottom by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val lastVisibleItem = info.visibleItemsInfo.lastOrNull() ?: return@derivedStateOf true
            val totalItems = info.totalItemsCount
            lastVisibleItem.index >= totalItems - 2
        }
    }

    LaunchedEffect(isScrollInProgress) {
        if (isScrollInProgress && scrollFollowState == ScrollFollowState.FOLLOWING) {
            onUserScrolled()
        }
    }

    LaunchedEffect(isNearBottom) {
        if (isNearBottom) {
            onScrolledToBottom()
        } else if (scrollFollowState == ScrollFollowState.NEAR_BOTTOM) {
            onScrolledNearBottom()
        }
    }

    // 流式到达时自动滚到底
    LaunchedEffect(messages.size, messages.lastOrNull()?.blocks?.size) {
        if (scrollFollowState == ScrollFollowState.FOLLOWING && messages.isNotEmpty()) {
            listState.scrollToItem(messages.size - 1)
        }
    }

    LazyColumn(
        state = listState,
        modifier = modifier,
    ) {
        item { Spacer(Modifier.height(16.dp)) }
        items(messages, key = { it.id }) { message ->
            MessageBubble(
                message = message,
                onToggleThinking = onToggleThinking,
                onToggleTool = onToggleTool,
                modifier = Modifier.padding(vertical = 4.dp),
            )
        }
        item { Spacer(Modifier.height(8.dp)) }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt
git commit -m "feat(android): MessageList（LazyColumn + 滚动跟随逻辑）"
```

---

### Task 9: SessionPanel（充实内容）

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt`
- Create: `app/src/main/java/com/sebastian/android/viewmodel/SessionViewModel.kt`

- [ ] **Step 1: 创建 `SessionViewModel.kt`**

```kotlin
// com/sebastian/android/viewmodel/SessionViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Session
import com.sebastian.android.data.repository.SessionRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SessionUiState(
    val sessions: List<Session> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SessionViewModel @Inject constructor(
    private val repository: SessionRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SessionUiState())
    val uiState: StateFlow<SessionUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            repository.sessionsFlow().collect { sessions ->
                _uiState.update { it.copy(sessions = sessions) }
            }
        }
        loadSessions()
    }

    fun loadSessions() {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isLoading = true) }
            repository.loadSessions()
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
                .onSuccess { _uiState.update { it.copy(isLoading = false) } }
        }
    }

    fun createSession() {
        viewModelScope.launch(Dispatchers.IO) {
            repository.createSession()
        }
    }
}
```

- [ ] **Step 2: 替换 `SessionPanel.kt`**

```kotlin
// com/sebastian/android/ui/chat/SessionPanel.kt
package com.sebastian.android.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Divider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Session

@Composable
fun SessionPanel(
    sessions: List<Session>,
    activeSessionId: String?,
    onSessionClick: (Session) -> Unit,
    onNewSession: () -> Unit,
    onNavigateToSettings: () -> Unit,
    onNavigateToSubAgents: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize()) {
        // 顶部操作栏
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "会话",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f).padding(start = 8.dp),
            )
            IconButton(onClick = onNewSession) {
                Icon(Icons.Default.Add, contentDescription = "新建会话")
            }
        }
        Divider()

        // 会话列表
        LazyColumn(modifier = Modifier.weight(1f)) {
            items(sessions, key = { it.id }) { session ->
                ListItem(
                    headlineContent = {
                        Text(
                            text = session.title,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSessionClick(session) },
                    colors = if (session.id == activeSessionId) {
                        androidx.compose.material3.ListItemDefaults.colors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        )
                    } else androidx.compose.material3.ListItemDefaults.colors(),
                )
            }
        }

        Divider()

        // 底部导航入口
        TextButton(
            onClick = onNavigateToSubAgents,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
        ) {
            Icon(Icons.Default.Person, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Sub-Agents", modifier = Modifier.weight(1f))
        }
        TextButton(
            onClick = onNavigateToSettings,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
        ) {
            Icon(Icons.Default.Settings, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("设置", modifier = Modifier.weight(1f))
        }
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/sebastian/android/viewmodel/SessionViewModel.kt \
        app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt
git commit -m "feat(android): SessionPanel 充实会话列表 + SessionViewModel"
```

---

### Task 10: 升级 ChatScreen（完整三面板 + 接线 ChatViewModel）

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 1: 替换 `ChatScreen.kt`**

```kotlin
// com/sebastian/android/ui/chat/ChatScreen.kt
package com.sebastian.android.ui.chat

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi
import androidx.compose.material3.adaptive.layout.AnimatedPane
import androidx.compose.material3.adaptive.layout.ListDetailPaneScaffold
import androidx.compose.material3.adaptive.layout.ListDetailPaneScaffoldRole
import androidx.compose.material3.adaptive.navigation.rememberListDetailPaneScaffoldNavigator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.common.ApprovalDialog
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.ChatViewModel
import com.sebastian.android.viewmodel.SessionViewModel
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3AdaptiveApi::class, ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    navController: NavController,
    chatViewModel: ChatViewModel = hiltViewModel(),
    sessionViewModel: SessionViewModel = hiltViewModel(),
) {
    val chatState by chatViewModel.uiState.collectAsState()
    val sessionState by sessionViewModel.uiState.collectAsState()
    val navigator = rememberListDetailPaneScaffoldNavigator<Nothing>()
    val scope = rememberCoroutineScope()

    // Approval Dialog（出现时阻断其他交互）
    chatState.pendingApprovals.firstOrNull()?.let { approval ->
        ApprovalDialog(
            approval = approval,
            onGrant = chatViewModel::grantApproval,
            onDeny = chatViewModel::denyApproval,
        )
    }

    ListDetailPaneScaffold(
        directive = navigator.scaffoldDirective,
        value = navigator.scaffoldValue,
        listPane = {
            AnimatedPane {
                SessionPanel(
                    sessions = sessionState.sessions,
                    activeSessionId = null,
                    onSessionClick = {},
                    onNewSession = sessionViewModel::createSession,
                    onNavigateToSettings = { navController.navigate(Route.Settings) },
                    onNavigateToSubAgents = { navController.navigate(Route.SubAgents) },
                )
            }
        },
        detailPane = {
            AnimatedPane {
                Scaffold(
                    topBar = {
                        TopAppBar(
                            title = { Text("Sebastian") },
                            navigationIcon = {
                                IconButton(onClick = {
                                    scope.launch {
                                        navigator.navigateTo(ListDetailPaneScaffoldRole.List)
                                    }
                                }) {
                                    Icon(Icons.Default.Menu, contentDescription = "会话列表")
                                }
                            },
                        )
                    },
                ) { innerPadding ->
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(innerPadding)
                            .imePadding(),
                    ) {
                        MessageList(
                            messages = chatState.messages,
                            scrollFollowState = chatState.scrollFollowState,
                            onUserScrolled = chatViewModel::onUserScrolled,
                            onScrolledNearBottom = chatViewModel::onScrolledNearBottom,
                            onScrolledToBottom = chatViewModel::onScrolledToBottom,
                            onToggleThinking = chatViewModel::toggleThinkingBlock,
                            onToggleTool = chatViewModel::toggleToolBlock,
                            modifier = Modifier.weight(1f),
                        )
                        // Composer 占位（Plan 4 填充）
                        Box(modifier = Modifier) {
                            Text("Composer TODO")
                        }
                    }
                }
            }
        },
    )
}
```

- [ ] **Step 2: 完整构建**

```bash
./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL。

- [ ] **Step 3: 运行全部单元测试**

```bash
./gradlew :app:testDebugUnitTest
```

预期：`SseFrameParserTest`(5) + `SettingsViewModelTest`(4) + `ChatViewModelTest`(7) = **16 个测试**全部 PASS。

- [ ] **Step 4: 在模拟器上验证流式消息渲染**

1. 启动 App，配置 Server URL（Settings → Connection）
2. 发送消息（Plan 4 的 Composer 完成前，可用调试工具 `adb shell` 触发 SSE 事件）
3. 验证：ThinkingCard 显示呼吸动画，TextBlock 逐字追加，完成后切换 Markwon 渲染

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "feat(android): 升级 ChatScreen 接入 ChatViewModel + 完整消息渲染链路"
```

---

**Plan 3 完成检查：**
- [ ] 所有单元测试通过（16 个）
- [ ] 流式 SSE 事件正确驱动 ChatUiState（通过测试验证）
- [ ] ThinkingCard 点击可展开/折叠
- [ ] ToolCallCard 显示状态（RUNNING 时转圈，DONE 时绿勾）
- [ ] MessageList 滚动跟随（FOLLOWING → DETACHED → FOLLOWING）
- [ ] ApprovalDialog 弹出时覆盖全屏

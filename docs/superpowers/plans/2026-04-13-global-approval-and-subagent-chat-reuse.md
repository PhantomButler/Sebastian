# 全局审批系统 + SubAgent 对话页复用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将审批弹窗从页面级提升到 App 全局级（任何页面可弹出），同时将 SubAgent 对话页合并到主 ChatScreen（参数化复用三面板布局）。

**Architecture:** App 根级新增 `GlobalApprovalViewModel` 连接全局 SSE，`GlobalApprovalBanner` 悬浮在 NavHost 之上。ChatScreen 通过 `agentId` 参数区分主对话/SubAgent 模式，SessionPanel 按模式切换完整/精简布局。后端 approval 事件补充 `agent_type` 字段。

**Tech Stack:** Kotlin, Jetpack Compose, Hilt, OkHttp SSE, Python/FastAPI (backend)

**Spec:** `docs/superpowers/specs/2026-04-13-global-approval-and-subagent-chat-reuse-design.md`

---

## File Structure

| 操作 | 文件路径 | 职责 |
|------|---------|------|
| 修改 | `sebastian/orchestrator/conversation.py` | approval 事件改用 `APPROVAL_*` 类型 + 补充 `agent_type` |
| 修改 | `sebastian/permissions/gate.py` | 传递 `agent_type` 给 `request_approval` |
| 修改 | `ui/mobile-android/.../data/model/StreamEvent.kt` | `ApprovalRequested` 新增 `agentType` 字段 |
| 修改 | `ui/mobile-android/.../data/remote/dto/SseFrameDto.kt` | 解析 `agent_type` 字段 |
| 修改 | `ui/mobile-android/.../data/repository/ChatRepository.kt` | 接口不变（已有 `grantApproval`/`denyApproval`） |
| 新增 | `ui/mobile-android/.../viewmodel/GlobalApprovalViewModel.kt` | 全局 SSE + 审批队列管理 |
| 新增 | `ui/mobile-android/.../ui/common/GlobalApprovalBanner.kt` | 悬浮顶部审批 Banner |
| 修改 | `ui/mobile-android/.../viewmodel/ChatViewModel.kt` | 移除审批处理 + 新增 `sendAgentMessage` |
| 修改 | `ui/mobile-android/.../viewmodel/SessionViewModel.kt` | 新增 `loadAgentSessions` |
| 修改 | `ui/mobile-android/.../ui/navigation/Route.kt` | 新增 `AgentChat`，删除 `AgentSessions`/`SessionDetail` |
| 修改 | `ui/mobile-android/.../ui/chat/ChatScreen.kt` | 接收 `agentId`/`agentName` 参数化 |
| 修改 | `ui/mobile-android/.../ui/chat/SessionPanel.kt` | 精简模式支持 |
| 修改 | `ui/mobile-android/.../MainActivity.kt` | 路由表更新 + GlobalApprovalBanner 包裹 |
| 修改 | `ui/mobile-android/.../ui/subagents/AgentListScreen.kt` | 导航目标改为 `Route.AgentChat` |
| 删除 | `ui/mobile-android/.../ui/subagents/SessionListScreen.kt` | 不再需要 |
| 删除 | `ui/mobile-android/.../ui/subagents/SessionDetailScreen.kt` | 不再需要 |

以下简写 `ui/mobile-android/app/src/main/java/com/sebastian/android` 为 `$APP`。

---

### Task 1: 后端 — approval 事件补充 agent_type 并修正事件类型

**Files:**
- Modify: `sebastian/orchestrator/conversation.py:26-69`
- Modify: `sebastian/permissions/gate.py:193-200,254-261`

**重要发现：** 后端当前发出 `USER_APPROVAL_REQUESTED`（值 `"user.approval_requested"`），但 Android 客户端解析的是 `"approval.requested"`。两者不匹配，导致审批功能实际不工作。此 Task 同时修复此 bug。

- [ ] **Step 1: 修改 `conversation.py` — request_approval 方法**

在 `request_approval` 方法签名中新增 `agent_type` 参数，改用 `APPROVAL_*` 事件类型：

```python
# sebastian/orchestrator/conversation.py

async def request_approval(
    self,
    approval_id: str,
    task_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    reason: str,
    session_id: str = "",
    agent_type: str = "",      # 新增
) -> bool:
```

修改事件发布部分（约第57-69行），将 `EventType.USER_APPROVAL_REQUESTED` 改为 `EventType.APPROVAL_REQUESTED`，并在 data 中加入 `agent_type`：

```python
        await self._bus.publish(
            Event(
                type=EventType.APPROVAL_REQUESTED,
                data={
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "session_id": session_id,
                    "agent_type": agent_type,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "reason": reason,
                },
            )
        )
```

- [ ] **Step 2: 修改 `conversation.py` — resolve_approval 方法**

将 `resolve_approval` 中的事件类型从 `USER_APPROVAL_GRANTED`/`USER_APPROVAL_DENIED` 改为 `APPROVAL_GRANTED`/`APPROVAL_DENIED`（约第87行）：

```python
    async def resolve_approval(self, approval_id: str, granted: bool) -> None:
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            logger.warning(
                "resolve_approval called for unknown or already-done approval: %s", approval_id
            )
            return
        future.set_result(granted)
        event_type = EventType.APPROVAL_GRANTED if granted else EventType.APPROVAL_DENIED
        await self._bus.publish(
            Event(
                type=event_type,
                data={"approval_id": approval_id, "granted": granted},
            )
        )
```

- [ ] **Step 3: 修改 `gate.py` — 传递 agent_type**

在 `gate.py` 的两处 `request_approval` 调用中添加 `agent_type=context.agent_type`。

第一处（约第193行，`_check_path_in_workspace` 中）：

```python
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=inputs,
            reason=f"操作路径 '{resolved}' 在 workspace 外，需要用户确认。",
            session_id=context.session_id or "",
            agent_type=context.agent_type,
        )
```

第二处（约第254行，`_request_approval_and_call` 中）：

```python
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=inputs,
            reason=reason,
            session_id=context.session_id or "",
            agent_type=context.agent_type,
        )
```

- [ ] **Step 4: 验证后端改动**

Run: `cd /Users/ericw/work/code/ai/sebastian && python -c "from sebastian.orchestrator.conversation import ConversationManager; print('OK')"`
Expected: `OK`（无导入错误）

Run: `ruff check sebastian/orchestrator/conversation.py sebastian/permissions/gate.py`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add sebastian/orchestrator/conversation.py sebastian/permissions/gate.py
git commit -m "fix(backend): approval 事件改用 APPROVAL_* 类型并补充 agent_type

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Android — StreamEvent 和 SseFrameParser 支持 agentType

**Files:**
- Modify: `$APP/data/model/StreamEvent.kt:34`
- Modify: `$APP/data/remote/dto/SseFrameDto.kt:42`
- Modify: `$APP/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt:54-59`

- [ ] **Step 1: 修改 StreamEvent.ApprovalRequested**

在 `$APP/data/model/StreamEvent.kt` 第34行，给 `ApprovalRequested` 新增 `agentType` 字段：

```kotlin
    data class ApprovalRequested(val sessionId: String, val approvalId: String, val agentType: String, val description: String) : StreamEvent()
```

- [ ] **Step 2: 修改 SseFrameParser**

在 `$APP/data/remote/dto/SseFrameDto.kt` 第42行，解析 `agent_type` 字段：

```kotlin
        "approval.requested" -> StreamEvent.ApprovalRequested(data.getString("session_id"), data.getString("approval_id"), data.optString("agent_type", "sebastian"), data.optString("description", ""))
```

- [ ] **Step 3: 更新测试**

在 `$APP/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt`，替换 `parses approval_requested event` 测试：

```kotlin
    @Test
    fun `parses approval_requested event with agent_type`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_1","agent_type":"code_agent","description":"删除文件"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        val approval = event as StreamEvent.ApprovalRequested
        assertEquals("ap_1", approval.approvalId)
        assertEquals("code_agent", approval.agentType)
        assertEquals("删除文件", approval.description)
    }

    @Test
    fun `parses approval_requested event defaults agent_type to sebastian`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_2","description":"运行命令"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        assertEquals("sebastian", (event as StreamEvent.ApprovalRequested).agentType)
    }
```

- [ ] **Step 4: 运行测试**

Run: `cd ui/mobile-android && ./gradlew testDebugUnitTest --tests "com.sebastian.android.data.remote.SseFrameParserTest" --console=plain`
Expected: 所有测试 PASS

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt
git commit -m "feat(android): ApprovalRequested 新增 agentType 字段

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Android — GlobalApprovalViewModel

**Files:**
- Create: `$APP/viewmodel/GlobalApprovalViewModel.kt`

- [ ] **Step 1: 创建 GlobalApprovalViewModel**

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException
import javax.inject.Inject

data class GlobalApproval(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val description: String,
)

data class GlobalApprovalUiState(
    val approvals: List<GlobalApproval> = emptyList(),
)

@HiltViewModel
class GlobalApprovalViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val settingsRepository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(GlobalApprovalUiState())
    val uiState: StateFlow<GlobalApprovalUiState> = _uiState.asStateFlow()

    private var sseJob: Job? = null

    fun onAppStart() {
        if (sseJob?.isActive == true) return
        sseJob = viewModelScope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) return@launch
            try {
                chatRepository.globalStream(baseUrl).collect { event ->
                    handleEvent(event)
                }
            } catch (_: CancellationException) {
                throw CancellationException()
            } catch (_: Exception) {
                // Global SSE failure is non-fatal; will retry on next onAppStart
            }
        }
    }

    fun onAppStop() {
        sseJob?.cancel()
        sseJob = null
    }

    private fun handleEvent(event: StreamEvent) {
        when (event) {
            is StreamEvent.ApprovalRequested -> {
                val approval = GlobalApproval(
                    approvalId = event.approvalId,
                    sessionId = event.sessionId,
                    agentType = event.agentType,
                    description = event.description,
                )
                _uiState.update { it.copy(approvals = it.approvals + approval) }
            }
            is StreamEvent.ApprovalGranted -> {
                _uiState.update { state ->
                    state.copy(approvals = state.approvals.filter { it.approvalId != event.approvalId })
                }
            }
            is StreamEvent.ApprovalDenied -> {
                _uiState.update { state ->
                    state.copy(approvals = state.approvals.filter { it.approvalId != event.approvalId })
                }
            }
            else -> Unit
        }
    }

    fun grantApproval(approvalId: String) {
        _uiState.update { state ->
            state.copy(approvals = state.approvals.filter { it.approvalId != approvalId })
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.grantApproval(approvalId)
        }
    }

    fun denyApproval(approvalId: String) {
        _uiState.update { state ->
            state.copy(approvals = state.approvals.filter { it.approvalId != approvalId })
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.denyApproval(approvalId)
        }
    }
}
```

- [ ] **Step 2: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/GlobalApprovalViewModel.kt
git commit -m "feat(android): 新增 GlobalApprovalViewModel 管理全局 SSE 审批队列

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Android — GlobalApprovalBanner

**Files:**
- Create: `$APP/ui/common/GlobalApprovalBanner.kt`

- [ ] **Step 1: 创建 GlobalApprovalBanner Composable**

```kotlin
package com.sebastian.android.ui.common

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.viewmodel.GlobalApproval

@Composable
fun GlobalApprovalBanner(
    approval: GlobalApproval?,
    onGrant: (String) -> Unit,
    onDeny: (String) -> Unit,
    onNavigateToSession: (GlobalApproval) -> Unit,
    modifier: Modifier = Modifier,
) {
    AnimatedVisibility(
        visible = approval != null,
        enter = slideInVertically { -it },
        exit = slideOutVertically { -it },
        modifier = modifier,
    ) {
        approval?.let { current ->
            Surface(
                shape = RoundedCornerShape(bottomStart = 12.dp, bottomEnd = 12.dp),
                shadowElevation = 8.dp,
                color = MaterialTheme.colorScheme.errorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier
                        .statusBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                ) {
                    // Row 1: agent name + description
                    Text(
                        text = "${current.agentType} 请求权限审批",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                    Text(
                        text = current.description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.8f),
                        maxLines = 3,
                        modifier = Modifier.padding(top = 4.dp),
                    )

                    // Row 2: actions
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        TextButton(onClick = { onNavigateToSession(current) }) {
                            Text("查看详情")
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                            Button(
                                onClick = { onDeny(current.approvalId) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.error,
                                ),
                                modifier = Modifier.widthIn(min = 80.dp),
                            ) {
                                Text("拒绝")
                            }
                            Button(
                                onClick = { onGrant(current.approvalId) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.primary,
                                ),
                                modifier = Modifier.widthIn(min = 80.dp),
                            ) {
                                Text("允许")
                            }
                        }
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 2: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/GlobalApprovalBanner.kt
git commit -m "feat(android): 新增 GlobalApprovalBanner 悬浮顶部审批通知

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Android — ChatViewModel 移除审批处理 + 新增 sendAgentMessage

**Files:**
- Modify: `$APP/viewmodel/ChatViewModel.kt`

- [ ] **Step 1: 移除审批相关代码**

在 `ChatViewModel.kt` 中：

1. 删除 `PendingApproval` data class（约第38-42行）：

```kotlin
// 删除整个 PendingApproval data class
```

2. 从 `ChatUiState` 中删除 `pendingApprovals` 字段（约第52行）：

将 `ChatUiState` 改为：

```kotlin
data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeThinkingEffort: ThinkingEffort = ThinkingEffort.AUTO,
    val activeSessionId: String? = null,
    val isOffline: Boolean = false,
    val error: String? = null,
    val isServerNotConfigured: Boolean = false,
    val connectionFailed: Boolean = false,
    val flushTick: Long = 0L,
)
```

3. 在 `handleEvent` 方法中，删除 `ApprovalRequested`、`ApprovalGranted`、`ApprovalDenied` 三个分支（约第274-294行），保留 `else -> Unit`。

4. 删除 `grantApproval` 和 `denyApproval` 方法（约第434-445行）。

- [ ] **Step 2: 新增 sendAgentMessage 方法**

在 `ChatViewModel.kt` 的 `sendSessionMessage` 方法之后（约第351行后），新增：

```kotlin
    fun sendAgentMessage(agentId: String, text: String) {
        if (text.isBlank()) return
        val currentSessionId = _uiState.value.activeSessionId
        val userMsg = Message(
            id = UUID.randomUUID().toString(),
            sessionId = currentSessionId ?: "pending",
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
            if (currentSessionId == null) {
                // New agent session: create + start SSE
                sessionRepository.createAgentSession(agentId, text)
                    .onSuccess { session ->
                        _uiState.update { it.copy(activeSessionId = session.id) }
                        startSseCollection(replayFromStart = true)
                        sessionRepository.loadAgentSessions(agentId)
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                    }
            } else {
                // Existing session: send turn
                chatRepository.sendSessionTurn(currentSessionId, text, _uiState.value.activeThinkingEffort)
                    .onSuccess {
                        if (sseJob?.isActive != true) {
                            startSseCollection(replayFromStart = true)
                        }
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                    }
            }
        }
    }
```

**依赖：** 此 Step 调用了 `sessionRepository.loadAgentSessions()`，需先完成 Task 7。建议执行顺序：Task 7 → Task 5。

- [ ] **Step 3: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
git commit -m "refactor(android): ChatViewModel 移除审批处理 + 新增 sendAgentMessage

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Android — Route 变更

**Files:**
- Modify: `$APP/ui/navigation/Route.kt`

- [ ] **Step 1: 修改 Route.kt**

替换 `Route.kt` 全部内容：

```kotlin
package com.sebastian.android.ui.navigation

import kotlinx.serialization.Serializable

@Serializable
sealed class Route {
    @Serializable
    data object Chat : Route()

    @Serializable
    data object SubAgents : Route()

    @Serializable
    data class AgentChat(val agentId: String, val agentName: String) : Route()

    @Serializable
    data object Settings : Route()

    @Serializable
    data object SettingsConnection : Route()

    @Serializable
    data object SettingsProviders : Route()

    @Serializable
    data object SettingsProvidersNew : Route()

    @Serializable
    data class SettingsProvidersEdit(val providerId: String) : Route()

    @Serializable
    data object SettingsAppearance : Route()

    @Serializable
    data object SettingsDebugLogging : Route()
}
```

已删除 `AgentSessions` 和 `SessionDetail`，新增 `AgentChat`。

- [ ] **Step 2: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/navigation/Route.kt
git commit -m "refactor(android): Route 新增 AgentChat，删除 AgentSessions/SessionDetail

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Android — SessionViewModel 新增 loadAgentSessions

**Files:**
- Modify: `$APP/viewmodel/SessionViewModel.kt`
- Modify: `$APP/data/repository/SessionRepository.kt`
- Modify: `$APP/data/repository/SessionRepositoryImpl.kt`

- [ ] **Step 1: SessionRepository 接口新增 loadAgentSessions**

在 `$APP/data/repository/SessionRepository.kt` 接口中，确认 `getAgentSessions` 已存在（当前已有），然后新增 `loadAgentSessions` 方法签名（将结果写入 `sessionsFlow`）：

```kotlin
interface SessionRepository {
    fun sessionsFlow(): Flow<List<Session>>
    suspend fun loadSessions(): Result<List<Session>>
    suspend fun loadAgentSessions(agentType: String): Result<List<Session>>
    suspend fun createSession(title: String? = null): Result<Session>
    suspend fun deleteSession(sessionId: String): Result<Unit>
    suspend fun getAgentSessions(agentType: String): Result<List<Session>>
    suspend fun createAgentSession(agentType: String, title: String? = null): Result<Session>
}
```

- [ ] **Step 2: SessionRepositoryImpl 实现 loadAgentSessions**

在 `$APP/data/repository/SessionRepositoryImpl.kt` 中新增：

```kotlin
    override suspend fun loadAgentSessions(agentType: String): Result<List<Session>> = runCatching {
        val sessions = apiService.getAgentSessions(agentType).sessions.map { it.toDomain() }
        _sessions.value = sessions
        sessions
    }
```

- [ ] **Step 3: SessionViewModel 新增 loadAgentSessions**

在 `$APP/viewmodel/SessionViewModel.kt` 中新增方法：

```kotlin
    fun loadAgentSessions(agentType: String) {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true) }
            repository.loadAgentSessions(agentType)
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
                .onSuccess { _uiState.update { it.copy(isLoading = false) } }
        }
    }
```

- [ ] **Step 4: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/SessionViewModel.kt
git commit -m "feat(android): SessionViewModel 新增 loadAgentSessions 支持按 agent 加载 session 列表

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Android — SessionPanel 精简模式

**Files:**
- Modify: `$APP/ui/chat/SessionPanel.kt`

- [ ] **Step 1: 修改 SessionPanel 签名和布局**

修改 `SessionPanel` 函数签名，新增 `agentName` 参数，将 `onNavigateToSettings` 和 `onNavigateToSubAgents` 改为默认空回调：

```kotlin
@Composable
fun SessionPanel(
    sessions: List<Session>,
    activeSessionId: String?,
    isNewSession: Boolean = false,
    agentName: String? = null,
    onSessionClick: (Session) -> Unit,
    onNewSession: () -> Unit,
    onNavigateToSettings: () -> Unit = {},
    onNavigateToSubAgents: () -> Unit = {},
    onClose: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
```

修改布局：在 `Column` 内部，根据 `agentName` 是否为 null 切换标题和功能区：

```kotlin
    Box(modifier = modifier.fillMaxSize().statusBarsPadding()) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Header
            Text(
                text = agentName ?: "Sebastian",
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            )

            // Feature section — only in main chat mode
            if (agentName == null) {
                Column(modifier = Modifier.padding(horizontal = 12.dp)) {
                    Text(
                        text = "功能",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 4.dp, bottom = 8.dp),
                    )
                    FeatureItem(
                        label = "Sub-Agents",
                        onClick = onNavigateToSubAgents,
                    )
                    Spacer(Modifier.height(6.dp))
                    FeatureItem(
                        label = "设置",
                        onClick = onNavigateToSettings,
                    )
                    Spacer(Modifier.height(6.dp))
                    FeatureItem(
                        label = "系统总览",
                        enabled = false,
                        badgeText = "即将推出",
                        onClick = {},
                    )
                }

                HorizontalDivider(modifier = Modifier.padding(top = 12.dp))
            }

            // History section (both modes)
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 12.dp),
            ) {
                Text(
                    text = "历史对话",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 4.dp, top = 12.dp, bottom = 8.dp),
                )
                LazyColumn(modifier = Modifier.weight(1f)) {
                    items(sessions, key = { it.id }) { session ->
                        SessionItem(
                            session = session,
                            isActive = session.id == activeSessionId,
                            onClick = { onSessionClick(session) },
                        )
                    }
                }
            }
        }

        // New chat FAB - bottom right
        NewChatButton(
            enabled = !isNewSession,
            isDark = isDark,
            onClick = onNewSession,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 16.dp, bottom = 40.dp),
        )
    }
```

（其余 private composable 保持不变）

- [ ] **Step 2: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt
git commit -m "feat(android): SessionPanel 支持精简模式（agentName 参数控制）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Android — ChatScreen 参数化

**Files:**
- Modify: `$APP/ui/chat/ChatScreen.kt`

- [ ] **Step 1: 修改 ChatScreen 签名**

```kotlin
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    navController: NavController,
    agentId: String? = null,
    agentName: String? = null,
    chatViewModel: ChatViewModel = hiltViewModel(),
    sessionViewModel: SessionViewModel = hiltViewModel(),
    settingsViewModel: SettingsViewModel = hiltViewModel(),
) {
```

- [ ] **Step 2: 新增 LaunchedEffect 加载 agent sessions**

在 `val chatState by ...` 之前加入：

```kotlin
    // Load appropriate sessions based on mode
    LaunchedEffect(agentId) {
        if (agentId != null) {
            sessionViewModel.loadAgentSessions(agentId)
        }
    }
```

- [ ] **Step 3: 移除 ApprovalDialog**

删除 ChatScreen 中的 `ApprovalDialog` 调用（约第73-79行）。

- [ ] **Step 4: 修改 TopAppBar**

将 TopAppBar 替换为根据 `agentId` 条件渲染：

```kotlin
                TopAppBar(
                    title = { Text(agentName ?: "Sebastian") },
                    navigationIcon = {
                        if (agentId != null) {
                            IconButton(onClick = { navController.popBackStack() }) {
                                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                            }
                        } else {
                            IconButton(onClick = {
                                activePane = if (activePane == SidePane.LEFT) SidePane.NONE else SidePane.LEFT
                            }) {
                                Icon(Icons.Default.Menu, contentDescription = "会话列表")
                            }
                        }
                    },
                    actions = {
                        IconButton(onClick = {
                            activePane = if (activePane == SidePane.RIGHT) SidePane.NONE else SidePane.RIGHT
                        }) {
                            Icon(Icons.Default.Checklist, contentDescription = "待办事项")
                        }
                    },
                )
```

需要新增 import：

```kotlin
import androidx.compose.material.icons.automirrored.filled.ArrowBack
```

- [ ] **Step 5: 修改 SessionPanel 调用**

将 `leftPane` 中的 `SessionPanel` 调用改为：

```kotlin
        leftPane = {
            SessionPanel(
                sessions = sessionState.sessions,
                activeSessionId = chatState.activeSessionId,
                isNewSession = chatState.messages.isEmpty(),
                agentName = agentName,
                onSessionClick = { session ->
                    chatViewModel.switchSession(session.id)
                    activePane = SidePane.NONE
                },
                onNewSession = {
                    chatViewModel.newSession()
                    activePane = SidePane.NONE
                },
                onNavigateToSettings = {
                    navController.navigate(Route.Settings) { launchSingleTop = true }
                },
                onNavigateToSubAgents = {
                    navController.navigate(Route.SubAgents) { launchSingleTop = true }
                },
                onClose = { activePane = SidePane.NONE },
            )
        },
```

- [ ] **Step 6: 修改 Composer onSend**

将 `Composer` 的 `onSend` 回调改为根据 `agentId` 分发：

```kotlin
                    Composer(
                        state = chatState.composerState,
                        activeProvider = settingsState.currentProvider,
                        effort = chatState.activeThinkingEffort,
                        onEffortChange = chatViewModel::setEffort,
                        onSend = { text ->
                            if (agentId != null) {
                                chatViewModel.sendAgentMessage(agentId, text)
                            } else {
                                chatViewModel.sendMessage(text)
                            }
                        },
                        onStop = chatViewModel::cancelTurn,
                    )
```

- [ ] **Step 7: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 8: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "feat(android): ChatScreen 参数化支持 agentId/agentName 复用三面板

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Android — AgentListScreen 导航改为 AgentChat

**Files:**
- Modify: `$APP/ui/subagents/AgentListScreen.kt`

- [ ] **Step 1: 修改导航目标**

将 `AgentListScreen.kt` 第66行的 `navController.navigate` 调用从：

```kotlin
navController.navigate(Route.AgentSessions(agent.agentType)) { launchSingleTop = true }
```

改为：

```kotlin
navController.navigate(Route.AgentChat(agentId = agent.agentType, agentName = agent.name)) { launchSingleTop = true }
```

- [ ] **Step 2: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt
git commit -m "refactor(android): AgentListScreen 导航改为 Route.AgentChat

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: Android — MainActivity 路由表更新 + GlobalApprovalBanner

**Files:**
- Modify: `$APP/MainActivity.kt`

- [ ] **Step 1: 更新 imports**

在 `MainActivity.kt` 中更新 imports：删除 `SessionDetailScreen` 和 `SessionListScreen` 的 import，新增 `GlobalApprovalBanner` 和 `GlobalApprovalViewModel` 的 import：

```kotlin
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.zIndex
import androidx.hilt.navigation.compose.hiltViewModel
import com.sebastian.android.ui.common.GlobalApprovalBanner
import com.sebastian.android.viewmodel.GlobalApprovalViewModel
// 删除这两行：
// import com.sebastian.android.ui.subagents.SessionDetailScreen
// import com.sebastian.android.ui.subagents.SessionListScreen
```

- [ ] **Step 2: 更新 SebastianNavHost**

替换 `SebastianNavHost` 函数：

```kotlin
@Composable
fun SebastianNavHost() {
    val navController = rememberNavController()
    val globalApprovalViewModel: GlobalApprovalViewModel = hiltViewModel()
    val approvalState by globalApprovalViewModel.uiState.collectAsState()
    val animDuration = 300

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> globalApprovalViewModel.onAppStart()
                Lifecycle.Event.ON_STOP -> globalApprovalViewModel.onAppStop()
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        NavHost(
            navController = navController,
            startDestination = Route.Chat,
            enterTransition = {
                slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.Left, tween(animDuration)) +
                    fadeIn(tween(animDuration))
            },
            exitTransition = {
                slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.Left, tween(animDuration)) +
                    fadeOut(tween(animDuration))
            },
            popEnterTransition = {
                slideIntoContainer(AnimatedContentTransitionScope.SlideDirection.Right, tween(animDuration)) +
                    fadeIn(tween(animDuration))
            },
            popExitTransition = {
                slideOutOfContainer(AnimatedContentTransitionScope.SlideDirection.Right, tween(animDuration)) +
                    fadeOut(tween(animDuration))
            },
        ) {
            composable<Route.Chat> {
                ChatScreen(navController = navController)
            }
            composable<Route.SubAgents> {
                AgentListScreen(navController = navController)
            }
            composable<Route.AgentChat> { backStackEntry ->
                val route = backStackEntry.toRoute<Route.AgentChat>()
                ChatScreen(
                    navController = navController,
                    agentId = route.agentId,
                    agentName = route.agentName,
                )
            }
            composable<Route.Settings> {
                SettingsScreen(navController = navController)
            }
            composable<Route.SettingsConnection> {
                ConnectionPage(navController = navController)
            }
            composable<Route.SettingsProviders> {
                ProviderListPage(navController = navController)
            }
            composable<Route.SettingsAppearance> {
                AppearancePage(navController = navController)
            }
            composable<Route.SettingsDebugLogging> {
                DebugLoggingPage(navController = navController)
            }
            composable<Route.SettingsProvidersNew> {
                ProviderFormPage(navController = navController, providerId = null)
            }
            composable<Route.SettingsProvidersEdit> { backStackEntry ->
                val route = backStackEntry.toRoute<Route.SettingsProvidersEdit>()
                ProviderFormPage(navController = navController, providerId = route.providerId)
            }
        }

        // Global approval banner — floats above all screens
        GlobalApprovalBanner(
            approval = approvalState.approvals.firstOrNull(),
            onGrant = globalApprovalViewModel::grantApproval,
            onDeny = globalApprovalViewModel::denyApproval,
            onNavigateToSession = { approval ->
                if (approval.agentType == "sebastian") {
                    navController.navigate(Route.Chat) {
                        popUpTo(Route.Chat) { inclusive = true }
                        launchSingleTop = true
                    }
                } else {
                    navController.navigate(
                        Route.AgentChat(agentId = approval.agentType, agentName = approval.agentType)
                    ) { launchSingleTop = true }
                }
            },
            modifier = Modifier
                .align(Alignment.TopCenter)
                .zIndex(1f),
        )
    }
}
```

新增 imports：

```kotlin
import androidx.compose.runtime.DisposableEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
```

- [ ] **Step 3: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "feat(android): MainActivity 集成 GlobalApprovalBanner + 路由表更新

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 12: Android — 删除 SessionListScreen 和 SessionDetailScreen

**Files:**
- Delete: `$APP/ui/subagents/SessionListScreen.kt`
- Delete: `$APP/ui/subagents/SessionDetailScreen.kt`

- [ ] **Step 1: 删除文件**

```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/SessionListScreen.kt
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/SessionDetailScreen.kt
```

- [ ] **Step 2: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL（确认没有残留引用）

- [ ] **Step 3: Commit**

```bash
git add -u ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/SessionListScreen.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/SessionDetailScreen.kt
git commit -m "chore(android): 删除 SessionListScreen/SessionDetailScreen（已合并到 ChatScreen）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 13: Android — 删除旧 ApprovalDialog（可选清理）

**Files:**
- Delete: `$APP/ui/common/ApprovalDialog.kt`

- [ ] **Step 1: 确认无残留引用**

搜索 `ApprovalDialog` 的所有引用，确认已全部移除：

Run: `grep -r "ApprovalDialog" ui/mobile-android/app/src/main/java/`
Expected: 无输出

- [ ] **Step 2: 删除文件**

```bash
rm ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ApprovalDialog.kt
```

- [ ] **Step 3: 验证编译**

Run: `cd ui/mobile-android && ./gradlew compileDebugKotlin --console=plain 2>&1 | tail -5`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
git add -u ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ApprovalDialog.kt
git commit -m "chore(android): 删除旧 ApprovalDialog（已被 GlobalApprovalBanner 替代）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 14: 更新 README

**Files:**
- Modify: `$APP/ui/README.md`
- Modify: `$APP/ui/subagents/` — 如果有 README 也需要更新

- [ ] **Step 1: 更新 ui/README.md**

更新路由表，反映删除的路由和新增的路由：

| Route | Screen |
|-------|--------|
| `Chat` | `ChatScreen` |
| `SubAgents` | `AgentListScreen` |
| `AgentChat(agentId, agentName)` | `ChatScreen(agentId, agentName)` |
| `Settings` | `SettingsScreen` |
| ... | ... |

更新 `subagents/` 目录结构描述，去掉 `SessionListScreen.kt` 和 `SessionDetailScreen.kt`，只保留 `AgentListScreen.kt`。

更新 `common/` 描述，去掉 `ApprovalDialog.kt`，新增 `GlobalApprovalBanner.kt`。

- [ ] **Step 2: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md
git commit -m "docs(android): 更新 UI README 反映路由和组件变更

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

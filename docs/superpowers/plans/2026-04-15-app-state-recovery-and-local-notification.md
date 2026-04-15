# App 状态恢复 + 本地通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Android App 切到后台再进入后 approval 面板消失导致 agent 卡住的 bug，并为 approval 请求 / 子代理任务完成 / 失败事件接入本地通知（后台才发，前台靠应用内 UI）。

**Architecture:** 新增 `GlobalSseDispatcher` 把唯一全局 SSE 连接转成 `SharedFlow`，供 ViewModel 与本地通知分发器共享订阅；新增 `AppStateReconciler`（Singleton + `ProcessLifecycleOwner`）在 `ON_START` / SSE `onOpen` 时 150ms debounce 触发 REST 快照拉取（`GET /approvals`、`GET /sessions/{id}/recent`），并以幂等主键 merge 喂给各 ViewModel；新增 `NotificationDispatcher` 订阅同一 SSE 流，按前后台状态和事件类型发本地通知。

**Tech Stack:** Kotlin + Jetpack Compose + Hilt + Kotlin Coroutines/Flow + OkHttp SSE + Android `NotificationManager`; 测试 JUnit4 + Mockito-Kotlin + Turbine。

**后端改动：** 无（`GET /approvals`、`GET /sessions/{id}/recent`、`session.completed` / `session.failed` 事件均已存在）。spec 中的 `session_state` 字段推迟到 [multi-device-session-state-sync spec](../specs/2026-04-14-multi-device-session-state-sync-design.md) 的正式实施计划。

**参考 spec：** [`docs/superpowers/specs/2026-04-15-app-state-recovery-and-local-notification-design.md`](../specs/2026-04-15-app-state-recovery-and-local-notification-design.md)

---

## 文件改动总览

| 操作 | 文件 | 职责 |
|------|------|------|
| 新增 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/GlobalSseDispatcher.kt` | 单条全局 SSE 连接 + SharedFlow 分发 + 生命周期绑定 |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt` | 新增 `SessionCompleted` / `SessionFailed` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt` | 解析 `session.completed` / `session.failed` 帧 |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/GlobalApprovalViewModel.kt` | 从 `GlobalSseDispatcher` 订阅；新增 `replaceAll(list)` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt` | 新增 `getSessionRecent` / `getPendingApprovals` 返回类型正规化 |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt` | 新增 `SessionRecentDto` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt` / `ChatRepositoryImpl.kt` | 新增 `getPendingApprovals()` / `getSessionRecent()` |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | 新增 `replaceMessages(list)` + `reconcileCurrentSession()` |
| 新增 | `ui/mobile-android/app/src/main/java/com/sebastian/android/data/sync/AppStateReconciler.kt` | 150ms debounce + 并行拉快照 |
| 新增 | `ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationChannels.kt` | channel 常量与注册 |
| 新增 | `ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationDispatcher.kt` | 订阅 SSE + 前后台判断 + 发/撤通知 |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/SebastianApp.kt` | channel 注册 + 启动 `GlobalSseDispatcher` / `NotificationDispatcher` |
| 修改 | `ui/mobile-android/app/src/main/AndroidManifest.xml` | `POST_NOTIFICATIONS` 权限 + deep link intent-filter |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt` | 首启权限请求 + deep link 导航 + 触发 reconcile |
| 修改 | `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt` | 未授权状态行 + 跳系统设置 |
| 新增 | `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/GlobalSseDispatcherTest.kt` | SharedFlow 分发单测 |
| 新增 | `ui/mobile-android/app/src/test/java/com/sebastian/android/data/sync/AppStateReconcilerTest.kt` | debounce + merge 幂等单测 |
| 新增 | `ui/mobile-android/app/src/test/java/com/sebastian/android/notification/NotificationDispatcherTest.kt` | 前后台判断 + 撤回逻辑单测 |
| 修改 | `ui/mobile-android/README.md` | 导航表补充新模块入口 |

---

## Task 1: `StreamEvent` 扩展 — `SessionCompleted` / `SessionFailed`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseFrameParserSessionTest.kt`

后端 `session.completed` / `session.failed` 事件 payload 已含 `session_id` / `agent_type` / `goal`，客户端目前忽略。通知分发器需要这两个事件，先扩展模型与解析。

- [ ] **Step 1: 写失败测试**

```kotlin
// ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseFrameParserSessionTest.kt
package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.dto.SseFrameParser
import org.junit.Assert.assertEquals
import org.junit.Test

class SseFrameParserSessionTest {
    @Test
    fun `parses session completed frame`() {
        val raw = """{"type":"session.completed","data":{"session_id":"s1","agent_type":"researcher","goal":"查资料"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(
            StreamEvent.SessionCompleted(sessionId = "s1", agentType = "researcher", goal = "查资料"),
            event,
        )
    }

    @Test
    fun `parses session failed frame with error`() {
        val raw = """{"type":"session.failed","data":{"session_id":"s2","agent_type":"coder","goal":"写函数","error":"LLM timeout"}}"""
        val event = SseFrameParser.parse(raw)
        assertEquals(
            StreamEvent.SessionFailed(sessionId = "s2", agentType = "coder", goal = "写函数", error = "LLM timeout"),
            event,
        )
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.SseFrameParserSessionTest"
```

Expected: 编译失败，`StreamEvent.SessionCompleted` / `SessionFailed` 不存在。

- [ ] **Step 3: 在 `StreamEvent.kt` 新增两个子类**

在 `StreamEvent.kt` 的 `Approval` 区段下方、`Unknown` 之前插入：

```kotlin
    // Session lifecycle
    data class SessionCompleted(
        val sessionId: String,
        val agentType: String,
        val goal: String,
    ) : StreamEvent()
    data class SessionFailed(
        val sessionId: String,
        val agentType: String,
        val goal: String,
        val error: String,
    ) : StreamEvent()
```

- [ ] **Step 4: 在 `SseFrameParser.parseByType` 新增两条分支**

在 `"approval.denied" -> ...` 行之后插入：

```kotlin
        "session.completed" -> StreamEvent.SessionCompleted(
            sessionId = data.getString("session_id"),
            agentType = data.optString("agent_type", ""),
            goal = data.optString("goal", ""),
        )
        "session.failed" -> StreamEvent.SessionFailed(
            sessionId = data.getString("session_id"),
            agentType = data.optString("agent_type", ""),
            goal = data.optString("goal", ""),
            error = data.optString("error", ""),
        )
```

- [ ] **Step 5: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.SseFrameParserSessionTest"
```

Expected: PASS。

- [ ] **Step 6: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseFrameParserSessionTest.kt
git commit -m "feat(android): StreamEvent 新增 SessionCompleted/SessionFailed"
```

---

## Task 2: `GlobalSseDispatcher` — 单连接 + SharedFlow 分发

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/GlobalSseDispatcher.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/GlobalSseDispatcherTest.kt`

目标：唯一的全局 SSE 连接由 Singleton 持有，通过 `MutableSharedFlow` 分发给多个消费者（`GlobalApprovalViewModel`、`NotificationDispatcher`、`AppStateReconciler`）。连接生命周期显式通过 `start()` / `stop()` 控制，暴露 `events: SharedFlow<StreamEvent>` 和 `connectionState: StateFlow<ConnectionState>`（`Disconnected` / `Connecting` / `Connected`）。`onOpen` 通过 `connectionState` 从 `Connecting` 转 `Connected` 让订阅者感知。

- [ ] **Step 1: 写失败测试**

```kotlin
// ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/GlobalSseDispatcherTest.kt
package com.sebastian.android.data.remote

import app.cash.turbine.test
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class GlobalSseDispatcherTest {

    @Test
    fun `events flow fans out to multiple subscribers`() = runTest {
        val upstream = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val chatRepo: ChatRepository = mock()
        val settings: SettingsRepository = mock()
        whenever(chatRepo.globalStream("http://x", null)).thenReturn(upstream)
        whenever(settings.serverUrl).thenReturn(flowOf("http://x"))

        val dispatcher = GlobalSseDispatcher(chatRepo, settings, StandardTestDispatcher(testScheduler))
        dispatcher.start(TestScope(testScheduler))
        advanceUntilIdle()

        val collectedA = mutableListOf<StreamEvent>()
        val collectedB = mutableListOf<StreamEvent>()
        val jobA = kotlinx.coroutines.GlobalScope.launch(Dispatchers.Unconfined) {
            dispatcher.events.collect { collectedA.add(it) }
        }
        val jobB = kotlinx.coroutines.GlobalScope.launch(Dispatchers.Unconfined) {
            dispatcher.events.collect { collectedB.add(it) }
        }

        upstream.emit(StreamEvent.ApprovalGranted("a1"))
        advanceUntilIdle()

        assertEquals(listOf<StreamEvent>(StreamEvent.ApprovalGranted("a1")), collectedA)
        assertEquals(listOf<StreamEvent>(StreamEvent.ApprovalGranted("a1")), collectedB)

        jobA.cancel(); jobB.cancel()
    }

    @Test
    fun `connectionState reports Connected when upstream emits first event`() = runTest {
        val upstream = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val chatRepo: ChatRepository = mock()
        val settings: SettingsRepository = mock()
        whenever(chatRepo.globalStream("http://x", null)).thenReturn(upstream)
        whenever(settings.serverUrl).thenReturn(flowOf("http://x"))

        val dispatcher = GlobalSseDispatcher(chatRepo, settings, StandardTestDispatcher(testScheduler))
        dispatcher.start(TestScope(testScheduler))
        advanceUntilIdle()

        dispatcher.connectionState.test {
            assertEquals(ConnectionState.Connecting, awaitItem())
            upstream.emit(StreamEvent.Unknown)
            assertEquals(ConnectionState.Connected, awaitItem())
            cancelAndIgnoreRemainingEvents()
        }
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.GlobalSseDispatcherTest"
```

Expected: 编译失败，`GlobalSseDispatcher` / `ConnectionState` 不存在。

- [ ] **Step 3: 写实现**

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/GlobalSseDispatcher.kt
package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException
import javax.inject.Inject
import javax.inject.Singleton

enum class ConnectionState { Disconnected, Connecting, Connected }

@Singleton
class GlobalSseDispatcher @Inject constructor(
    private val chatRepository: ChatRepository,
    private val settingsRepository: SettingsRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) {
    private val _events = MutableSharedFlow<StreamEvent>(
        replay = 0,
        extraBufferCapacity = 64,
    )
    val events: SharedFlow<StreamEvent> = _events.asSharedFlow()

    private val _connectionState = MutableStateFlow(ConnectionState.Disconnected)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        if (job?.isActive == true) return
        job = scope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) return@launch
            _connectionState.value = ConnectionState.Connecting
            try {
                chatRepository.globalStream(baseUrl).collect { event ->
                    if (_connectionState.value != ConnectionState.Connected) {
                        _connectionState.value = ConnectionState.Connected
                    }
                    _events.emit(event)
                }
            } catch (_: CancellationException) {
                throw CancellationException()
            } catch (_: Exception) {
                // 非致命；下次 start 会重新连接
            } finally {
                _connectionState.value = ConnectionState.Disconnected
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        _connectionState.value = ConnectionState.Disconnected
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.GlobalSseDispatcherTest"
```

Expected: PASS。

- [ ] **Step 5: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/GlobalSseDispatcher.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/GlobalSseDispatcherTest.kt
git commit -m "feat(android): 新增 GlobalSseDispatcher 单连接 SharedFlow 分发"
```

---

## Task 3: `GlobalApprovalViewModel` 改造 — 订阅 dispatcher + `replaceAll`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/GlobalApprovalViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/GlobalApprovalViewModelTest.kt`

当前 ViewModel 自管 SSE Job；改为从 `GlobalSseDispatcher.events` 订阅，并把 `onAppStart`/`onAppStop` 语义下沉到 dispatcher（由 MainActivity 直接控制 dispatcher 启停）。新增 `replaceAll(list)` 供 reconciler 调用。

- [ ] **Step 1: 写失败测试（含 replaceAll 幂等性）**

```kotlin
// ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/GlobalApprovalViewModelTest.kt
package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.repository.ChatRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class GlobalApprovalViewModelTest {

    @Test
    fun `replaceAll upserts by approvalId without duplicating SSE-pushed items`() = runTest {
        val bus = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val sse: GlobalSseDispatcher = mock()
        whenever(sse.events).thenReturn(bus)
        val chatRepo: ChatRepository = mock()

        val vm = GlobalApprovalViewModel(chatRepo, sse, StandardTestDispatcher(testScheduler))
        advanceUntilIdle()

        bus.emit(StreamEvent.ApprovalRequested("s1", "a1", "sebastian", "bash", "{}", "reason"))
        advanceUntilIdle()

        vm.replaceAll(
            listOf(
                ApprovalSnapshot("a1", "s1", "sebastian", "bash", "{}", "reason"),
                ApprovalSnapshot("a2", "s2", "coder", "write", "{}", "r2"),
            )
        )
        advanceUntilIdle()

        assertEquals(listOf("a1", "a2"), vm.uiState.value.approvals.map { it.approvalId })
    }

    @Test
    fun `replaceAll removes items no longer in server snapshot`() = runTest {
        val bus = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val sse: GlobalSseDispatcher = mock()
        whenever(sse.events).thenReturn(bus)
        val chatRepo: ChatRepository = mock()

        val vm = GlobalApprovalViewModel(chatRepo, sse, StandardTestDispatcher(testScheduler))
        advanceUntilIdle()

        bus.emit(StreamEvent.ApprovalRequested("s1", "a1", "sebastian", "bash", "{}", "r"))
        advanceUntilIdle()

        vm.replaceAll(emptyList())
        advanceUntilIdle()

        assertEquals(emptyList<GlobalApproval>(), vm.uiState.value.approvals)
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.GlobalApprovalViewModelTest"
```

Expected: 编译失败，`replaceAll` 与 `ApprovalSnapshot` 不存在；构造签名也改了。

- [ ] **Step 3: 重写 `GlobalApprovalViewModel`**

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/GlobalApprovalViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class GlobalApproval(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val toolName: String,
    val toolInputJson: String,
    val reason: String,
)

/** REST 快照用的幂等 upsert 数据对象，字段与 GlobalApproval 一致 */
data class ApprovalSnapshot(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val toolName: String,
    val toolInputJson: String,
    val reason: String,
)

data class GlobalApprovalUiState(
    val approvals: List<GlobalApproval> = emptyList(),
)

@HiltViewModel
class GlobalApprovalViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    sseDispatcher: GlobalSseDispatcher,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(GlobalApprovalUiState())
    val uiState: StateFlow<GlobalApprovalUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch(dispatcher) {
            sseDispatcher.events.collect { handleEvent(it) }
        }
    }

    private fun handleEvent(event: StreamEvent) {
        when (event) {
            is StreamEvent.ApprovalRequested -> upsert(
                GlobalApproval(
                    approvalId = event.approvalId,
                    sessionId = event.sessionId,
                    agentType = event.agentType,
                    toolName = event.toolName,
                    toolInputJson = event.toolInputJson,
                    reason = event.reason,
                )
            )
            is StreamEvent.ApprovalGranted -> removeById(event.approvalId)
            is StreamEvent.ApprovalDenied -> removeById(event.approvalId)
            else -> Unit
        }
    }

    private fun upsert(approval: GlobalApproval) {
        _uiState.update { state ->
            val filtered = state.approvals.filterNot { it.approvalId == approval.approvalId }
            state.copy(approvals = filtered + approval)
        }
    }

    private fun removeById(approvalId: String) {
        _uiState.update { state ->
            state.copy(approvals = state.approvals.filterNot { it.approvalId == approvalId })
        }
    }

    /** 用 REST 快照整体覆盖；按 approvalId 合并顺序不依赖。 */
    fun replaceAll(snapshot: List<ApprovalSnapshot>) {
        _uiState.update {
            GlobalApprovalUiState(
                approvals = snapshot.map { s ->
                    GlobalApproval(
                        approvalId = s.approvalId,
                        sessionId = s.sessionId,
                        agentType = s.agentType,
                        toolName = s.toolName,
                        toolInputJson = s.toolInputJson,
                        reason = s.reason,
                    )
                }
            )
        }
    }

    fun grantApproval(approvalId: String) {
        removeById(approvalId)
        viewModelScope.launch(dispatcher) { chatRepository.grantApproval(approvalId) }
    }

    fun denyApproval(approvalId: String) {
        removeById(approvalId)
        viewModelScope.launch(dispatcher) { chatRepository.denyApproval(approvalId) }
    }
}
```

- [ ] **Step 4: 删除 `MainActivity` 里对 `onAppStart` / `onAppStop` 的调用占位**

打开 `MainActivity.kt`，定位 `DisposableEffect(lifecycleOwner)` 代码块（约 90 行处），**保留 observer 结构但先把 body 改成空 when 分支**（Task 7 会重新接线到 dispatcher）：

```kotlin
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, _ ->
            // Approval dispatcher 与 reconciler 接线见 Task 7
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
```

并删除 `MainActivity.kt` 顶部 `import com.sebastian.android.viewmodel.GlobalApprovalViewModel.onAppStart` 相关导入（若工具自动清理则跳过）。

- [ ] **Step 5: 运行测试确认通过 + 编译通过**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.GlobalApprovalViewModelTest"
./gradlew :app:compileDebugKotlin
```

Expected: 测试 PASS，编译通过。

- [ ] **Step 6: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/GlobalApprovalViewModel.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/GlobalApprovalViewModelTest.kt
git commit -m "refactor(android): GlobalApprovalViewModel 改为订阅 GlobalSseDispatcher 并新增 replaceAll"
```

---

## Task 4: `ApiService` + `ChatRepository` 新增 approvals / recent 拉取

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`

后端 `GET /approvals` 返回 `{approvals: [...]}`，当前 `ApiService.getPendingApprovals()` 声明返回 `List<Map<String, Any>>` 其实和响应结构对不上（响应是带 key 的 object）。顺手修正。

- [ ] **Step 1: 在 `ApiService.kt` 的 Approvals 区段，把 `getPendingApprovals` 改为：**

```kotlin
    // Approvals
    @GET("api/v1/approvals")
    suspend fun getPendingApprovals(): PendingApprovalsResponse
```

同时新增 `getSessionRecent`（放在 Sessions 区段末尾）：

```kotlin
    @GET("api/v1/sessions/{sessionId}/recent")
    suspend fun getSessionRecent(
        @Path("sessionId") sessionId: String,
        @Query("limit") limit: Int = 50,
    ): SessionRecentResponse
```

- [ ] **Step 2: 在 `SessionDto.kt` 末尾追加 DTO**

```kotlin
data class PendingApprovalsResponse(
    val approvals: List<PendingApprovalDto>,
)

data class PendingApprovalDto(
    val id: String,
    @com.squareup.moshi.Json(name = "session_id") val sessionId: String,
    @com.squareup.moshi.Json(name = "tool_name") val toolName: String,
    @com.squareup.moshi.Json(name = "tool_input") val toolInput: Map<String, Any>?,
    val reason: String?,
    // 后端 approvals 路由目前不返回 agent_type；fallback 到 "sebastian"
    @com.squareup.moshi.Json(name = "agent_type") val agentType: String? = null,
)

data class SessionRecentResponse(
    @com.squareup.moshi.Json(name = "session_id") val sessionId: String,
    val status: String,
    val messages: List<MessageDto>,
)
```

- [ ] **Step 3: 在 `ChatRepository.kt` 接口新增两个方法**

在 `denyApproval` 下方追加：

```kotlin
    suspend fun getPendingApprovals(): Result<List<com.sebastian.android.viewmodel.ApprovalSnapshot>>
    suspend fun getSessionRecent(sessionId: String, limit: Int = 50): Result<List<com.sebastian.android.data.model.Message>>
```

- [ ] **Step 4: 在 `ChatRepositoryImpl.kt` 实现**

```kotlin
    override suspend fun getPendingApprovals(): Result<List<com.sebastian.android.viewmodel.ApprovalSnapshot>> = runCatching {
        apiService.getPendingApprovals().approvals.map { dto ->
            com.sebastian.android.viewmodel.ApprovalSnapshot(
                approvalId = dto.id,
                sessionId = dto.sessionId,
                agentType = dto.agentType ?: "sebastian",
                toolName = dto.toolName,
                toolInputJson = org.json.JSONObject(dto.toolInput ?: emptyMap<String, Any>()).toString(),
                reason = dto.reason.orEmpty(),
            )
        }
    }

    override suspend fun getSessionRecent(sessionId: String, limit: Int): Result<List<com.sebastian.android.data.model.Message>> = runCatching {
        apiService.getSessionRecent(sessionId, limit).messages
            .mapIndexed { index, dto -> dto.toDomain(sessionId, index) }
    }
```

- [ ] **Step 5: 编译通过**

```bash
./gradlew :app:compileDebugKotlin
```

Expected: 通过（若 `MessageDto.toDomain` 签名不同请按现有签名调整）。

- [ ] **Step 6: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt
git commit -m "feat(android): ChatRepository 新增 getPendingApprovals/getSessionRecent"
```

---

## Task 5: `ChatViewModel` 新增 `replaceMessages` + `reconcileCurrentSession`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelReconcileTest.kt`

Reconciler 需要一个线程安全入口把 REST 拉回的消息列表整体替换进 `uiState.messages`，并清理 `pendingDeltas` 缓存（否则冲进来的旧 delta 可能叠到新消息上）。

- [ ] **Step 1: 写失败测试**

```kotlin
// ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelReconcileTest.kt
package com.sebastian.android.viewmodel

import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelReconcileTest {

    @Test
    fun `replaceMessages overrides the current list`() = runTest {
        val chatRepo: ChatRepository = mock()
        val sessionRepo: SessionRepository = mock()
        val settings: SettingsRepository = mock()
        val net: NetworkMonitor = mock()
        whenever(net.isOnline).thenReturn(flowOf(true))

        val vm = ChatViewModel(chatRepo, sessionRepo, settings, net, StandardTestDispatcher(testScheduler))
        advanceUntilIdle()

        val snapshot = listOf(
            Message(
                id = "m1",
                sessionId = "s1",
                role = MessageRole.USER,
                blocks = listOf(ContentBlock.TextBlock("b1", "hello")),
            ),
            Message(
                id = "m2",
                sessionId = "s1",
                role = MessageRole.ASSISTANT,
                blocks = listOf(ContentBlock.TextBlock("b2", "world")),
            ),
        )
        vm.replaceMessages(snapshot)
        advanceUntilIdle()

        assertEquals(listOf("m1", "m2"), vm.uiState.value.messages.map { it.id })
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelReconcileTest"
```

Expected: 编译失败，`replaceMessages` 不存在。

- [ ] **Step 3: 在 `ChatViewModel.kt` 新增方法（放在 `observeNetwork` 附近）**

```kotlin
    /** 用 REST 快照整体替换消息列表；清理 pendingDeltas 防止旧 delta 叠到新消息上。 */
    fun replaceMessages(messages: List<Message>) {
        pendingDeltas.clear()
        _uiState.update { state -> state.copy(messages = messages) }
    }

    /** 回前台 / SSE 重连时调用；若 activeSessionId 为空则不操作。 */
    suspend fun reconcileCurrentSession() {
        val sessionId = _uiState.value.activeSessionId ?: return
        chatRepository.getSessionRecent(sessionId)
            .onSuccess { replaceMessages(it) }
            .onFailure { /* 拉失败不致命，保持现有内存状态 */ }
    }
```

（注意 `reconcileCurrentSession` 是 `suspend`，由 reconciler 在自己 scope 里调用，避免和 ViewModel scope 耦合。）

- [ ] **Step 4: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelReconcileTest"
```

Expected: PASS。

- [ ] **Step 5: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelReconcileTest.kt
git commit -m "feat(android): ChatViewModel 新增 replaceMessages + reconcileCurrentSession"
```

---

## Task 6: `AppStateReconciler` — 150ms debounce + 并行拉快照

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/sync/AppStateReconciler.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/sync/AppStateReconcilerTest.kt`

Singleton 聚合 `reconcile()` 入口；连续多次触发 150ms 内合并为一次；内部并行拉 `getPendingApprovals` 与当前 session 的 recent（当前 session 来源由注入函数暴露，避免和 ChatViewModel 耦合——MainActivity 把"当前 sessionId provider"传进来）。

- [ ] **Step 1: 写失败测试**

```kotlin
// ui/mobile-android/app/src/test/java/com/sebastian/android/data/sync/AppStateReconcilerTest.kt
package com.sebastian.android.data.sync

import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.viewmodel.ApprovalSnapshot
import com.sebastian.android.viewmodel.GlobalApprovalViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.times
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class AppStateReconcilerTest {

    @Test
    fun `three rapid calls collapse to one REST fetch after debounce`() = runTest {
        val chatRepo: ChatRepository = mock()
        whenever(chatRepo.getPendingApprovals()).thenReturn(Result.success(emptyList()))
        val approvalVm: GlobalApprovalViewModel = mock()
        val reconcileChat: suspend () -> Unit = mock()

        val reconciler = AppStateReconciler(
            chatRepository = chatRepo,
            approvalViewModelProvider = { approvalVm },
            reconcileChatSession = reconcileChat,
            debounceMs = 150L,
            dispatcher = StandardTestDispatcher(testScheduler),
        )
        reconciler.attach(TestScope(testScheduler))

        reconciler.reconcile()
        advanceTimeBy(50)
        reconciler.reconcile()
        advanceTimeBy(50)
        reconciler.reconcile()
        advanceUntilIdle()

        verify(chatRepo, times(1)).getPendingApprovals()
        verify(approvalVm, times(1)).replaceAll(emptyList())
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.sync.AppStateReconcilerTest"
```

Expected: 编译失败，`AppStateReconciler` 不存在。

- [ ] **Step 3: 写实现**

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/data/sync/AppStateReconciler.kt
package com.sebastian.android.data.sync

import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.di.IoDispatcher
import com.sebastian.android.viewmodel.GlobalApprovalViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AppStateReconciler @Inject constructor(
    private val chatRepository: ChatRepository,
    @IoDispatcher private val defaultDispatcher: CoroutineDispatcher,
) {
    /** 由 MainActivity 注入：查询当前显示 session 的 hilt viewmodel；chat reconcile 回调 */
    private var approvalViewModelProvider: (() -> GlobalApprovalViewModel)? = null
    private var reconcileChatSession: (suspend () -> Unit)? = null
    private var externalScope: CoroutineScope? = null
    private var pendingJob: Job? = null
    private val debounceMs: Long = 150L
    private val dispatcher: CoroutineDispatcher = defaultDispatcher

    /** 测试专用构造 */
    internal constructor(
        chatRepository: ChatRepository,
        approvalViewModelProvider: () -> GlobalApprovalViewModel,
        reconcileChatSession: suspend () -> Unit,
        debounceMs: Long,
        dispatcher: CoroutineDispatcher,
    ) : this(chatRepository, dispatcher) {
        this.approvalViewModelProvider = approvalViewModelProvider
        this.reconcileChatSession = reconcileChatSession
        // @Suppress - 仅测试路径修改 val；生产路径走 attach()
    }

    fun attach(
        scope: CoroutineScope,
        approvalViewModelProvider: () -> GlobalApprovalViewModel,
        reconcileChatSession: suspend () -> Unit,
    ) {
        this.externalScope = scope
        this.approvalViewModelProvider = approvalViewModelProvider
        this.reconcileChatSession = reconcileChatSession
    }

    /** 测试专用 attach 重载 */
    internal fun attach(scope: CoroutineScope) {
        this.externalScope = scope
    }

    fun reconcile() {
        val scope = externalScope ?: return
        pendingJob?.cancel()
        pendingJob = scope.launch(dispatcher) {
            delay(debounceMs)
            runReconcile()
        }
    }

    private suspend fun runReconcile() = kotlinx.coroutines.coroutineScope {
        val approvalsDeferred = async {
            chatRepository.getPendingApprovals().getOrNull() ?: emptyList()
        }
        val chatReconcileDeferred = async { reconcileChatSession?.invoke() }
        val approvals = approvalsDeferred.await()
        approvalViewModelProvider?.invoke()?.replaceAll(approvals)
        chatReconcileDeferred.await()
    }
}
```

> 注意：上面的 `internal constructor(...)` 模式允许测试直接注入协作者。生产代码路径通过 `attach(scope, provider, reconcileFn)` 注入。

- [ ] **Step 4: 调整测试以匹配实际 API（如有偏差）并运行**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.sync.AppStateReconcilerTest"
```

Expected: PASS。若 Kotlin `val`/`internal constructor` 报"重复初始化"编译错误，改为将 3 个字段声明为 `private var` 即可。

- [ ] **Step 5: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/sync/AppStateReconciler.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/data/sync/AppStateReconcilerTest.kt
git commit -m "feat(android): 新增 AppStateReconciler 150ms debounce 并行拉快照"
```

---

## Task 7: `MainActivity` 接线 — 生命周期触发 dispatcher + reconciler

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`（暴露 reconcile 委托）

把 `ProcessLifecycleOwner`（进程级）的 `ON_START` 和 `GlobalSseDispatcher.connectionState` 变成 `Connected` 这两个事件连到 reconciler。

- [ ] **Step 1: 在 `MainActivity.kt` 顶部新增依赖注入**

```kotlin
import androidx.lifecycle.ProcessLifecycleOwner
import com.sebastian.android.data.remote.ConnectionState
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.sync.AppStateReconciler
// ...

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var settingsDataStore: SettingsDataStore
    @Inject lateinit var sseDispatcher: GlobalSseDispatcher
    @Inject lateinit var stateReconciler: AppStateReconciler
```

- [ ] **Step 2: 在 `SebastianNavHost` 内替换原先的 `DisposableEffect(lifecycleOwner)` 块**

```kotlin
    val globalApprovalViewModel: GlobalApprovalViewModel = hiltViewModel()
    val chatViewModel: ChatViewModel = hiltViewModel()  // 复用主 ChatScreen 的 VM（Hilt 默认 scope 内同一实例）

    // Attach reconciler 一次（相当于 init）
    DisposableEffect(Unit) {
        val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate)
        (LocalContext.current.applicationContext as com.sebastian.android.SebastianApp)
            .attachReconciler(scope, { globalApprovalViewModel }, { chatViewModel.reconcileCurrentSession() })
        onDispose { scope.coroutineContext[kotlinx.coroutines.Job]?.cancel() }
    }

    // 进程级生命周期：ON_START 启动 SSE 并触发 reconcile；ON_STOP 断开 SSE
    DisposableEffect(Unit) {
        val owner = ProcessLifecycleOwner.get()
        val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate)
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> {
                    sseDispatcher.start(scope)
                    stateReconciler.reconcile()
                }
                Lifecycle.Event.ON_STOP -> sseDispatcher.stop()
                else -> Unit
            }
        }
        owner.lifecycle.addObserver(observer)
        // SSE onOpen 也触发一次 reconcile（debounce 会合并）
        val connectionJob = scope.launch {
            sseDispatcher.connectionState.collect { state ->
                if (state == ConnectionState.Connected) stateReconciler.reconcile()
            }
        }
        onDispose {
            owner.lifecycle.removeObserver(observer)
            connectionJob.cancel()
        }
    }
```

（`SebastianApp.attachReconciler` 在 Task 9 引入；这里可以先直接调用 `stateReconciler.attach(scope, ..., ...)` 避免循环依赖——改为：）

```kotlin
    DisposableEffect(Unit) {
        val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate)
        stateReconciler.attach(
            scope = scope,
            approvalViewModelProvider = { globalApprovalViewModel },
            reconcileChatSession = { chatViewModel.reconcileCurrentSession() },
        )
        onDispose { scope.coroutineContext[kotlinx.coroutines.Job]?.cancel() }
    }
```

使用这版（不走 SebastianApp），删除上面 `attachReconciler` 相关占位。

- [ ] **Step 3: 编译通过 + 手动在模拟器上冒烟验证**

```bash
./gradlew :app:installDebug
# 启动 App，触发一个 approval（在 Sebastian 主对话里跑一个需要审批的工具），
# 然后按 Home 键切后台，再进 App。
# 预期：approval banner 仍然显示那条。
```

- [ ] **Step 4: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "feat(android): MainActivity 接线 GlobalSseDispatcher + AppStateReconciler"
```

---

## Task 8: `NotificationChannels` — channel 注册

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationChannels.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/SebastianApp.kt`

- [ ] **Step 1: 写 NotificationChannels.kt**

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationChannels.kt
package com.sebastian.android.notification

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import androidx.core.content.getSystemService

object NotificationChannels {
    const val APPROVAL = "approval"
    const val TASK_PROGRESS = "task_progress"

    fun registerAll(context: Context) {
        val manager = context.getSystemService<NotificationManager>() ?: return
        manager.createNotificationChannel(
            NotificationChannel(
                APPROVAL,
                "审批请求",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "Agent 需要你批准或拒绝的工具调用"
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(
                TASK_PROGRESS,
                "任务进度",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "子代理完成或失败的状态"
            }
        )
    }
}
```

- [ ] **Step 2: 在 `SebastianApp.onCreate` 调用注册**

打开 `SebastianApp.kt`，在 `onCreate()` 内末尾追加：

```kotlin
        com.sebastian.android.notification.NotificationChannels.registerAll(this)
```

若 `SebastianApp` 尚未 override `onCreate()`，改为：

```kotlin
@HiltAndroidApp
class SebastianApp : android.app.Application() {
    override fun onCreate() {
        super.onCreate()
        com.sebastian.android.notification.NotificationChannels.registerAll(this)
    }
}
```

- [ ] **Step 3: 编译通过**

```bash
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 4: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationChannels.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/SebastianApp.kt
git commit -m "feat(android): 注册审批 / 任务进度 NotificationChannel"
```

---

## Task 9: `NotificationDispatcher` — 前后台判断 + 发/撤通知

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationDispatcher.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/SebastianApp.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/notification/NotificationDispatcherTest.kt`

核心职责：订阅 `GlobalSseDispatcher.events`，按前后台过滤（注入一个 `ForegroundChecker` 方便测试），把事件映射成 `NotificationCompat.Builder` 调用 `NotificationManagerCompat.notify`；收到 `ApprovalGranted/Denied` 撤回旧通知。

- [ ] **Step 1: 写失败测试**

```kotlin
// ui/mobile-android/app/src/test/java/com/sebastian/android/notification/NotificationDispatcherTest.kt
package com.sebastian.android.notification

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class NotificationDispatcherTest {

    @Test
    fun `foreground events are suppressed`() = runTest {
        val bus = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val sse: GlobalSseDispatcher = mock(); whenever(sse.events).thenReturn(bus)
        val sink: NotificationSink = mock()
        val dispatcher = NotificationDispatcher(sse, sink, foregroundChecker = { true }, dispatcher = StandardTestDispatcher(testScheduler))
        dispatcher.start(TestScope(testScheduler))
        advanceUntilIdle()

        bus.emit(StreamEvent.ApprovalRequested("s1", "a1", "sebastian", "bash", "{}", "reason"))
        advanceUntilIdle()

        verify(sink, never()).notify(any(), any())
    }

    @Test
    fun `background approval emits heads-up on approval channel`() = runTest {
        val bus = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val sse: GlobalSseDispatcher = mock(); whenever(sse.events).thenReturn(bus)
        val sink: NotificationSink = mock()
        val dispatcher = NotificationDispatcher(sse, sink, foregroundChecker = { false }, dispatcher = StandardTestDispatcher(testScheduler))
        dispatcher.start(TestScope(testScheduler))
        advanceUntilIdle()

        bus.emit(StreamEvent.ApprovalRequested("s1", "a1", "sebastian", "bash", "{}", "rm -rf"))
        advanceUntilIdle()

        verify(sink).notify(
            eqHash("a1"),
            matchNotification(channelId = NotificationChannels.APPROVAL, title = "需要审批：bash")
        )
    }

    @Test
    fun `granted approval cancels its pending notification`() = runTest {
        val bus = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 16)
        val sse: GlobalSseDispatcher = mock(); whenever(sse.events).thenReturn(bus)
        val sink: NotificationSink = mock()
        val dispatcher = NotificationDispatcher(sse, sink, foregroundChecker = { false }, dispatcher = StandardTestDispatcher(testScheduler))
        dispatcher.start(TestScope(testScheduler))
        advanceUntilIdle()

        bus.emit(StreamEvent.ApprovalRequested("s1", "a1", "sebastian", "bash", "{}", "rm -rf"))
        bus.emit(StreamEvent.ApprovalGranted("a1"))
        advanceUntilIdle()

        verify(sink).cancel(eqHash("a1"))
    }

    // 辅助
    private fun eqHash(approvalId: String): Int = approvalId.hashCode()
    private fun matchNotification(channelId: String, title: String): NotificationSpec =
        org.mockito.kotlin.argThat { it.channelId == channelId && it.title == title }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.notification.NotificationDispatcherTest"
```

Expected: 编译失败，`NotificationDispatcher` / `NotificationSink` / `NotificationSpec` 不存在。

- [ ] **Step 3: 写实现**

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationDispatcher.kt
package com.sebastian.android.notification

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import com.sebastian.android.MainActivity
import com.sebastian.android.R
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

/** 通知发送端口抽象（测试用 mock 替换，避免依赖真实 NotificationManager） */
interface NotificationSink {
    fun notify(id: Int, spec: NotificationSpec)
    fun cancel(id: Int)
}

/** 与 Android NotificationCompat 解耦的纯数据描述 */
data class NotificationSpec(
    val channelId: String,
    val title: String,
    val body: String,
    val sessionId: String,
)

@Singleton
class NotificationDispatcher @Inject constructor(
    private val sseDispatcher: GlobalSseDispatcher,
    private val sink: NotificationSink,
    private val foregroundChecker: () -> Boolean = {
        ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
    },
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) {
    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        if (job?.isActive == true) return
        job = scope.launch(dispatcher) {
            sseDispatcher.events.collect { handle(it) }
        }
    }

    fun stop() { job?.cancel(); job = null }

    private fun handle(event: StreamEvent) {
        when (event) {
            is StreamEvent.ApprovalRequested -> if (!foregroundChecker()) {
                sink.notify(
                    event.approvalId.hashCode(),
                    NotificationSpec(
                        channelId = NotificationChannels.APPROVAL,
                        title = "需要审批：${event.toolName}",
                        body = event.reason.take(120),
                        sessionId = event.sessionId,
                    ),
                )
            }
            is StreamEvent.ApprovalGranted -> sink.cancel(event.approvalId.hashCode())
            is StreamEvent.ApprovalDenied -> sink.cancel(event.approvalId.hashCode())
            is StreamEvent.SessionCompleted -> if (!foregroundChecker()) {
                sink.notify(
                    ("completed:" + event.sessionId).hashCode(),
                    NotificationSpec(
                        channelId = NotificationChannels.TASK_PROGRESS,
                        title = "${event.agentType} 已完成",
                        body = event.goal.take(120),
                        sessionId = event.sessionId,
                    ),
                )
            }
            is StreamEvent.SessionFailed -> if (!foregroundChecker()) {
                sink.notify(
                    ("failed:" + event.sessionId).hashCode(),
                    NotificationSpec(
                        channelId = NotificationChannels.TASK_PROGRESS,
                        title = "${event.agentType} 执行失败",
                        body = (event.error.ifBlank { event.goal }).take(120),
                        sessionId = event.sessionId,
                    ),
                )
            }
            else -> Unit
        }
    }
}

/** 生产实现：把 NotificationSpec 变成 NotificationCompat 并发到系统 */
@Singleton
class AndroidNotificationSink @Inject constructor(
    @ApplicationContext private val context: Context,
) : NotificationSink {
    override fun notify(id: Int, spec: NotificationSpec) {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("sebastian://session/${spec.sessionId}"))
            .setPackage(context.packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pending = PendingIntent.getActivity(
            context,
            id,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, spec.channelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(spec.title)
            .setContentText(spec.body)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).apply {
            if (areNotificationsEnabled()) notify(id, notification)
        }
    }

    override fun cancel(id: Int) {
        NotificationManagerCompat.from(context).cancel(id)
    }
}
```

- [ ] **Step 4: Hilt 绑定 `NotificationSink`**

在 `ui/mobile-android/app/src/main/java/com/sebastian/android/di/NetworkModule.kt` 或新建 `NotificationModule.kt`：

```kotlin
// ui/mobile-android/app/src/main/java/com/sebastian/android/di/NotificationModule.kt
package com.sebastian.android.di

import com.sebastian.android.notification.AndroidNotificationSink
import com.sebastian.android.notification.NotificationSink
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class NotificationModule {
    @Binds
    @Singleton
    abstract fun bindNotificationSink(impl: AndroidNotificationSink): NotificationSink
}
```

- [ ] **Step 5: 在 `SebastianApp.onCreate` 启动 dispatcher**

```kotlin
@HiltAndroidApp
class SebastianApp : android.app.Application() {
    @Inject lateinit var notificationDispatcher: com.sebastian.android.notification.NotificationDispatcher

    private val appScope = kotlinx.coroutines.CoroutineScope(
        kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Default
    )

    override fun onCreate() {
        super.onCreate()
        com.sebastian.android.notification.NotificationChannels.registerAll(this)
        notificationDispatcher.start(appScope)
    }
}
```

注意 `notificationDispatcher` 订阅的是 `GlobalSseDispatcher.events`；后者尚未 `start`（MainActivity 会在 `ON_START` 时调 `sseDispatcher.start`），收不到事件也不报错。

- [ ] **Step 6: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.notification.NotificationDispatcherTest"
```

Expected: PASS。

- [ ] **Step 7: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationDispatcher.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/di/NotificationModule.kt \
        ui/mobile-android/app/src/main/java/com/sebastian/android/SebastianApp.kt \
        ui/mobile-android/app/src/test/java/com/sebastian/android/notification/NotificationDispatcherTest.kt
git commit -m "feat(android): NotificationDispatcher 订阅 SSE 发/撤本地通知"
```

---

## Task 10: AndroidManifest — 权限 + deep link

**Files:**
- Modify: `ui/mobile-android/app/src/main/AndroidManifest.xml`

- [ ] **Step 1: 在 `<manifest>` 下新增权限，在 `<activity>` 下新增 intent-filter**

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

    <application
        android:name=".SebastianApp"
        android:label="Sebastian"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:supportsRtl="true"
        android:theme="@style/Theme.Sebastian"
        android:networkSecurityConfig="@xml/network_security_config"
        android:enableOnBackInvokedCallback="true">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:launchMode="singleTask"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.VIEW" />
                <category android:name="android.intent.category.DEFAULT" />
                <category android:name="android.intent.category.BROWSABLE" />
                <data android:scheme="sebastian" android:host="session" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

- [ ] **Step 2: 编译确认**

```bash
./gradlew :app:assembleDebug
```

- [ ] **Step 3: commit**

```bash
git add ui/mobile-android/app/src/main/AndroidManifest.xml
git commit -m "feat(android): manifest 加 POST_NOTIFICATIONS 权限 + sebastian://session/* deep link"
```

---

## Task 11: `MainActivity` — 首启权限请求 + deep link 导航

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 1: 在 `MainActivity.onCreate` 顶部（`super.onCreate` 之后）申请通知权限**

```kotlin
    private val requestNotificationPermission =
        registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {
            // 用户拒绝时不做任何处理；Settings 页提供重新打开入口
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        maybeRequestNotificationPermission()
        enableEdgeToEdge()
        setContent { /* 原内容 */ }
    }

    private fun maybeRequestNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.TIRAMISU) return
        val perm = android.Manifest.permission.POST_NOTIFICATIONS
        if (checkSelfPermission(perm) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestNotificationPermission.launch(perm)
        }
    }
```

- [ ] **Step 2: 处理 deep link（`sebastian://session/{sessionId}`）并导航**

在 `SebastianNavHost` 内，收到带 `data` 的 Intent 时解析并导航。新增一个接受 `startSessionId` 的参数：

```kotlin
@Composable
fun SebastianNavHost(startSessionId: String? = null) {
    // ...
    // 注意：如果 startSessionId != null，用 LaunchedEffect 在组合后导航
    LaunchedEffect(startSessionId) {
        if (!startSessionId.isNullOrBlank()) {
            navController.navigate(Route.Chat(sessionId = startSessionId)) {
                popUpTo<Route.Chat> { inclusive = false }
                launchSingleTop = true
            }
        }
    }
    // ...原有 Box { NavHost ... } 不变
}
```

在 `MainActivity.setContent { ... }` 调用处传入解析结果：

```kotlin
        setContent {
            val themeMode by settingsDataStore.theme.collectAsState(initial = "system")
            SebastianTheme(themeMode = themeMode) {
                val surfaceColor = MaterialTheme.colorScheme.surface
                SideEffect {
                    window.setBackgroundDrawable(ColorDrawable(surfaceColor.toArgb()))
                }
                val startSessionId = remember {
                    intent?.data?.takeIf { it.scheme == "sebastian" && it.host == "session" }
                        ?.pathSegments?.firstOrNull()
                }
                SebastianNavHost(startSessionId = startSessionId)
            }
        }
```

此外 override `onNewIntent`（singleTask 模式下，后续点击通知会走这里）：

```kotlin
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)  // 下一次 composition 读取到最新 intent；Compose 通过 activity recreate 或手动 recomposition 拿到
        // 简单起见：如果当前已显示 Compose，直接 recreate。
        recreate()
    }
```

> `recreate()` 是简单方案（可接受的代价）；未来可改为维护 `mutableStateOf<Uri?>` 传给 `SebastianNavHost`。

- [ ] **Step 3: 手动测试**

```bash
./gradlew :app:installDebug
# 在设备上运行：
~/Library/Android/sdk/platform-tools/adb shell am start -a android.intent.action.VIEW -d "sebastian://session/demo-session-id"
# 预期：App 启动并落到 Chat(sessionId="demo-session-id")
```

- [ ] **Step 4: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "feat(android): 启动时请求通知权限 + sebastian://session deep link 导航"
```

---

## Task 12: Settings 页未授权状态行

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`

- [ ] **Step 1: 先用 Read 看清 `SettingsScreen.kt` 当前结构，找到合适的条目区段（比如在"通用"分组末尾）**

- [ ] **Step 2: 新增一行可点击条目**

```kotlin
@Composable
private fun NotificationPermissionRow() {
    val context = LocalContext.current
    val enabled by remember(context) {
        mutableStateOf(
            androidx.core.app.NotificationManagerCompat.from(context).areNotificationsEnabled()
        )
    }
    if (enabled) return

    ListItem(
        headlineContent = { Text("通知权限未开启") },
        supportingContent = { Text("开启后 Sebastian 离线时可通知审批与任务完成") },
        trailingContent = {
            TextButton(onClick = {
                val intent = android.content.Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, context.packageName)
                context.startActivity(intent)
            }) { Text("去设置") }
        },
        modifier = Modifier.fillMaxWidth(),
    )
}
```

并在 `SettingsScreen` 主体的合适位置调用 `NotificationPermissionRow()`。

- [ ] **Step 3: 冒烟验证**

手动在设备上：系统设置里关掉 App 的通知权限 → 打开 Settings 页 → 应看到"通知权限未开启"一行 → 点"去设置"跳转。

- [ ] **Step 4: commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt
git commit -m "feat(android): Settings 页展示通知权限状态 + 跳系统设置入口"
```

---

## Task 13: 集成冒烟验证 + README 同步

**Files:**
- Modify: `ui/mobile-android/README.md`

- [ ] **Step 1: 在 `ui/mobile-android/README.md` 的"修改导航"表补充**

```markdown
| 改全局 SSE 分发 | `data/remote/GlobalSseDispatcher.kt` |
| 改状态恢复 / reconcile | `data/sync/AppStateReconciler.kt` |
| 改本地通知 | `notification/NotificationDispatcher.kt`、`notification/NotificationChannels.kt` |
```

- [ ] **Step 2: 在"SSE 连接机制"章节追加一段**

```markdown
### 状态恢复与本地通知

`GlobalSseDispatcher`（Singleton）持有唯一的全局 SSE 连接并通过 `SharedFlow` 分发给：
- `GlobalApprovalViewModel`（原订阅逻辑迁移至此）
- `NotificationDispatcher`（后台时发本地通知）
- `AppStateReconciler`（监听 `connectionState` 的 `Connected` 转换，触发 reconcile）

`AppStateReconciler` 在 `ProcessLifecycleOwner.ON_START` 或 SSE `onOpen` 时 150ms debounce 并行拉取：
- `GET /api/v1/approvals` → `GlobalApprovalViewModel.replaceAll`
- `GET /api/v1/sessions/{id}/recent` → `ChatViewModel.replaceMessages`

`NotificationDispatcher` 仅在 App 处于后台时发通知（`ProcessLifecycleOwner.currentState < STARTED`）；通知点击携带 `sebastian://session/{id}` deep link 回到对应 session。
```

- [ ] **Step 3: 手动端到端冒烟清单（不作代码改动，验证后打勾即可）**

| # | 场景 | 预期 |
|---|------|------|
| 1 | 在 Sebastian 里触发需审批的工具；按 Home；立即回到 App | Banner 仍显示那条 approval |
| 2 | 场景 1 基础上，杀掉 App 进程（最近任务划掉）；重新启动 | Banner 恢复显示那条 approval |
| 3 | 派发子代理任务；把 App 退后台；等任务完成 | 通知栏出现 "{agentType} 已完成" |
| 4 | 场景 3 的通知点击 | App 打开并落到该子代理 session |
| 5 | 前台触发 approval | **不**出现系统通知；只有 banner |
| 6 | 前台批准某 approval（先离线让后台通知已发）再回到前台 | 通知自动撤回 |
| 7 | 系统设置里关掉通知权限，打开 Settings 页 | 显示"通知权限未开启" + 跳转按钮 |
| 8 | 首次全新安装后启动 App | Android 13+ 弹出 `POST_NOTIFICATIONS` 权限请求 |

- [ ] **Step 4: 提交 README**

```bash
git add ui/mobile-android/README.md
git commit -m "docs(android): README 补状态恢复 / 本地通知 模块说明"
```

- [ ] **Step 5: 创建 PR**

```bash
git push
gh pr create --base main --head dev --title "feat(android): App 状态恢复 + 本地通知" --body "$(cat <<'EOF'
## Summary
- 新增 GlobalSseDispatcher（单连接 SharedFlow 分发），拆分全局 SSE 订阅生命周期
- 新增 AppStateReconciler：ProcessLifecycleOwner.ON_START 与 SSE 重连时拉 REST 快照（approvals + session recent）幂等 merge，修复"切后台再进入审批面板消失"bug
- 新增本地通知（approval HIGH heads-up / task_progress DEFAULT），仅在 App 处于后台时发送；通知点击 deep link sebastian://session/{id}
- Android 13+ 启动时请求 POST_NOTIFICATIONS；Settings 页提供未授权状态行 + 跳系统设置

## Test plan
- [ ] `./gradlew :app:testDebugUnitTest` 全绿
- [ ] README "手动端到端冒烟清单" 8 项全部通过
- [ ] PR CI（backend-lint / backend-type / backend-test / mobile-lint）全绿
EOF
)"
```

---

## Self-Review Notes

**Spec 覆盖对照：**

| Spec 要求 | 对应 Task |
|---|---|
| REST 快照 + SSE 增量幂等 merge | 3, 5, 6 |
| `ProcessLifecycleOwner.ON_START` 触发 | 7 |
| SSE `onOpen` 触发（debounce 合并） | 2, 7 |
| `GlobalSseDispatcher` 拆分 | 2 |
| `replaceAll(list)` / `replaceMessages(list)` | 3, 5 |
| 本地通知前台不发 | 9 |
| channel 分组（approval HIGH / task_progress DEFAULT） | 8 |
| 通知去重 / granted-denied 撤回 | 9 |
| 权限请求（首启） | 11 |
| Settings 页未授权状态行 + 跳系统设置 | 12 |
| Deep link `sebastian://session/{id}` | 10, 11 |
| 单测覆盖（reconciler 幂等 / 通知前后台） | 6, 9 |

**Spec 中显式推迟的项（不在本计划）：**
- `GET /sessions/{id}/recent` 的 `session_state` 字段（归 multi-device-session-state-sync spec）
- 跨进程推送（FCM / 国内厂商 / 聚合 SDK）
- 通知富交互、摘要合并、设备列表、Draft 同步

**类型一致性检查：** `ApprovalSnapshot`（Task 3 定义）被 Task 4 的 Repository 返回，Task 6 Reconciler 传递，全链路一致；`NotificationSpec` 只在 Task 9 内使用；`ConnectionState` 在 Task 2 定义、Task 7 消费，一致。

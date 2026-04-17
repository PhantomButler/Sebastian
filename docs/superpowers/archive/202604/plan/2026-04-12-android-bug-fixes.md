# Android 客户端 Bug 修复 + 架构纠偏实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Android 客户端 code review 中发现的 2 个 Critical 问题和 12 个 Major 问题，消除架构越界、并发数据丢失 bug、滚动跟随振荡和 SSE 连接状态管理缺陷。

**Architecture:** 分 9 个独立 Task 顺序执行。Task 1–3 为纯架构纠偏（可独立验证），Task 4–7 修复 ChatViewModel / MessageList 核心逻辑，Task 8–9 为 UI 组件小改动。每个 Task 以 build 通过为验收门槛，关键逻辑有单元测试。

**Tech Stack:** Kotlin 2.x + Jetpack Compose + Hilt + OkHttp/Retrofit + kotlinx-coroutines

工作目录：`ui/mobile-android/`  
构建命令：`./gradlew :app:assembleDebug`  
单元测试：`./gradlew :app:testDebugUnitTest`

---

## 文件结构总览

| 操作 | 路径 |
|------|------|
| 新建 | `app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt` |
| 新建 | `app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt` |
| 新建 | `app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt` |
| 新建 | `app/src/main/java/com/sebastian/android/ui/common/ErrorBanner.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/viewmodel/SessionViewModel.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/viewmodel/SubAgentViewModel.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/di/RepositoryModule.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/ui/composer/SendButton.kt` |
| 修改 | `app/src/main/java/com/sebastian/android/ui/composer/Composer.kt` |

---

## Task 1：修复 @IoDispatcher 默认值 + activeSessionId null（M-9, M-11）

**影响：** Hilt 注入语义错误；SessionPanel 无法高亮当前会话。  
**Files:**
- Modify: `viewmodel/SessionViewModel.kt:27`
- Modify: `viewmodel/SubAgentViewModel.kt:38`
- Modify: `viewmodel/ProviderFormViewModel.kt:31`
- Modify: `ui/chat/ChatScreen.kt:165`

- [ ] **Step 1：移除 SessionViewModel 中的默认值**

```kotlin
// viewmodel/SessionViewModel.kt — 第 25-28 行
@HiltViewModel
class SessionViewModel @Inject constructor(
    private val repository: SessionRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,  // 删除 = Dispatchers.IO
) : ViewModel() {
```

同时删除不再使用的 import（如文件顶部有 `import kotlinx.coroutines.Dispatchers` 且仅用于此处，则删除）。

- [ ] **Step 2：移除 SubAgentViewModel 中的默认值**

```kotlin
// viewmodel/SubAgentViewModel.kt — 第 35-39 行
@HiltViewModel
class SubAgentViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val apiService: ApiService,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,  // 删除 = Dispatchers.IO
) : ViewModel() {
```

删除文件顶部 `import kotlinx.coroutines.Dispatchers`（此 import 仅用于默认值）。

- [ ] **Step 3：移除 ProviderFormViewModel 中的默认值**

```kotlin
// viewmodel/ProviderFormViewModel.kt — 第 29-32 行
@HiltViewModel
class ProviderFormViewModel @Inject constructor(
    private val repository: SettingsRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,  // 删除 = Dispatchers.IO
) : ViewModel() {
```

删除文件顶部 `import kotlinx.coroutines.Dispatchers`。

- [ ] **Step 4：修复 SessionPanel activeSessionId**

```kotlin
// ui/chat/ChatScreen.kt — supportingPane 内的 SessionPanel 调用，约第 163-175 行
SessionPanel(
    sessions = sessionState.sessions,
    activeSessionId = chatState.activeSessionId,   // 原为 null，改为传入真实值
    onSessionClick = { session ->
        chatViewModel.switchSession(session.id)
        scope.launch {
            navigator.navigateTo(SupportingPaneScaffoldRole.Main)
        }
    },
    onNewSession = sessionViewModel::createSession,
    onNavigateToSettings = { navController.navigate(Route.Settings) { launchSingleTop = true } },
    onNavigateToSubAgents = { navController.navigate(Route.SubAgents) { launchSingleTop = true } },
)
```

- [ ] **Step 5：验证构建通过**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL，无编译错误。

- [ ] **Step 6：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/viewmodel/SessionViewModel.kt \
        app/src/main/java/com/sebastian/android/viewmodel/SubAgentViewModel.kt \
        app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt \
        app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "fix(android): 移除 @IoDispatcher 默认值，修复 activeSessionId null

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2：创建 AgentRepository，消除 SubAgentViewModel 架构违规（C-2）

**影响：** SubAgentViewModel 直接注入并调用 ApiService，绕过 Repository 层，且在 ViewModel 内做 JSON 解析。  
**Files:**
- Create: `data/model/AgentInfo.kt`
- Create: `data/repository/AgentRepository.kt`
- Create: `data/repository/AgentRepositoryImpl.kt`
- Modify: `di/RepositoryModule.kt`
- Modify: `viewmodel/SubAgentViewModel.kt`

- [ ] **Step 1：将 AgentInfo 从 ViewModel 迁移到 data/model 层**

新建文件 `data/model/AgentInfo.kt`：

```kotlin
package com.sebastian.android.data.model

data class AgentInfo(
    val agentType: String,
    val name: String,
    val description: String,
    val isActive: Boolean,
)
```

- [ ] **Step 2：创建 AgentRepository 接口**

新建文件 `data/repository/AgentRepository.kt`：

```kotlin
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo

interface AgentRepository {
    suspend fun getAgents(): Result<List<AgentInfo>>
}
```

- [ ] **Step 3：创建 AgentRepositoryImpl**

新建文件 `data/repository/AgentRepositoryImpl.kt`：

```kotlin
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AgentRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : AgentRepository {

    override suspend fun getAgents(): Result<List<AgentInfo>> = runCatching {
        withContext(dispatcher) {
            apiService.getAgents()
                .map { map ->
                    AgentInfo(
                        agentType = map["agent_type"]?.toString() ?: "",
                        name = map["name"]?.toString() ?: "",
                        description = map["description"]?.toString() ?: "",
                        isActive = map["is_active"] as? Boolean ?: false,
                    )
                }
                .filter { it.agentType.isNotEmpty() }
        }
    }
}
```

- [ ] **Step 4：在 RepositoryModule 注册 AgentRepository**

修改 `di/RepositoryModule.kt`，在现有绑定后追加：

```kotlin
package com.sebastian.android.di

import com.sebastian.android.data.repository.*
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    @Binds @Singleton
    abstract fun bindSettingsRepository(impl: SettingsRepositoryImpl): SettingsRepository

    @Binds @Singleton
    abstract fun bindChatRepository(impl: ChatRepositoryImpl): ChatRepository

    @Binds @Singleton
    abstract fun bindSessionRepository(impl: SessionRepositoryImpl): SessionRepository

    @Binds @Singleton
    abstract fun bindAgentRepository(impl: AgentRepositoryImpl): AgentRepository  // 新增
}
```

- [ ] **Step 5：重写 SubAgentViewModel，移除 ApiService 直接依赖**

用以下内容完整替换 `viewmodel/SubAgentViewModel.kt`：

```kotlin
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Session
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SubAgentUiState(
    val agents: List<AgentInfo> = emptyList(),
    val agentSessions: List<Session> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SubAgentViewModel @Inject constructor(
    private val agentRepository: AgentRepository,
    private val sessionRepository: SessionRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SubAgentUiState())
    val uiState: StateFlow<SubAgentUiState> = _uiState.asStateFlow()

    fun loadAgents() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            agentRepository.getAgents()
                .onSuccess { agents ->
                    _uiState.update { it.copy(isLoading = false, agents = agents) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun loadAgentSessions(agentType: String) {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            sessionRepository.getAgentSessions(agentType)
                .onSuccess { sessions ->
                    _uiState.update { it.copy(isLoading = false, agentSessions = sessions) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}
```

- [ ] **Step 6：更新 AgentListScreen 的 AgentInfo import（若有直接引用）**

检查 `ui/subagents/AgentListScreen.kt` 是否有 `import com.sebastian.android.viewmodel.AgentInfo`，若有，改为：

```kotlin
import com.sebastian.android.data.model.AgentInfo
```

- [ ] **Step 7：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL。

- [ ] **Step 8：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt \
        app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt \
        app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt \
        app/src/main/java/com/sebastian/android/di/RepositoryModule.kt \
        app/src/main/java/com/sebastian/android/viewmodel/SubAgentViewModel.kt \
        app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt
git commit -m "feat(android): 新增 AgentRepository，消除 SubAgentViewModel 直接调 ApiService

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3：SettingsRepository currentProvider + SettingsRepositoryImpl dispatcher（M-8, M-12）

**影响：** 「当前激活 Provider」过滤逻辑泄漏到 ChatScreen UI 层；SettingsRepositoryImpl 硬编码 Dispatchers.IO 而非注入。  
**Files:**
- Modify: `data/repository/SettingsRepository.kt`
- Modify: `data/repository/SettingsRepositoryImpl.kt`
- Modify: `viewmodel/SettingsViewModel.kt`

- [ ] **Step 1：在 SettingsRepository 接口加 currentProvider**

```kotlin
// data/repository/SettingsRepository.kt — 完整替换
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Provider
import kotlinx.coroutines.flow.Flow

interface SettingsRepository {
    val serverUrl: Flow<String>
    val theme: Flow<String>
    val currentProvider: Flow<Provider?>          // 新增：当前激活 Provider
    suspend fun saveServerUrl(url: String)
    suspend fun saveTheme(theme: String)
    fun providersFlow(): Flow<List<Provider>>
    suspend fun getProviders(): Result<List<Provider>>
    suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider>
    suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider>
    suspend fun deleteProvider(id: String): Result<Unit>
    suspend fun setDefaultProvider(id: String): Result<Unit>
    suspend fun testConnection(url: String): Result<Unit>
}
```

- [ ] **Step 2：在 SettingsRepositoryImpl 实现 currentProvider + 注入 dispatcher**

```kotlin
// data/repository/SettingsRepositoryImpl.kt — 完整替换
package com.sebastian.android.data.repository

import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.ProviderDto
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SettingsRepositoryImpl @Inject constructor(
    private val dataStore: SettingsDataStore,
    private val apiService: ApiService,
    private val okHttpClient: OkHttpClient,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,   // 新增：替换硬编码
) : SettingsRepository {

    override val serverUrl: Flow<String> = dataStore.serverUrl
    override val theme: Flow<String> = dataStore.theme

    private val _providers = MutableStateFlow<List<Provider>>(emptyList())

    override fun providersFlow(): Flow<List<Provider>> = _providers.asStateFlow()

    override val currentProvider: Flow<Provider?> = _providers.map { list ->
        list.firstOrNull { it.isDefault }
    }

    override suspend fun saveServerUrl(url: String) = dataStore.saveServerUrl(url)
    override suspend fun saveTheme(theme: String) = dataStore.saveTheme(theme)

    override suspend fun getProviders(): Result<List<Provider>> = runCatching {
        val dtos = apiService.getProviders()
        val providers = dtos.map { it.toDomain() }
        _providers.value = providers
        providers
    }

    override suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider> = runCatching {
        val dto = apiService.createProvider(ProviderDto(name = name, type = type, baseUrl = baseUrl, apiKey = apiKey))
        val provider = dto.toDomain()
        _providers.value = _providers.value + provider
        provider
    }

    override suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider> = runCatching {
        val dto = apiService.updateProvider(id, ProviderDto(name = name, type = type, baseUrl = baseUrl, apiKey = apiKey))
        val provider = dto.toDomain()
        _providers.value = _providers.value.map { if (it.id == id) provider else it }
        provider
    }

    override suspend fun deleteProvider(id: String): Result<Unit> = runCatching {
        apiService.deleteProvider(id)
        _providers.value = _providers.value.filter { it.id != id }
    }

    override suspend fun setDefaultProvider(id: String): Result<Unit> = runCatching {
        apiService.setDefaultProvider(id)
        _providers.value = _providers.value.map { it.copy(isDefault = it.id == id) }
        dataStore.saveActiveProviderId(id)
    }

    override suspend fun testConnection(url: String): Result<Unit> = runCatching {
        withContext(dispatcher) {                               // 原为硬编码 Dispatchers.IO
            val trimmed = url.trimEnd('/')
            val response = okHttpClient.newCall(
                Request.Builder().url("$trimmed/api/v1/health").build()
            ).execute()
            response.use {
                if (!it.isSuccessful) throw Exception("HTTP ${it.code}")
            }
        }
    }
}
```

- [ ] **Step 3：在 SettingsUiState 加 currentProvider，更新 combine**

```kotlin
// viewmodel/SettingsViewModel.kt — 修改 SettingsUiState 和 init 块

data class SettingsUiState(
    val serverUrl: String = "",
    val theme: String = "system",
    val providers: List<Provider> = emptyList(),
    val currentProvider: Provider? = null,         // 新增
    val isLoading: Boolean = false,
    val error: String? = null,
    val connectionTestResult: ConnectionTestResult? = null,
)

// init 块中将 combine 改为 4 个 Flow：
init {
    viewModelScope.launch {
        combine(
            repository.serverUrl,
            repository.theme,
            repository.providersFlow(),
            repository.currentProvider,
        ) { url, theme, providers, currentProvider ->
            _uiState.update {
                it.copy(
                    serverUrl = url,
                    theme = theme,
                    providers = providers,
                    currentProvider = currentProvider,
                )
            }
        }.collect {}
    }
    loadProviders()
}
```

- [ ] **Step 4：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 5：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt \
        app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt \
        app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt
git commit -m "feat(android): SettingsRepository 暴露 currentProvider Flow，修复 dispatcher 注入

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4：扩展 ChatUiState + 创建 ErrorBanner（M-4, M-5, M-10 前置）

**影响：** 为后续 Task 5/6/7 提供所需的状态字段和 UI 组件。  
**Files:**
- Modify: `viewmodel/ChatViewModel.kt` — ChatUiState 定义
- Create: `ui/common/ErrorBanner.kt`

- [ ] **Step 1：在 ChatUiState 追加三个字段**

找到 `viewmodel/ChatViewModel.kt` 中的 `ChatUiState` 数据类（约第 41-51 行），替换为：

```kotlin
data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeThinkingEffort: ThinkingEffort = ThinkingEffort.AUTO,
    val activeSessionId: String = "main",
    val isOffline: Boolean = false,
    val isServerNotConfigured: Boolean = false,   // 新增：serverUrl 为空时显示配置提示
    val connectionFailed: Boolean = false,        // 新增：SSE 重试耗尽时显示失败提示
    val flushTick: Long = 0L,                     // 新增：每次 delta flush 后递增，驱动 MessageList 滚动
    val pendingApprovals: List<PendingApproval> = emptyList(),
    val error: String? = null,
)
```

- [ ] **Step 2：创建 ErrorBanner 通用组件**

新建文件 `ui/common/ErrorBanner.kt`：

```kotlin
package com.sebastian.android.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun ErrorBanner(
    message: String,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer)
            .padding(horizontal = 12.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onErrorContainer,
            modifier = Modifier.weight(1f),
        )
        if (actionLabel != null && onAction != null) {
            TextButton(onClick = onAction) {
                Text(actionLabel, color = MaterialTheme.colorScheme.onErrorContainer)
            }
        }
    }
}
```

- [ ] **Step 3：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 4：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        app/src/main/java/com/sebastian/android/ui/common/ErrorBanner.kt
git commit -m "feat(android): 扩展 ChatUiState（flushTick/isServerNotConfigured/connectionFailed）+ ErrorBanner

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5：ChatViewModel 修复集合（M-1, M-3, M-4, M-6, M-10）

**影响：** 修复 5 处独立问题：delta 并发丢失（两个竞态窗口）、Last-Event-ID 策略、SSE 失败状态管理、cancelTurn 无超时、baseUrl 为空无提示。  
**Files:**
- Modify: `viewmodel/ChatViewModel.kt`

以下所有修改均在同一文件内，最后统一提交。

- [ ] **Step 1：修复 startDeltaFlusher — 原子 remove + flushTick 递增（M-1 Bug 1）**

将 `startDeltaFlusher` 函数（约第 76-102 行）替换为：

```kotlin
private fun startDeltaFlusher() {
    viewModelScope.launch(dispatcher) {
        while (true) {
            delay(50L)
            // 用 remove() 原子取出每个 blockId 的 delta，避免 snapshot+clear() 的竞态窗口
            val snapshot = pendingDeltas.keys.toList().mapNotNull { key ->
                pendingDeltas.remove(key)?.toString()?.let { key to it }
            }
            if (snapshot.isEmpty()) continue
            val msgId = currentAssistantMessageId ?: continue
            _uiState.update { state ->
                state.copy(
                    messages = state.messages.map { msg ->
                        if (msg.id != msgId) return@map msg
                        msg.copy(
                            blocks = msg.blocks.map { block ->
                                val pending = snapshot.find { it.first == block.blockId }
                                    ?: return@map block
                                if (block is ContentBlock.TextBlock)
                                    block.copy(text = block.text + pending.second)
                                else block
                            },
                        )
                    },
                    flushTick = state.flushTick + 1,   // 通知 MessageList 有新内容
                )
            }
        }
    }
}
```

- [ ] **Step 2：修复 TextBlockStop — 先 drain pending 再解析（M-1 Bug 2）**

将 `TextBlockStop` 分支（约第 171-187 行）替换为：

```kotlin
is StreamEvent.TextBlockStop -> {
    viewModelScope.launch(dispatcher) {
        val msgId = currentAssistantMessageId ?: return@launch
        // 先原子取出该 block 尚未 flush 的 delta，避免解析时丢失最后一批字符
        val pendingText = pendingDeltas.remove(event.blockId)?.toString() ?: ""
        val rawText = (_uiState.value.messages
            .find { it.id == msgId }
            ?.blocks?.find { it.blockId == event.blockId }
            ?.let { (it as? ContentBlock.TextBlock)?.text } ?: "") + pendingText
        val rendered = withContext(dispatcher) {
            markdownParser.parse(rawText)
        }
        updateBlockInCurrentMessage(event.blockId) { existing ->
            if (existing is ContentBlock.TextBlock)
                existing.copy(done = true, renderedMarkdown = rendered)
            else existing
        }
    }
}
```

- [ ] **Step 3：修复 switchSession — 清理 pendingDeltas（M-1 内存泄漏）**

在 `switchSession` 函数的 `sseJob?.cancel()` 之后加一行：

```kotlin
fun switchSession(sessionId: String) {
    sseJob?.cancel()
    sseJob = null
    currentAssistantMessageId = null
    pendingTurnSessionId = null
    pendingDeltas.clear()            // 新增：切换会话时清理旧会话的残留 delta
    _uiState.update {
        it.copy(
            activeSessionId = sessionId,
            messages = emptyList(),
            composerState = ComposerState.IDLE_EMPTY,
            agentAnimState = AgentAnimState.IDLE,
            pendingApprovals = emptyList(),
        )
    }
    // ... 后续不变
}
```

- [ ] **Step 4：添加 determineLastEventId 方法（M-3）**

在 ViewModel 的 private helpers 区域添加：

```kotlin
/**
 * 根据当前消息列表的最后一条消息决定 SSE 连接时的 Last-Event-ID：
 * - 空列表或最后消息为 USER（进行中会话）→ "0"，请求全量回放
 * - 最后消息为 ASSISTANT（已完成会话）→ ""，只订阅新事件
 */
private fun determineLastEventId(): String {
    val lastMessage = _uiState.value.messages.lastOrNull() ?: return "0"
    return when (lastMessage.role) {
        MessageRole.USER -> "0"
        MessageRole.ASSISTANT -> ""
        else -> "0"
    }
}
```

- [ ] **Step 5：重写 startSseCollection — baseUrl 检查 + lastEventId + connectionFailed（M-3, M-4, M-10）**

将 `startSseCollection` 函数（约第 115-127 行）替换为：

```kotlin
private fun startSseCollection() {
    sseJob = viewModelScope.launch(dispatcher) {
        val baseUrl = settingsRepository.serverUrl.first()
        if (baseUrl.isEmpty()) {
            _uiState.update { it.copy(isServerNotConfigured = true) }
            return@launch
        }
        _uiState.update { it.copy(isServerNotConfigured = false, connectionFailed = false) }
        val sessionId = _uiState.value.activeSessionId
        val lastEventId = determineLastEventId()
        try {
            chatRepository.sessionStream(baseUrl, sessionId, lastEventId).collect { event ->
                handleEvent(event)
            }
        } catch (e: Exception) {
            // 只有非网络断开原因导致的失败才标记 connectionFailed
            // 网络断开由 NetworkMonitor 通过 isOffline 处理
            if (!_uiState.value.isOffline) {
                _uiState.update { it.copy(connectionFailed = true) }
            }
        }
    }
}
```

- [ ] **Step 6：更新 observeNetwork — 网络恢复时清除 connectionFailed（M-4）**

将 `observeNetwork` 函数（约第 104-113 行）替换为：

```kotlin
private fun observeNetwork() {
    viewModelScope.launch(dispatcher) {
        networkMonitor.isOnline.collect { isOnline ->
            _uiState.update { it.copy(isOffline = !isOnline) }
            if (isOnline) {
                _uiState.update { it.copy(connectionFailed = false) }  // 网络恢复清除失败状态
                if (sseJob?.isActive != true) {
                    startSseCollection()
                }
            }
        }
    }
}
```

- [ ] **Step 7：添加 retryConnection 公开方法（M-4）**

在 Public mutation surface 区域（`cancelTurn` 之后）添加：

```kotlin
fun retryConnection() {
    _uiState.update { it.copy(connectionFailed = false) }
    startSseCollection()
}
```

- [ ] **Step 8：修复 cancelTurn — 添加 5 秒超时保护（M-6）**

将 `cancelTurn` 函数替换为：

```kotlin
fun cancelTurn() {
    _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
    viewModelScope.launch(dispatcher) {
        withTimeoutOrNull(5_000L) {
            chatRepository.cancelTurn(_uiState.value.activeSessionId)
        } ?: _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY) }
    }
}
```

在文件顶部追加 import：`import kotlinx.coroutines.withTimeoutOrNull`

- [ ] **Step 9：为关键逻辑编写单元测试**

在 `app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelDeltaTest.kt` 创建：

```kotlin
package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.util.concurrent.ConcurrentHashMap

/**
 * 验证 pendingDeltas 的原子 remove 行为：
 * 取出后原始 map 中不再有该 key。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DeltaAtomicRemoveTest {

    @Test
    fun `remove returns value and clears key atomically`() {
        val map = ConcurrentHashMap<String, StringBuilder>()
        map.getOrPut("block1") { StringBuilder() }.append("hello")
        map.getOrPut("block1") { StringBuilder() }.append(" world")

        val snapshot = map.keys.toList().mapNotNull { key ->
            map.remove(key)?.toString()?.let { key to it }
        }

        assertEquals(1, snapshot.size)
        assertEquals("block1" to "hello world", snapshot[0])
        assertFalse(map.containsKey("block1"))
    }

    @Test
    fun `remove on absent key returns null without throwing`() {
        val map = ConcurrentHashMap<String, StringBuilder>()
        val result = map.remove("nonexistent")
        assertEquals(null, result)
    }
}
```

- [ ] **Step 10：运行单元测试**

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest \
    --tests "com.sebastian.android.viewmodel.DeltaAtomicRemoveTest"
```

预期：2 tests passed。

- [ ] **Step 11：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 12：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt \
        app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelDeltaTest.kt
git commit -m "fix(android): 修复 delta 竞态丢失、Last-Event-ID 策略、SSE 失败状态、cancelTurn 超时

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6：滚动跟随修复 — 去振荡 + flushTick 驱动（M-2, M-5）

**影响：** 程序触发的 scrollToItem 被 isScrollInProgress 误判为用户操作导致 FOLLOWING→DETACHED 振荡；长消息流式时 delta flush 更新文字但列表不自动下滚。  
**Files:**
- Modify: `ui/chat/MessageList.kt`

- [ ] **Step 1：重写 MessageList.kt**

用以下内容完整替换 `ui/chat/MessageList.kt`：

```kotlin
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Message
import com.sebastian.android.viewmodel.ScrollFollowState
import kotlinx.coroutines.launch

@Composable
fun MessageList(
    messages: List<Message>,
    scrollFollowState: ScrollFollowState,
    flushTick: Long,                    // 每次 delta flush 后递增，通知列表滚动
    onUserScrolled: () -> Unit,
    onScrolledNearBottom: () -> Unit,
    onScrolledToBottom: () -> Unit,
    onScrollToBottom: () -> Unit,
    onToggleThinking: (String) -> Unit,
    onToggleTool: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    val isNearBottom by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val lastVisible = info.visibleItemsInfo.lastOrNull() ?: return@derivedStateOf true
            lastVisible.index >= info.totalItemsCount - 2
        }
    }

    val showFab by remember {
        derivedStateOf { scrollFollowState == ScrollFollowState.DETACHED }
    }

    // 精确检测用户拖动手势，避免程序触发的 scrollToItem 被误判
    // DragInteraction.Start 只在真实触摸拖动时触发，程序滚动不触发
    LaunchedEffect(Unit) {
        listState.interactionSource.interactions.collect { interaction ->
            if (interaction is DragInteraction.Start &&
                scrollFollowState == ScrollFollowState.FOLLOWING
            ) {
                onUserScrolled()
            }
        }
    }

    // 接近底部时恢复 FOLLOWING
    LaunchedEffect(isNearBottom) {
        if (isNearBottom) {
            onScrolledToBottom()
        } else if (scrollFollowState == ScrollFollowState.NEAR_BOTTOM) {
            onScrolledNearBottom()
        }
    }

    // 三个触发条件：消息数量变化 / block 数量变化 / delta flush（flushTick）
    // 只在 FOLLOWING 状态下自动下滚，DETACHED 时不触发
    LaunchedEffect(messages.size, messages.lastOrNull()?.blocks?.size, flushTick) {
        if (scrollFollowState == ScrollFollowState.FOLLOWING && messages.isNotEmpty()) {
            listState.scrollToItem(messages.size - 1)
        }
    }

    Box(modifier = modifier) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
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

        AnimatedVisibility(
            visible = showFab,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(16.dp),
        ) {
            SmallFloatingActionButton(
                onClick = {
                    scope.launch {
                        listState.animateScrollToItem(
                            index = (messages.size - 1).coerceAtLeast(0)
                        )
                    }
                    onScrollToBottom()
                }
            ) {
                Icon(Icons.Default.KeyboardArrowDown, contentDescription = "回到底部")
            }
        }
    }
}
```

- [ ] **Step 2：更新 ChatScreen 传入 flushTick**

在 `ui/chat/ChatScreen.kt` 的 `MessageList(...)` 调用处追加 `flushTick` 参数：

```kotlin
MessageList(
    messages = chatState.messages,
    scrollFollowState = chatState.scrollFollowState,
    flushTick = chatState.flushTick,              // 新增
    onUserScrolled = chatViewModel::onUserScrolled,
    onScrolledNearBottom = chatViewModel::onScrolledNearBottom,
    onScrolledToBottom = chatViewModel::onScrolledToBottom,
    onScrollToBottom = chatViewModel::onScrolledToBottom,
    onToggleThinking = chatViewModel::toggleThinkingBlock,
    onToggleTool = chatViewModel::toggleToolBlock,
    modifier = Modifier.weight(1f),
)
```

- [ ] **Step 3：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 4：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt \
        app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "fix(android): 修复滚动跟随振荡，flushTick 驱动长消息自动下滚

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7：ChatScreen UI 更新 — Banner 三态 + currentProvider（M-4, M-8）

**影响：** 离线/未配置/连接失败三种状态显示错误或缺失；Provider 过滤逻辑从 UI 层下沉到 ViewModel。  
**Files:**
- Modify: `ui/chat/ChatScreen.kt`

- [ ] **Step 1：将 settingsViewModel.uiState collectAsState 提升到顶层**

在 `ChatScreen` composable 函数顶部（`chatState`/`sessionState` 之后），将原来放在 `Scaffold content` 内部的 collect 提升出来：

```kotlin
@OptIn(ExperimentalMaterial3AdaptiveApi::class, ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    navController: NavController,
    chatViewModel: ChatViewModel = hiltViewModel(),
    sessionViewModel: SessionViewModel = hiltViewModel(),
    settingsViewModel: SettingsViewModel = hiltViewModel(),
) {
    val chatState by chatViewModel.uiState.collectAsState()
    val sessionState by sessionViewModel.uiState.collectAsState()
    val settingsState by settingsViewModel.uiState.collectAsState()  // 提升到顶层
    val navigator = rememberSupportingPaneScaffoldNavigator<Nothing>()
    val scope = rememberCoroutineScope()
    // ...
```

- [ ] **Step 2：替换单一离线 Banner 为三态 Banner**

将 `AnimatedVisibility(visible = chatState.isOffline)` 及其内部 Box 替换为：

```kotlin
// 未配置服务器地址
AnimatedVisibility(visible = chatState.isServerNotConfigured) {
    ErrorBanner(message = "请先在设置中配置服务器地址")
}
// 网络断开
AnimatedVisibility(visible = chatState.isOffline && !chatState.isServerNotConfigured) {
    ErrorBanner(message = "网络已断开，重连中…")
}
// SSE 连接耗尽（非网络断开，非未配置）
AnimatedVisibility(
    visible = chatState.connectionFailed &&
        !chatState.isOffline &&
        !chatState.isServerNotConfigured
) {
    ErrorBanner(
        message = "连接失败，请检查服务器地址",
        actionLabel = "重试",
        onAction = chatViewModel::retryConnection,
    )
}
```

在文件顶部追加 import：
```kotlin
import com.sebastian.android.ui.common.ErrorBanner
```

- [ ] **Step 3：Composer activeProvider 改用 settingsState.currentProvider**

找到 Composer 调用处，将：
```kotlin
val providers by settingsViewModel.uiState.collectAsState()   // 删除这行（已提升到顶层）

Composer(
    ...
    activeProvider = providers.providers.firstOrNull { it.isDefault },  // 改为：
    ...
)
```
改为：
```kotlin
Composer(
    state = chatState.composerState,
    activeProvider = settingsState.currentProvider,       // 直接使用 ViewModel 已计算的值
    effort = chatState.activeThinkingEffort,
    onEffortChange = chatViewModel::setEffort,
    onSend = chatViewModel::sendMessage,
    onStop = chatViewModel::cancelTurn,
)
```

- [ ] **Step 4：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 5：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "fix(android): ChatScreen 三态 Banner，currentProvider 从 ViewModel 读取

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8：SendButton 预留 onLongPress 参数（M-7）

**影响：** Phase 3 接入全双工语音时不需要修改 Composer 接口，符合 spec 插槽架构约定。  
**Files:**
- Modify: `ui/composer/SendButton.kt`
- Modify: `ui/composer/Composer.kt`

- [ ] **Step 1：重写 SendButton，用 Surface + combinedClickable 替换 FilledIconButton**

用以下内容完整替换 `ui/composer/SendButton.kt`：

```kotlin
package com.sebastian.android.ui.composer

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.sebastian.android.ui.common.AnimationTokens
import com.sebastian.android.viewmodel.ComposerState

/**
 * 发送 / 停止 按钮
 *
 * | state       | 外观                      | 可点击 |
 * |-------------|--------------------------|-------|
 * | IDLE_EMPTY  | 灰色发送图标（禁用）         | 否    |
 * | IDLE_READY  | 激活色发送图标              | 是    |
 * | SENDING     | CircularProgressIndicator | 否    |
 * | STREAMING   | 停止图标 ■                 | 是    |
 * | CANCELLING  | CircularProgressIndicator | 否    |
 *
 * [onLongPress] Phase 3 预留：全双工语音入口，默认 null（不注册长按手势）。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SendButton(
    state: ComposerState,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onLongPress: (() -> Unit)? = null,    // Phase 3：语音全双工入口
    modifier: Modifier = Modifier,
) {
    val isEnabled = state == ComposerState.IDLE_READY || state == ComposerState.STREAMING
    val containerColor = if (state == ComposerState.IDLE_EMPTY)
        MaterialTheme.colorScheme.surfaceVariant
    else
        MaterialTheme.colorScheme.primary

    val onClick: () -> Unit = when (state) {
        ComposerState.IDLE_READY -> onSend
        ComposerState.STREAMING -> onStop
        else -> { {} }
    }

    Surface(
        shape = CircleShape,
        color = containerColor,
        modifier = modifier.size(44.dp),
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .fillMaxSize()
                .combinedClickable(
                    enabled = isEnabled,
                    onClick = onClick,
                    onLongClick = onLongPress,
                ),
        ) {
            AnimatedContent(
                targetState = state,
                transitionSpec = {
                    fadeIn(tween(AnimationTokens.STATE_TRANSITION_DURATION_MS)) togetherWith
                        fadeOut(tween(AnimationTokens.STATE_TRANSITION_DURATION_MS))
                },
                label = "send_button_state",
            ) { targetState ->
                when (targetState) {
                    ComposerState.IDLE_EMPTY, ComposerState.IDLE_READY -> Icon(
                        imageVector = Icons.Default.Send,
                        contentDescription = "发送",
                        tint = if (state == ComposerState.IDLE_EMPTY)
                            MaterialTheme.colorScheme.onSurfaceVariant
                        else
                            MaterialTheme.colorScheme.onPrimary,
                    )
                    ComposerState.STREAMING -> Icon(
                        imageVector = Icons.Default.Stop,
                        contentDescription = "停止",
                        tint = MaterialTheme.colorScheme.onPrimary,
                    )
                    ComposerState.SENDING, ComposerState.CANCELLING -> CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                }
            }
        }
    }
}
```

- [ ] **Step 2：Composer 透传 onLongPress（保持默认 null，接口不破坏）**

在 `ui/composer/Composer.kt` 的 `SendButton(...)` 调用处加一行（参数已有默认值，不传也不报错）：

```kotlin
SendButton(
    state = effectiveState,
    onSend = {
        val msg = text.trim()
        if (msg.isNotEmpty()) {
            text = ""
            onSend(msg)
        }
    },
    onStop = onStop,
    // onLongPress = null  // Phase 3 注入时在此传入回调，Composer 签名无需修改
)
```

此步骤实际上无需修改代码（默认值已处理），仅作确认。

- [ ] **Step 3：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 4：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/ui/composer/SendButton.kt
git commit -m "feat(android): SendButton 预留 onLongPress Phase 3 语音入口

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9：Composer attachmentPreviewSlot 用 AnimatedVisibility 包裹（Minor）

**影响：** Phase 2 接入附件时预览区有平滑展开动画，而不是瞬显/瞬消。  
**Files:**
- Modify: `ui/composer/Composer.kt`

- [ ] **Step 1：用 AnimatedVisibility 包裹 attachmentPreviewSlot**

找到 `ui/composer/Composer.kt` 中（约第 66-69 行）：

```kotlin
// 修改前
attachmentPreviewSlot?.let {
    it()
}

// 修改后
AnimatedVisibility(visible = attachmentPreviewSlot != null) {
    attachmentPreviewSlot?.invoke()
}
```

在文件顶部确认或追加 import：
```kotlin
import androidx.compose.animation.AnimatedVisibility
```

- [ ] **Step 2：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

- [ ] **Step 3：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/ui/composer/Composer.kt
git commit -m "fix(android): attachmentPreviewSlot 用 AnimatedVisibility 包裹，Phase 2 动画预备

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 完成验收

所有 Task 完成后运行完整测试套件，确认无回归：

```bash
cd ui/mobile-android && ./gradlew :app:testDebugUnitTest && ./gradlew :app:assembleDebug
```

**修复清单确认：**

| Issue | Task | 状态 |
|-------|------|------|
| M-9：@IoDispatcher 默认值 | Task 1 | ✅ |
| M-11：activeSessionId null | Task 1 | ✅ |
| C-2：SubAgentViewModel 架构违规 | Task 2 | ✅ |
| M-8：currentProvider 泄漏到 UI | Task 3 | ✅ |
| M-12：SettingsRepositoryImpl dispatcher 硬编码 | Task 3 | ✅ |
| M-1：delta 并发丢失（两处竞态） | Task 5 | ✅ |
| M-3：Last-Event-ID 策略未实现 | Task 5 | ✅ |
| M-4：SSE 耗尽后误显"重连中" | Task 5, 7 | ✅ |
| M-6：cancelTurn 无超时保护 | Task 5 | ✅ |
| M-10：baseUrl 为空误显离线 | Task 5, 7 | ✅ |
| M-2：滚动跟随振荡 | Task 6 | ✅ |
| M-5：长消息不自动下滚 | Task 6 | ✅ |
| M-7：SendButton 缺 onLongPress | Task 8 | ✅ |
| Minor：attachmentPreviewSlot 无动画 | Task 9 | ✅ |

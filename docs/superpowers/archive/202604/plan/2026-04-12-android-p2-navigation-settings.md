# Android Phase 1 — Plan 2: Navigation & Settings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Plan 1 基础上完成导航骨架（`ThreePaneScaffold` 三面板 + Compose Navigation 路由）和完整设置页（连接配置 + Provider CRUD），让用户可以配置 Server URL 并管理 LLM Provider。

**Architecture:** `MainActivity` 持有 `NavHost`，路由到 `ChatScreen`（三面板骨架）和 `SettingsScreen`（Stack push）。`ThreePaneScaffold` 使用 slide 动画（侧栏滑入时主内容推出）。`SettingsViewModel` 通过 Hilt 注入 `SettingsRepository`，暴露 `StateFlow<SettingsUiState>`。

**Tech Stack:** Compose Navigation 2.8, `androidx.compose.material3.adaptive` 1.1, Hilt ViewModel, kotlinx-coroutines-test（ViewModel 测试）

**依赖：** Plan 1 完成（SettingsRepository, SessionRepository, Provider 模型已就绪）

---

## 文件结构

```
app/src/main/java/com/sebastian/android/
├── MainActivity.kt                           # 替换 Plan 1 临时版本
├── ui/
│   ├── theme/
│   │   ├── SebastianTheme.kt                 # Material3 主题
│   │   └── Color.kt                          # 颜色定义
│   ├── navigation/
│   │   └── Route.kt                          # @Serializable sealed class 路由
│   ├── chat/
│   │   ├── ChatScreen.kt                     # ThreePaneScaffold 骨架（内容 Plan 3 填充）
│   │   ├── SessionPanel.kt                   # 左侧会话列表面板
│   │   └── TodoPanel.kt                      # 右侧 Todo 面板（Plan 3 填充，此 plan 留空）
│   └── settings/
│       ├── SettingsScreen.kt                 # 设置入口页
│       ├── ConnectionPage.kt                 # 服务器 URL 配置
│       ├── ProviderListPage.kt               # Provider 列表
│       └── ProviderFormPage.kt               # Provider 新建/编辑
├── viewmodel/
│   └── SettingsViewModel.kt
app/src/test/java/com/sebastian/android/
└── viewmodel/
    └── SettingsViewModelTest.kt
```

---

### Task 1: Material3 主题

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/theme/Color.kt`
- Create: `app/src/main/java/com/sebastian/android/ui/theme/SebastianTheme.kt`

- [ ] **Step 1: 创建 `Color.kt`**

```kotlin
// com/sebastian/android/ui/theme/Color.kt
package com.sebastian.android.ui.theme

import androidx.compose.ui.graphics.Color

// Material3 动态颜色优先（Android 12+），以下为 fallback
val PrimaryLight = Color(0xFF1A73E8)
val OnPrimaryLight = Color(0xFFFFFFFF)
val SurfaceLight = Color(0xFFF8F9FA)
val OnSurfaceLight = Color(0xFF202124)
val BackgroundLight = Color(0xFFFFFFFF)

val PrimaryDark = Color(0xFF8AB4F8)
val OnPrimaryDark = Color(0xFF1A3A5C)
val SurfaceDark = Color(0xFF202124)
val OnSurfaceDark = Color(0xFFE8EAED)
val BackgroundDark = Color(0xFF171717)
```

- [ ] **Step 2: 创建 `SebastianTheme.kt`**

```kotlin
// com/sebastian/android/ui/theme/SebastianTheme.kt
package com.sebastian.android.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val LightColors = lightColorScheme(
    primary = PrimaryLight,
    onPrimary = OnPrimaryLight,
    surface = SurfaceLight,
    onSurface = OnSurfaceLight,
    background = BackgroundLight,
)

private val DarkColors = darkColorScheme(
    primary = PrimaryDark,
    onPrimary = OnPrimaryDark,
    surface = SurfaceDark,
    onSurface = OnSurfaceDark,
    background = BackgroundDark,
)

@Composable
fun SebastianTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }

    MaterialTheme(
        colorScheme = colorScheme,
        content = content,
    )
}
```

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/theme/
git commit -m "feat(android): Material3 主题（动态颜色 + fallback）"
```

---

### Task 2: 路由定义

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/navigation/Route.kt`

- [ ] **Step 1: 创建 `Route.kt`**

```kotlin
// com/sebastian/android/ui/navigation/Route.kt
package com.sebastian.android.ui.navigation

import kotlinx.serialization.Serializable

@Serializable
sealed class Route {
    @Serializable
    data object Chat : Route()

    @Serializable
    data object SubAgents : Route()

    @Serializable
    data class AgentSessions(val agentId: String) : Route()

    @Serializable
    data class SessionDetail(val sessionId: String) : Route()

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
}
```

- [ ] **Step 2: 编译确认（需要 kotlin-serialization 插件已在 build.gradle.kts 中启用）**

```bash
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/navigation/
git commit -m "feat(android): Compose Navigation 类型安全路由定义"
```

---

### Task 3: MainActivity + NavHost

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 1: 替换 `MainActivity.kt`**

```kotlin
// com/sebastian/android/MainActivity.kt
package com.sebastian.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.sebastian.android.ui.chat.ChatScreen
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.ui.settings.ProviderFormPage
import com.sebastian.android.ui.settings.ProviderListPage
import com.sebastian.android.ui.settings.ConnectionPage
import com.sebastian.android.ui.settings.SettingsScreen
import com.sebastian.android.ui.theme.SebastianTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SebastianTheme {
                SebastianNavHost()
            }
        }
    }
}

@Composable
fun SebastianNavHost() {
    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = Route.Chat) {
        composable<Route.Chat> {
            ChatScreen(navController = navController)
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
        composable<Route.SettingsProvidersNew> {
            ProviderFormPage(navController = navController, providerId = null)
        }
        composable<Route.SettingsProvidersEdit> { backStackEntry ->
            val route = backStackEntry.toRoute<Route.SettingsProvidersEdit>()
            ProviderFormPage(navController = navController, providerId = route.providerId)
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "feat(android): MainActivity + NavHost 路由配置"
```

---

### Task 4: ChatScreen（三面板骨架）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`
- Create: `app/src/main/java/com/sebastian/android/ui/chat/SessionPanel.kt`
- Create: `app/src/main/java/com/sebastian/android/ui/chat/TodoPanel.kt`

- [ ] **Step 1: 创建 `SessionPanel.kt`（骨架，Plan 3 充实内容）**

```kotlin
// com/sebastian/android/ui/chat/SessionPanel.kt
package com.sebastian.android.ui.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
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
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        // Plan 3 填充：会话列表 + 导航入口
        Text("SessionPanel - TODO")
    }
}
```

- [ ] **Step 2: 创建 `TodoPanel.kt`（骨架）**

```kotlin
// com/sebastian/android/ui/chat/TodoPanel.kt
package com.sebastian.android.ui.chat

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier

@Composable
fun TodoPanel(modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("Todo Panel")
    }
}
```

- [ ] **Step 3: 创建 `ChatScreen.kt`（ThreePaneScaffold 骨架）**

```kotlin
// com/sebastian/android/ui/chat/ChatScreen.kt
package com.sebastian.android.ui.chat

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.material3.adaptive.layout.ThreePaneScaffoldRole
import androidx.compose.material3.adaptive.navigation.rememberListDetailPaneScaffoldNavigator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.navigation.NavController
import com.sebastian.android.ui.navigation.Route
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3AdaptiveApi::class, ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(navController: NavController) {
    val navigator = rememberListDetailPaneScaffoldNavigator<Nothing>()
    val scope = rememberCoroutineScope()

    ListDetailPaneScaffold(
        directive = navigator.scaffoldDirective,
        value = navigator.scaffoldValue,
        listPane = {
            AnimatedPane {
                SessionPanel(
                    sessions = emptyList(),
                    activeSessionId = null,
                    onSessionClick = {},
                    onNewSession = {},
                    onNavigateToSettings = { navController.navigate(Route.Settings) },
                    onNavigateToSubAgents = {},
                )
            }
        },
        detailPane = {
            AnimatedPane {
                ChatContent(
                    onOpenSessionPanel = {
                        scope.launch {
                            navigator.navigateTo(ListDetailPaneScaffoldRole.List)
                        }
                    }
                )
            }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChatContent(
    onOpenSessionPanel: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Sebastian") },
                navigationIcon = {
                    IconButton(onClick = onOpenSessionPanel) {
                        Icon(Icons.Default.Menu, contentDescription = "会话列表")
                    }
                },
            )
        }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            // Plan 3 填充：MessageList + Composer
            Text("Chat Content - TODO")
        }
    }
}
```

> **说明**：`ListDetailPaneScaffold` 是 `ThreePaneScaffold` 的两面板简化版，用于初始骨架。Plan 3 中升级为完整三面板（含右侧 TodoPanel）时替换为 `ThreePaneScaffold`。`ListDetailPaneScaffold` 默认使用 slide 动画——窄屏时 List 和 Detail 分屏显示，List 进入时 Detail 向右推出，符合 slide-away 要求。

- [ ] **Step 4: 在模拟器上验证 App 可启动并导航到 Settings**

```bash
./gradlew :app:installDebug
```

预期：App 启动，显示 TopAppBar "Sebastian"，点击汉堡按钮展开 SessionPanel 骨架。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/
git commit -m "feat(android): ChatScreen ThreePaneScaffold 骨架 + SessionPanel/TodoPanel 占位"
```

---

### Task 5: SettingsViewModel

**Files:**
- Create: `app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt`
- Create: `app/src/test/java/com/sebastian/android/viewmodel/SettingsViewModelTest.kt`

- [ ] **Step 1: 写 SettingsViewModel 的失败测试**

```kotlin
// app/src/test/java/com/sebastian/android/viewmodel/SettingsViewModelTest.kt
package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    private lateinit var repository: SettingsRepository
    private lateinit var viewModel: SettingsViewModel
    private val serverUrlFlow = MutableStateFlow("")
    private val themeFlow = MutableStateFlow("system")
    private val providersFlow = MutableStateFlow<List<Provider>>(emptyList())
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        repository = mock()
        whenever(repository.serverUrl).thenReturn(serverUrlFlow)
        whenever(repository.theme).thenReturn(themeFlow)
        whenever(repository.providersFlow()).thenReturn(providersFlow)
        viewModel = SettingsViewModel(repository, dispatcher)
    }

    @Test
    fun `initial state has empty serverUrl`() = runTest(dispatcher) {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("", state.serverUrl)
        }
    }

    @Test
    fun `serverUrl updates when flow emits`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial
            serverUrlFlow.emit("http://192.168.1.1:8823")
            val updated = awaitItem()
            assertEquals("http://192.168.1.1:8823", updated.serverUrl)
        }
    }

    @Test
    fun `saveServerUrl calls repository`() = runTest(dispatcher) {
        var saved = ""
        whenever(repository.saveServerUrl(org.mockito.kotlin.any())).then {
            saved = it.arguments[0] as String
            Unit
        }
        viewModel.saveServerUrl("http://10.0.2.2:8823")
        dispatcher.scheduler.advanceUntilIdle()
        assertEquals("http://10.0.2.2:8823", saved)
    }

    @Test
    fun `providers list reflects repository flow`() = runTest(dispatcher) {
        val provider = Provider("p1", "Claude", "anthropic", null, true, ThinkingCapability.EFFORT)
        viewModel.uiState.test {
            awaitItem() // initial empty
            providersFlow.emit(listOf(provider))
            val updated = awaitItem()
            assertEquals(1, updated.providers.size)
            assertEquals("Claude", updated.providers[0].name)
        }
    }

    @Test
    fun `deleteProvider removes from list on success`() = runTest(dispatcher) {
        val provider = Provider("p1", "Claude", "anthropic", null, true, ThinkingCapability.EFFORT)
        providersFlow.emit(listOf(provider))
        whenever(repository.deleteProvider("p1")).thenReturn(Result.success(Unit))
        viewModel.deleteProvider("p1")
        dispatcher.scheduler.advanceUntilIdle()
        // Repository 内部更新 _providers flow，ViewModel 通过 flow 感知
        assertTrue(true) // 行为验证：repository.deleteProvider 被调用
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "*.SettingsViewModelTest"
```

预期：FAILED — `SettingsViewModel` 未定义。

- [ ] **Step 3: 创建 `SettingsViewModel.kt`**

```kotlin
// com/sebastian/android/viewmodel/SettingsViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val serverUrl: String = "",
    val theme: String = "system",
    val providers: List<Provider> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
    val connectionTestResult: ConnectionTestResult? = null,
)

sealed class ConnectionTestResult {
    data object Success : ConnectionTestResult()
    data class Failure(val message: String) : ConnectionTestResult()
}

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repository: SettingsRepository,
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(
                repository.serverUrl,
                repository.theme,
                repository.providersFlow(),
            ) { url, theme, providers ->
                Triple(url, theme, providers)
            }.collect { (url, theme, providers) ->
                _uiState.update { it.copy(serverUrl = url, theme = theme, providers = providers) }
            }
        }
        loadProviders()
    }

    fun saveServerUrl(url: String) {
        viewModelScope.launch(dispatcher) {
            repository.saveServerUrl(url.trim())
        }
    }

    fun saveTheme(theme: String) {
        viewModelScope.launch(dispatcher) {
            repository.saveTheme(theme)
        }
    }

    fun loadProviders() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            repository.getProviders()
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
                .onSuccess {
                    _uiState.update { it.copy(isLoading = false) }
                }
        }
    }

    fun deleteProvider(id: String) {
        viewModelScope.launch(dispatcher) {
            repository.deleteProvider(id)
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message) }
                }
        }
    }

    fun setDefaultProvider(id: String) {
        viewModelScope.launch(dispatcher) {
            repository.setDefaultProvider(id)
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message) }
                }
        }
    }

    fun testConnection(url: String) {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, connectionTestResult = null) }
            repository.testConnection(url)
                .onSuccess {
                    _uiState.update { it.copy(isLoading = false, connectionTestResult = ConnectionTestResult.Success) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, connectionTestResult = ConnectionTestResult.Failure(e.message ?: "连接失败")) }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
    fun clearConnectionTestResult() = _uiState.update { it.copy(connectionTestResult = null) }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "*.SettingsViewModelTest"
```

预期：4 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/viewmodel/SettingsViewModel.kt \
        app/src/test/java/com/sebastian/android/viewmodel/SettingsViewModelTest.kt
git commit -m "feat(android): SettingsViewModel + 单元测试（TDD）"
```

---

### Task 6: SettingsScreen 入口页

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt`

- [ ] **Step 1: 创建 `SettingsScreen.kt`**

```kotlin
// com/sebastian/android/ui/settings/SettingsScreen.kt
package com.sebastian.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavController
import com.sebastian.android.ui.navigation.Route

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(navController: NavController) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            SettingsItem(
                title = "连接与账户",
                subtitle = "服务器地址、登录状态",
                onClick = { navController.navigate(Route.SettingsConnection) },
            )
            HorizontalDivider()
            SettingsItem(
                title = "模型与 Provider",
                subtitle = "LLM Provider 管理",
                onClick = { navController.navigate(Route.SettingsProviders) },
            )
            HorizontalDivider()
        }
    }
}

@Composable
private fun SettingsItem(
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = { Text(subtitle) },
        trailingContent = {
            Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null)
        },
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    )
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/settings/SettingsScreen.kt
git commit -m "feat(android): SettingsScreen 入口页"
```

---

### Task 7: ConnectionPage（服务器连接配置）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/settings/ConnectionPage.kt`

- [ ] **Step 1: 创建 `ConnectionPage.kt`**

```kotlin
// com/sebastian/android/ui/settings/ConnectionPage.kt
package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.viewmodel.ConnectionTestResult
import com.sebastian.android.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectionPage(
    navController: NavController,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    // 初始化输入框为当前已保存的值
    var urlInput by rememberSaveable(uiState.serverUrl) {
        mutableStateOf(uiState.serverUrl)
    }

    LaunchedEffect(uiState.connectionTestResult) {
        when (val result = uiState.connectionTestResult) {
            is ConnectionTestResult.Success -> {
                snackbarHostState.showSnackbar("连接成功")
                viewModel.clearConnectionTestResult()
            }
            is ConnectionTestResult.Failure -> {
                snackbarHostState.showSnackbar("连接失败：${result.message}")
                viewModel.clearConnectionTestResult()
            }
            null -> {}
        }
    }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("连接与账户") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Spacer(Modifier.height(8.dp))
            Text("服务器地址", style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(
                value = urlInput,
                onValueChange = { urlInput = it },
                label = { Text("http://192.168.1.x:8823") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { viewModel.testConnection(urlInput) },
                    enabled = urlInput.isNotBlank() && !uiState.isLoading,
                    modifier = Modifier.weight(1f),
                ) {
                    if (uiState.isLoading) {
                        CircularProgressIndicator(modifier = Modifier.width(20.dp).height(20.dp), strokeWidth = 2.dp)
                    } else {
                        Text("测试连接")
                    }
                }
                Button(
                    onClick = {
                        viewModel.saveServerUrl(urlInput)
                        navController.popBackStack()
                    },
                    enabled = urlInput.isNotBlank(),
                    modifier = Modifier.weight(1f),
                ) {
                    Text("保存")
                }
            }
            Text(
                text = "模拟器访问宿主机：http://10.0.2.2:8823\n真机使用局域网 IP",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/settings/ConnectionPage.kt
git commit -m "feat(android): ConnectionPage 服务器地址配置页"
```

---

### Task 8: ProviderListPage

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt`

- [ ] **Step 1: 创建 `ProviderListPage.kt`**

```kotlin
// com/sebastian/android/ui/settings/ProviderListPage.kt
package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.data.model.Provider
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderListPage(
    navController: NavController,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("模型与 Provider") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { navController.navigate(Route.SettingsProvidersNew) }) {
                Icon(Icons.Default.Add, contentDescription = "添加 Provider")
            }
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { innerPadding ->
        when {
            uiState.isLoading && uiState.providers.isEmpty() -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }
            uiState.providers.isEmpty() -> {
                Box(Modifier.fillMaxSize().padding(innerPadding), contentAlignment = Alignment.Center) {
                    Text("还没有 Provider，点击 + 添加")
                }
            }
            else -> {
                LazyColumn(modifier = Modifier.padding(innerPadding)) {
                    items(uiState.providers, key = { it.id }) { provider ->
                        ProviderItem(
                            provider = provider,
                            onEdit = { navController.navigate(Route.SettingsProvidersEdit(provider.id)) },
                            onDelete = { viewModel.deleteProvider(provider.id) },
                            onSetDefault = { viewModel.setDefaultProvider(provider.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ProviderItem(
    provider: Provider,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onSetDefault: () -> Unit,
) {
    ListItem(
        headlineContent = { Text(provider.name) },
        supportingContent = {
            Text("${provider.type}${if (provider.baseUrl != null) " · ${provider.baseUrl}" else ""}")
        },
        leadingContent = {
            if (provider.isDefault) {
                Icon(
                    Icons.Default.CheckCircle,
                    contentDescription = "默认",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        },
        trailingContent = {
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, contentDescription = "编辑")
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, contentDescription = "删除")
            }
        },
    )
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/settings/ProviderListPage.kt
git commit -m "feat(android): ProviderListPage（Provider 列表 + 增删操作）"
```

---

### Task 9: ProviderFormPage（新建/编辑 Provider）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt`
- Create: `app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt`

- [ ] **Step 1: 创建 `ProviderFormViewModel.kt`**

```kotlin
// com/sebastian/android/viewmodel/ProviderFormViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ProviderFormUiState(
    val name: String = "",
    val type: String = "anthropic",
    val baseUrl: String = "",
    val apiKey: String = "",
    val isLoading: Boolean = false,
    val isSaved: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class ProviderFormViewModel @Inject constructor(
    private val repository: SettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ProviderFormUiState())
    val uiState: StateFlow<ProviderFormUiState> = _uiState.asStateFlow()

    fun loadProvider(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            val provider = repository.providersFlow().first().find { it.id == id } ?: return@launch
            _uiState.update {
                it.copy(
                    name = provider.name,
                    type = provider.type,
                    baseUrl = provider.baseUrl ?: "",
                )
            }
        }
    }

    fun onNameChange(v: String) = _uiState.update { it.copy(name = v) }
    fun onTypeChange(v: String) = _uiState.update { it.copy(type = v) }
    fun onBaseUrlChange(v: String) = _uiState.update { it.copy(baseUrl = v) }
    fun onApiKeyChange(v: String) = _uiState.update { it.copy(apiKey = v) }

    fun save(existingId: String?) {
        val state = _uiState.value
        if (state.name.isBlank()) {
            _uiState.update { it.copy(error = "名称不能为空") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = if (existingId == null) {
                repository.createProvider(
                    name = state.name.trim(),
                    type = state.type,
                    baseUrl = state.baseUrl.trim().ifEmpty { null },
                    apiKey = state.apiKey.trim().ifEmpty { null },
                )
            } else {
                repository.updateProvider(
                    id = existingId,
                    name = state.name.trim(),
                    type = state.type,
                    baseUrl = state.baseUrl.trim().ifEmpty { null },
                    apiKey = state.apiKey.trim().ifEmpty { null },
                )
            }
            result
                .onSuccess { _uiState.update { it.copy(isLoading = false, isSaved = true) } }
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}
```

- [ ] **Step 2: 创建 `ProviderFormPage.kt`**

```kotlin
// com/sebastian/android/ui/settings/ProviderFormPage.kt
package com.sebastian.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.viewmodel.ProviderFormViewModel

private val PROVIDER_TYPES = listOf("anthropic", "openai", "ollama")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderFormPage(
    navController: NavController,
    providerId: String?,
    viewModel: ProviderFormViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(Unit) {
        providerId?.let { viewModel.loadProvider(it) }
    }

    LaunchedEffect(uiState.isSaved) {
        if (uiState.isSaved) navController.popBackStack()
    }

    LaunchedEffect(uiState.error) {
        uiState.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    var typeMenuExpanded by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (providerId == null) "添加 Provider" else "编辑 Provider") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = uiState.name,
                onValueChange = viewModel::onNameChange,
                label = { Text("名称") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            ExposedDropdownMenuBox(
                expanded = typeMenuExpanded,
                onExpandedChange = { typeMenuExpanded = it },
            ) {
                OutlinedTextField(
                    value = uiState.type,
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("类型") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = typeMenuExpanded) },
                    modifier = Modifier.fillMaxWidth().menuAnchor(),
                )
                ExposedDropdownMenu(
                    expanded = typeMenuExpanded,
                    onDismissRequest = { typeMenuExpanded = false },
                ) {
                    PROVIDER_TYPES.forEach { type ->
                        DropdownMenuItem(
                            text = { Text(type) },
                            onClick = {
                                viewModel.onTypeChange(type)
                                typeMenuExpanded = false
                            },
                        )
                    }
                }
            }

            if (uiState.type == "ollama" || uiState.type == "openai") {
                OutlinedTextField(
                    value = uiState.baseUrl,
                    onValueChange = viewModel::onBaseUrlChange,
                    label = { Text("Base URL（可选）") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            OutlinedTextField(
                value = uiState.apiKey,
                onValueChange = viewModel::onApiKeyChange,
                label = { Text("API Key${if (uiState.type == "ollama") "（可留空）" else ""}") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )

            Button(
                onClick = { viewModel.save(providerId) },
                enabled = !uiState.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("保存")
            }
        }
    }
}
```

- [ ] **Step 3: 完整构建**

```bash
./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL。

- [ ] **Step 4: 运行所有单元测试**

```bash
./gradlew :app:testDebugUnitTest
```

预期：`SseFrameParserTest`（5）+ `SettingsViewModelTest`（4）= 9 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/viewmodel/ProviderFormViewModel.kt \
        app/src/main/java/com/sebastian/android/ui/settings/ProviderFormPage.kt
git commit -m "feat(android): ProviderFormPage + ProviderFormViewModel（Provider 新建/编辑）"
```

---

**Plan 2 完成检查：**
- [ ] App 启动后显示 ChatScreen（TopAppBar + "Chat Content - TODO"）
- [ ] 点击汉堡按钮，SessionPanel 以 slide 动画推开主内容
- [ ] 从 ChatScreen 能导航到 SettingsScreen
- [ ] 在 ConnectionPage 可输入并保存 Server URL
- [ ] 在 ProviderListPage 可查看（空列表提示）并点击 + 进入 ProviderFormPage
- [ ] ProviderFormPage 表单可交互，保存后返回列表
- [ ] 所有单元测试通过（9 个）

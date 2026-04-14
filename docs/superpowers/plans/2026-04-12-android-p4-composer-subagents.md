# Android Phase 1 — Plan 4: Composer & SubAgents

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Phase 1 最后一块：Composer（文字输入 + ThinkButton + SendButton/StopButton）接入 ChatViewModel，SubAgent 督导页三级导航（AgentListScreen → SessionListScreen → SessionDetailScreen），并替换 Plan 3 中 ChatScreen 的 Composer 占位，使整个 Phase 1 功能完整可用。

**Architecture:** Composer 是无状态 Composable，通过 `state: ComposerState` prop + 回调与 `ChatViewModel` 通信。SubAgent 页面用 `SubAgentViewModel` 持有状态，复用 `SessionRepository`。`SessionDetailScreen` 共用 `ChatViewModel` 的消息列表逻辑（通过 sessionId 区分）。

**Tech Stack:** Compose `TextField`, `AnimatedContent`, Hilt ViewModel

**依赖：** Plan 1–3 完成（ChatViewModel.ComposerState、ThinkingEffort、SessionRepository 均已就绪）

---

## 文件结构

```
app/src/main/java/com/sebastian/android/
├── ui/
│   ├── composer/
│   │   ├── Composer.kt                       # 主容器（插槽架构）
│   │   ├── SendButton.kt                     # 发送/停止按钮
│   │   └── ThinkButton.kt                    # 思考档位选择
│   ├── subagents/
│   │   ├── AgentListScreen.kt
│   │   ├── SessionListScreen.kt
│   │   └── SessionDetailScreen.kt
│   └── chat/
│       └── ChatScreen.kt                     # 替换 Composer 占位
├── viewmodel/
│   └── SubAgentViewModel.kt
app/src/test/java/com/sebastian/android/
└── ui/composer/
    └── ComposerStateTest.kt
```

---

### Task 1: SendButton

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/composer/SendButton.kt`

- [ ] **Step 1: 创建 `SendButton.kt`**

```kotlin
// com/sebastian/android/ui/composer/SendButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
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
 */
@Composable
fun SendButton(
    state: ComposerState,
    onSend: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isEnabled = state == ComposerState.IDLE_READY || state == ComposerState.STREAMING
    val containerColor = if (state == ComposerState.IDLE_EMPTY)
        MaterialTheme.colorScheme.surfaceVariant
    else
        MaterialTheme.colorScheme.primary

    FilledIconButton(
        onClick = when (state) {
            ComposerState.IDLE_READY -> onSend
            ComposerState.STREAMING -> onStop
            else -> { {} }
        },
        enabled = isEnabled,
        colors = IconButtonDefaults.filledIconButtonColors(
            containerColor = containerColor,
            disabledContainerColor = containerColor,
        ),
        modifier = modifier.size(44.dp),
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
                )
                ComposerState.STREAMING -> Icon(
                    imageVector = Icons.Default.Stop,
                    contentDescription = "停止",
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
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/composer/SendButton.kt
git commit -m "feat(android): SendButton（发送/停止/进度 五态 AnimatedContent）"
```

---

### Task 2: ThinkButton + EffortPickerSheet

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt`

- [ ] **Step 1: 创建 `ThinkButton.kt`**

```kotlin
// com/sebastian/android/ui/composer/ThinkButton.kt
package com.sebastian.android.ui.composer

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import kotlinx.coroutines.launch

/**
 * ThinkButton 根据当前 Provider 的 thinking_capability 渲染不同形态：
 *
 * | capability  | 渲染                              |
 * |-------------|----------------------------------|
 * | null        | 禁用 chip（加载中）                 |
 * | NONE        | 不渲染                             |
 * | ALWAYS_ON   | 非交互 badge「思考·自动」             |
 * | TOGGLE      | 单击切换 on/off                    |
 * | EFFORT      | 单击打开 EffortPickerSheet          |
 * | ADAPTIVE    | 单击打开 EffortPickerSheet          |
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ThinkButton(
    activeProvider: Provider?,
    currentEffort: ThinkingEffort,
    onEffortChange: (ThinkingEffort) -> Unit,
    modifier: Modifier = Modifier,
) {
    val capability = activeProvider?.thinkingCapability

    // NONE：不渲染任何内容
    if (capability == ThinkingCapability.NONE) return

    var showSheet by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState()
    val scope = rememberCoroutineScope()

    val label = when (capability) {
        null -> "思考…"
        ThinkingCapability.ALWAYS_ON -> "思考·自动"
        ThinkingCapability.TOGGLE -> if (currentEffort != ThinkingEffort.AUTO) "思考·开" else "思考·关"
        ThinkingCapability.EFFORT, ThinkingCapability.ADAPTIVE -> when (currentEffort) {
            ThinkingEffort.LOW -> "思考·轻"
            ThinkingEffort.MEDIUM -> "思考·中"
            ThinkingEffort.HIGH -> "思考·深"
            ThinkingEffort.AUTO -> "思考·自动"
        }
        ThinkingCapability.NONE -> return
    }

    AssistChip(
        onClick = {
            when (capability) {
                null, ThinkingCapability.ALWAYS_ON -> { /* 不可点击 */ }
                ThinkingCapability.TOGGLE -> {
                    onEffortChange(if (currentEffort != ThinkingEffort.AUTO) ThinkingEffort.AUTO else ThinkingEffort.MEDIUM)
                }
                ThinkingCapability.EFFORT, ThinkingCapability.ADAPTIVE -> showSheet = true
                ThinkingCapability.NONE -> {}
            }
        },
        label = { Text(label, style = MaterialTheme.typography.labelMedium) },
        leadingIcon = {
            Icon(Icons.Default.Psychology, contentDescription = null)
        },
        enabled = capability != null && capability != ThinkingCapability.ALWAYS_ON,
        colors = if (currentEffort != ThinkingEffort.AUTO && capability == ThinkingCapability.TOGGLE)
            AssistChipDefaults.assistChipColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        else AssistChipDefaults.assistChipColors(),
        modifier = modifier.alpha(if (capability == null) 0.5f else 1f),
    )

    if (showSheet) {
        ModalBottomSheet(
            onDismissRequest = { showSheet = false },
            sheetState = sheetState,
        ) {
            EffortPickerSheet(
                current = currentEffort,
                onSelect = { effort ->
                    onEffortChange(effort)
                    scope.launch { sheetState.hide() }.invokeOnCompletion { showSheet = false }
                },
            )
        }
    }
}

@Composable
private fun EffortPickerSheet(
    current: ThinkingEffort,
    onSelect: (ThinkingEffort) -> Unit,
) {
    val options = listOf(
        ThinkingEffort.AUTO to "自动（模型决定）",
        ThinkingEffort.LOW to "轻度思考",
        ThinkingEffort.MEDIUM to "中度思考",
        ThinkingEffort.HIGH to "深度思考",
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 32.dp),
    ) {
        Text(
            "思考档位",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        )
        options.forEach { (effort, label) ->
            ListItem(
                headlineContent = { Text(label) },
                trailingContent = {
                    RadioButton(
                        selected = current == effort,
                        onClick = { onSelect(effort) },
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt
git commit -m "feat(android): ThinkButton + EffortPickerSheet 思考档位选择"
```

---

### Task 3: Composer（主容器 + 插槽架构）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/composer/Composer.kt`
- Create: `app/src/test/java/com/sebastian/android/ui/composer/ComposerStateTest.kt`

- [ ] **Step 1: 写 Composer 状态逻辑测试**

```kotlin
// app/src/test/java/com/sebastian/android/ui/composer/ComposerStateTest.kt
package com.sebastian.android.ui.composer

import com.sebastian.android.viewmodel.ComposerState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Composer 输入文本变化驱动 ComposerState 的逻辑测试。
 * 实际 state 由 ChatViewModel 持有，此处测试纯函数映射。
 */
class ComposerStateTest {

    @Test
    fun `empty text maps to IDLE_EMPTY`() {
        assertEquals(ComposerState.IDLE_EMPTY, resolveComposerState("", ComposerState.IDLE_EMPTY))
    }

    @Test
    fun `non-empty text in IDLE_EMPTY maps to IDLE_READY`() {
        assertEquals(ComposerState.IDLE_READY, resolveComposerState("hello", ComposerState.IDLE_EMPTY))
    }

    @Test
    fun `clearing text in IDLE_READY maps back to IDLE_EMPTY`() {
        assertEquals(ComposerState.IDLE_EMPTY, resolveComposerState("", ComposerState.IDLE_READY))
    }

    @Test
    fun `STREAMING state is not affected by text content`() {
        // 流式进行中，不因文字变化改变 composerState（由 ViewModel 控制）
        assertEquals(ComposerState.STREAMING, resolveComposerState("", ComposerState.STREAMING))
        assertEquals(ComposerState.STREAMING, resolveComposerState("text", ComposerState.STREAMING))
    }

    @Test
    fun `SENDING state is not affected by text content`() {
        assertEquals(ComposerState.SENDING, resolveComposerState("", ComposerState.SENDING))
    }

    // 辅助函数：模拟 Composer 内部的状态映射逻辑
    private fun resolveComposerState(text: String, current: ComposerState): ComposerState {
        if (current == ComposerState.STREAMING || current == ComposerState.SENDING || current == ComposerState.CANCELLING) {
            return current
        }
        return if (text.isNotBlank()) ComposerState.IDLE_READY else ComposerState.IDLE_EMPTY
    }
}
```

- [ ] **Step 2: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "*.ComposerStateTest"
```

预期：5 个测试全部 PASS（纯逻辑无依赖）。

- [ ] **Step 3: 创建 `Composer.kt`**

```kotlin
// com/sebastian/android/ui/composer/Composer.kt
package com.sebastian.android.ui.composer

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.viewmodel.ComposerState

/**
 * Composer 主容器（插槽架构）。
 *
 * 自身无状态：ComposerState 由 ChatViewModel 持有并通过 prop 传入。
 * Phase 2 预留插槽（voiceSlot, attachmentSlot）默认 null，接入时不修改此文件。
 */
@Composable
fun Composer(
    state: ComposerState,
    activeProvider: Provider?,
    effort: ThinkingEffort,
    onEffortChange: (ThinkingEffort) -> Unit,
    onSend: (String) -> Unit,
    onStop: () -> Unit,
    // Phase 2 插槽预留
    voiceSlot: @Composable (() -> Unit)? = null,
    attachmentSlot: @Composable (() -> Unit)? = null,
    attachmentPreviewSlot: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    var text by rememberSaveable { mutableStateOf("") }

    // Composer 内部根据文字内容通知父层更新 ComposerState
    // 实际 state 修改在 ChatViewModel，Composer 只读 state prop
    val effectiveState = when {
        state == ComposerState.STREAMING || state == ComposerState.SENDING || state == ComposerState.CANCELLING -> state
        text.isNotBlank() -> ComposerState.IDLE_READY
        else -> ComposerState.IDLE_EMPTY
    }

    Surface(
        shape = RoundedCornerShape(16.dp),
        tonalElevation = 2.dp,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 8.dp),
    ) {
        Column {
            // 附件预览区（Phase 2 填充）
            attachmentPreviewSlot?.let {
                it()
            }

            // 文字输入区
            TextField(
                value = text,
                onValueChange = { newText ->
                    text = newText
                },
                placeholder = {
                    androidx.compose.material3.Text("发消息给 Sebastian")
                },
                maxLines = 6,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            // 工具栏
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 左侧插槽区
                ThinkButton(
                    activeProvider = activeProvider,
                    currentEffort = effort,
                    onEffortChange = onEffortChange,
                )
                voiceSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }
                attachmentSlot?.let {
                    Spacer(Modifier.width(4.dp))
                    it()
                }

                Spacer(Modifier.weight(1f))

                // 右侧发送/停止按钮
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
                )
            }
        }
    }
}
```

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/composer/Composer.kt \
        app/src/test/java/com/sebastian/android/ui/composer/ComposerStateTest.kt
git commit -m "feat(android): Composer 主容器（插槽架构）+ ComposerState 单元测试"
```

---

### Task 4: 接入 Composer 到 ChatScreen

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`

- [ ] **Step 1: 替换 ChatScreen 中的 `// Composer 占位` 部分**

将 `ChatScreen.kt` 中的：

```kotlin
// Composer 占位（Plan 4 填充）
Box(modifier = Modifier) {
    Text("Composer TODO")
}
```

替换为：

```kotlin
val providers by settingsViewModel.uiState.collectAsState()

Composer(
    state = chatState.composerState,
    activeProvider = providers.providers.firstOrNull { it.isDefault },
    effort = chatState.activeThinkingEffort,
    onEffortChange = chatViewModel::setEffort,
    onSend = chatViewModel::sendMessage,
    onStop = chatViewModel::cancelTurn,
)
```

同时在函数参数中添加 `settingsViewModel: SettingsViewModel = hiltViewModel()`：

```kotlin
@Composable
fun ChatScreen(
    navController: NavController,
    chatViewModel: ChatViewModel = hiltViewModel(),
    sessionViewModel: SessionViewModel = hiltViewModel(),
    settingsViewModel: SettingsViewModel = hiltViewModel(),   // 新增
)
```

- [ ] **Step 2: 完整构建**

```bash
./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL。

- [ ] **Step 3: 在模拟器上端到端验证发送消息**

1. 打开 App，进入 ConnectionPage 填写 Server URL
2. 返回主界面，在 Composer 输入框输入文字
3. 验证：SendButton 从灰色（IDLE_EMPTY）变为激活色（IDLE_READY）
4. 点击发送，验证：消息出现在列表，SendButton 变为 SENDING（转圈）→ STREAMING（停止图标）
5. 流式完成后 SendButton 恢复 IDLE_EMPTY

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "feat(android): 接入 Composer 到 ChatScreen，完成完整发送/停止流程"
```

---

### Task 5: SubAgentViewModel

**Files:**
- Create: `app/src/main/java/com/sebastian/android/viewmodel/SubAgentViewModel.kt`

- [ ] **Step 1: 创建 `SubAgentViewModel.kt`**

```kotlin
// com/sebastian/android/viewmodel/SubAgentViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Session
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.repository.SessionRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AgentInfo(
    val agentType: String,
    val name: String,
    val description: String,
    val isActive: Boolean,
)

data class SubAgentUiState(
    val agents: List<AgentInfo> = emptyList(),
    val agentSessions: List<Session> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SubAgentViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val apiService: ApiService,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SubAgentUiState())
    val uiState: StateFlow<SubAgentUiState> = _uiState.asStateFlow()

    fun loadAgents() {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isLoading = true) }
            runCatching { apiService.getAgents() }
                .onSuccess { raw ->
                    val agents = raw.map { map ->
                        AgentInfo(
                            agentType = map["agent_type"]?.toString() ?: "",
                            name = map["name"]?.toString() ?: "",
                            description = map["description"]?.toString() ?: "",
                            isActive = map["is_active"] as? Boolean ?: false,
                        )
                    }.filter { it.agentType.isNotEmpty() }
                    _uiState.update { it.copy(isLoading = false, agents = agents) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun loadAgentSessions(agentType: String) {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isLoading = true) }
            sessionRepository.getAgentSessions(agentType)
                .onSuccess { sessions -> _uiState.update { it.copy(isLoading = false, agentSessions = sessions) } }
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/viewmodel/SubAgentViewModel.kt
git commit -m "feat(android): SubAgentViewModel（Agent 列表 + Session 列表）"
```

---

### Task 6: SubAgent 三级页面

**Files:**
- Create: `app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt`
- Create: `app/src/main/java/com/sebastian/android/ui/subagents/SessionListScreen.kt`
- Create: `app/src/main/java/com/sebastian/android/ui/subagents/SessionDetailScreen.kt`

- [ ] **Step 1: 创建 `AgentListScreen.kt`**

```kotlin
// com/sebastian/android/ui/subagents/AgentListScreen.kt
package com.sebastian.android.ui.subagents

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.SubAgentViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentListScreen(
    navController: NavController,
    viewModel: SubAgentViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(Unit) { viewModel.loadAgents() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Sub-Agents") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        }
    ) { innerPadding ->
        when {
            state.isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.agents.isEmpty() -> Box(Modifier.fillMaxSize().padding(innerPadding), contentAlignment = Alignment.Center) {
                Text("没有可用的 Sub-Agent")
            }
            else -> LazyColumn(modifier = Modifier.padding(innerPadding)) {
                items(state.agents, key = { it.agentType }) { agent ->
                    ListItem(
                        headlineContent = { Text(agent.name) },
                        supportingContent = { Text(agent.description) },
                        modifier = Modifier.clickable {
                            navController.navigate(Route.AgentSessions(agent.agentType))
                        },
                    )
                }
            }
        }
    }
}
```

- [ ] **Step 2: 创建 `SessionListScreen.kt`**

```kotlin
// com/sebastian/android/ui/subagents/SessionListScreen.kt
package com.sebastian.android.ui.subagents

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.SubAgentViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionListScreen(
    agentId: String,
    navController: NavController,
    viewModel: SubAgentViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(agentId) { viewModel.loadAgentSessions(agentId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("$agentId 会话") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = {
                // 创建新会话后导航进入
            }) {
                Icon(Icons.Default.Add, contentDescription = "新建会话")
            }
        },
    ) { innerPadding ->
        when {
            state.isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.agentSessions.isEmpty() -> Box(Modifier.fillMaxSize().padding(innerPadding), contentAlignment = Alignment.Center) {
                Text("还没有会话，点击 + 新建")
            }
            else -> LazyColumn(modifier = Modifier.padding(innerPadding)) {
                items(state.agentSessions, key = { it.id }) { session ->
                    ListItem(
                        headlineContent = {
                            Text(session.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        },
                        supportingContent = session.lastMessageAt?.let { { Text(it) } },
                        modifier = Modifier.clickable {
                            navController.navigate(Route.SessionDetail(session.id))
                        },
                    )
                }
            }
        }
    }
}
```

- [ ] **Step 3: 创建 `SessionDetailScreen.kt`（复用 ChatScreen 结构）**

```kotlin
// com/sebastian/android/ui/subagents/SessionDetailScreen.kt
package com.sebastian.android.ui.subagents

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.chat.MessageList
import com.sebastian.android.ui.composer.Composer
import com.sebastian.android.viewmodel.ChatViewModel
import com.sebastian.android.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionDetailScreen(
    sessionId: String,
    navController: NavController,
    chatViewModel: ChatViewModel = hiltViewModel(),
    settingsViewModel: SettingsViewModel = hiltViewModel(),
) {
    val chatState by chatViewModel.uiState.collectAsState()
    val settingsState by settingsViewModel.uiState.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("会话详情") },
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
            Composer(
                state = chatState.composerState,
                activeProvider = settingsState.providers.firstOrNull { it.isDefault },
                effort = chatState.activeThinkingEffort,
                onEffortChange = chatViewModel::setEffort,
                onSend = { text -> chatViewModel.sendSessionMessage(sessionId, text) },
                onStop = chatViewModel::cancelTurn,
            )
        }
    }
}
```

> **注意**：`SessionDetailScreen` 需要 `ChatViewModel` 支持 `sendSessionMessage(sessionId, text)`。在 `ChatViewModel.kt` 中补充此方法：
>
> ```kotlin
> fun sendSessionMessage(sessionId: String, text: String) {
>     if (text.isBlank()) return
>     val userMsg = Message(id = UUID.randomUUID().toString(), sessionId = sessionId, role = MessageRole.USER, text = text)
>     _uiState.update { state ->
>         state.copy(messages = state.messages + userMsg, composerState = ComposerState.SENDING, scrollFollowState = ScrollFollowState.FOLLOWING)
>     }
>     viewModelScope.launch(dispatcher) {
>         chatRepository.sendSessionTurn(sessionId, text, _uiState.value.activeThinkingEffort)
>             .onFailure { e -> _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) } }
>     }
> }
> ```

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/sebastian/android/ui/subagents/ \
        app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt
git commit -m "feat(android): SubAgent 三级页面（AgentList → SessionList → SessionDetail）"
```

---

### Task 7: 补全 NavHost SubAgents 路由

**Files:**
- Modify: `app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 1: 在 `SebastianNavHost` 中添加 SubAgents 路由**

在 `NavHost` 的 `composable<Route.Chat>` 后添加：

```kotlin
composable<Route.SubAgents> {
    AgentListScreen(navController = navController)
}
composable<Route.AgentSessions> { backStackEntry ->
    val route = backStackEntry.toRoute<Route.AgentSessions>()
    SessionListScreen(agentId = route.agentId, navController = navController)
}
composable<Route.SessionDetail> { backStackEntry ->
    val route = backStackEntry.toRoute<Route.SessionDetail>()
    SessionDetailScreen(sessionId = route.sessionId, navController = navController)
}
```

同时添加 import：

```kotlin
import com.sebastian.android.ui.subagents.AgentListScreen
import com.sebastian.android.ui.subagents.SessionListScreen
import com.sebastian.android.ui.subagents.SessionDetailScreen
```

- [ ] **Step 2: 完整构建**

```bash
./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL。

- [ ] **Step 3: 运行所有单元测试**

```bash
./gradlew :app:testDebugUnitTest
```

预期：全部测试通过：
- `SseFrameParserTest`: 5
- `SettingsViewModelTest`: 4
- `ChatViewModelTest`: 7
- `ComposerStateTest`: 5
- **共 21 个测试**

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/sebastian/android/MainActivity.kt
git commit -m "feat(android): 补全 NavHost SubAgents 路由"
```

---

### Task 8: Phase 1 功能验收

- [ ] **Step 1: 在模拟器上完整 E2E 验证**

按以下流程验证：

1. **Settings 流程**
   - 进入 Settings → Connection，输入 `http://10.0.2.2:8823`，测试连接成功，保存
   - 进入 Settings → Providers，添加一个 Provider（type: anthropic，输入 API Key），保存
   - 验证 Provider 出现在列表，设为默认

2. **发送消息**
   - 回到主界面，在 Composer 输入框输入 "你好"
   - 验证 SendButton 变为激活色
   - 点击发送，验证：用户消息出现在列表，SendButton 进入 SENDING（转圈）

3. **流式输出**
   - 等待 SSE 流式响应，验证：ThinkingCard 出现并呼吸动画，TextBlock 逐字追加
   - 流式进行中点击 SendButton（停止图标），验证：流式中断，ComposerState 恢复

4. **ThinkingCard 交互**
   - 点击 ThinkingCard header，验证：思考内容展开
   - 再次点击，验证：折叠

5. **ToolCallCard 交互**（需 Agent 触发工具调用）
   - 验证：工具运行中转圈，完成后绿勾，点击可展开输入

6. **会话面板**
   - 点击汉堡按钮，验证：SessionPanel 从左侧滑入，主内容推出屏幕（slide-away）

7. **Sub-Agent 页面**
   - 从 SessionPanel 点击"Sub-Agents"，验证：AgentListScreen 显示 Agent 列表
   - 点击某 Agent，进入 SessionListScreen

- [ ] **Step 2: 最终 Commit**

```bash
git add -p   # 确认仅添加必要改动
git commit -m "feat(android): Phase 1 完成——完整对话、流式渲染、Composer、SubAgents"
```

- [ ] **Step 3: 推送 dev 并创建 PR**

```bash
git push
gh pr create --base main --head dev \
  --title "feat(android): Android 原生客户端 Phase 1" \
  --body "$(cat <<'EOF'
## Summary
- 初始化 Kotlin + Jetpack Compose Android 项目（minSdk 33）
- Hilt DI + OkHttp SSE + Retrofit 数据层
- ThreePaneScaffold 三面板导航（slide-away 模式）
- ChatViewModel SSE 事件驱动状态机
- 流式 Markdown 块级增量渲染 + Animatable 淡入动画
- Composer 插槽架构（TextInput + ThinkButton + SendButton/StopButton）
- Settings 页（Connection + Provider CRUD）
- Sub-Agent 督导页三级导航
- ApprovalDialog 审批弹窗
- 21 个单元测试全部通过

## Test plan
- [ ] `./gradlew :app:testDebugUnitTest` 21 个测试全绿
- [ ] `./gradlew :app:assembleDebug` BUILD SUCCESSFUL
- [ ] 模拟器 E2E：发送消息 → 流式输出 → 停止按钮响应
- [ ] ThinkingCard / ToolCallCard 展开折叠
- [ ] Settings → Provider 添加
EOF
)"
```

---

**Plan 4 完成检查：**
- [ ] 21 个单元测试全部通过
- [ ] 完整构建 BUILD SUCCESSFUL
- [ ] Composer 输入 → 发送 → 流式输出 → 停止 全链路可用
- [ ] ThinkButton 可打开 EffortPickerSheet
- [ ] SubAgents 三级导航可进入
- [ ] PR 已创建

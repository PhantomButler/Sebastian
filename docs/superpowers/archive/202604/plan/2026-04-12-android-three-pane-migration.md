# Android ThreePaneScaffold 迁移计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `ChatScreen` 的 `SupportingPaneScaffold` 迁移到 spec 规定的 `ThreePaneScaffold`，实现三面板 slide-away 推走动画（而非当前的遮罩覆盖），并正确配置面板语义角色。

**Architecture:** 改动集中在 `ChatScreen.kt` 一个文件。将 `SupportingPaneScaffoldNavigator` 替换为 `ThreePaneScaffoldNavigator`，面板参数名从 `mainPane/supportingPane/extraPane` 改为 `detailPane/listPane/extraPane`，加入 `paneMotion = ThreePaneScaffoldDefaults.slideMotion`。导航调用从 `SupportingPaneScaffoldRole.*` 改为 `ThreePaneScaffoldRole.*`。

**Tech Stack:** Kotlin + Jetpack Compose + `androidx.compose.material3.adaptive`（已在 build.gradle.kts 引入：`compose.material3.adaptive`、`compose.material3.adaptive.layout`、`compose.material3.adaptive.navigation`）

工作目录：`ui/mobile-android/`  
构建命令：`./gradlew :app:assembleDebug`

**注意：** 迁移后需在真机上人工验证以下场景：
1. 手机竖屏：左/右侧栏滑入时主内容同步推出屏幕（不是覆盖）
2. 手机横屏：同上，验证宽度不触发常驻模式（宽度 < 1000dp）
3. 平板横屏（≥1000dp）：左右面板常驻，三栏并排

---

## 文件结构

| 操作 | 路径 |
|------|------|
| 修改 | `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` |

---

## Task 1：迁移 ChatScreen 到 ThreePaneScaffold

**当前问题：**
- `SupportingPaneScaffold` 是两面板组件，第三个面板（会话列表）强行塞在非官方的 `Extra` slot
- 无法配置 `paneMotion`，侧栏打开时是覆盖主内容而非推走
- 面板语义错误：会话列表（应为 List）放在了 Supporting 角色

**Files:**
- Modify: `ui/chat/ChatScreen.kt`

- [ ] **Step 1：替换 import**

找到文件顶部以下三行 import，全部替换：

```kotlin
// 删除：
import androidx.compose.material3.adaptive.layout.SupportingPaneScaffold
import androidx.compose.material3.adaptive.layout.SupportingPaneScaffoldRole
import androidx.compose.material3.adaptive.navigation.rememberSupportingPaneScaffoldNavigator

// 替换为：
import androidx.compose.material3.adaptive.layout.ThreePaneScaffold
import androidx.compose.material3.adaptive.layout.ThreePaneScaffoldDefaults
import androidx.compose.material3.adaptive.layout.ThreePaneScaffoldRole
import androidx.compose.material3.adaptive.navigation.rememberThreePaneScaffoldNavigator
```

- [ ] **Step 2：替换 navigator 类型**

找到（约第 59 行）：
```kotlin
val navigator = rememberSupportingPaneScaffoldNavigator<Nothing>()
```
替换为：
```kotlin
val navigator = rememberThreePaneScaffoldNavigator<Nothing>()
```

- [ ] **Step 3：替换 SupportingPaneScaffold 为 ThreePaneScaffold**

将 `SupportingPaneScaffold(...)` 整块（约第 84-183 行）替换为以下结构：

```kotlin
ThreePaneScaffold(
    directive = navigator.scaffoldDirective,
    value = navigator.scaffoldValue,
    paneMotion = ThreePaneScaffoldDefaults.slideMotion,   // 侧栏入场时主内容同步推出
    listPane = {
        // 左侧：历史会话列表（原 supportingPane）
        AnimatedPane {
            SessionPanel(
                sessions = sessionState.sessions,
                activeSessionId = chatState.activeSessionId,
                onSessionClick = { session ->
                    chatViewModel.switchSession(session.id)
                    scope.launch {
                        navigator.navigateTo(ThreePaneScaffoldRole.Detail)
                    }
                },
                onNewSession = sessionViewModel::createSession,
                onNavigateToSettings = {
                    navController.navigate(Route.Settings) { launchSingleTop = true }
                },
                onNavigateToSubAgents = {
                    navController.navigate(Route.SubAgents) { launchSingleTop = true }
                },
            )
        }
    },
    detailPane = {
        // 中间：主对话区（原 mainPane）
        AnimatedPane {
            Scaffold(
                topBar = {
                    TopAppBar(
                        title = { Text("Sebastian") },
                        navigationIcon = {
                            IconButton(onClick = {
                                scope.launch {
                                    navigator.navigateTo(ThreePaneScaffoldRole.List)  // 原 Supporting
                                }
                            }) {
                                Icon(Icons.Default.Menu, contentDescription = "会话列表")
                            }
                        },
                        actions = {
                            IconButton(onClick = {
                                scope.launch {
                                    navigator.navigateTo(ThreePaneScaffoldRole.Extra)  // 同名
                                }
                            }) {
                                Icon(Icons.Default.Checklist, contentDescription = "待办事项")
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
                    // 三态 Banner（此处保持 Task 7 已有的 Banner 代码不变）
                    AnimatedVisibility(visible = chatState.isServerNotConfigured) {
                        ErrorBanner(message = "请先在设置中配置服务器地址")
                    }
                    AnimatedVisibility(visible = chatState.isOffline && !chatState.isServerNotConfigured) {
                        ErrorBanner(message = "网络已断开，重连中…")
                    }
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
                    MessageList(
                        messages = chatState.messages,
                        scrollFollowState = chatState.scrollFollowState,
                        flushTick = chatState.flushTick,
                        onUserScrolled = chatViewModel::onUserScrolled,
                        onScrolledNearBottom = chatViewModel::onScrolledNearBottom,
                        onScrolledToBottom = chatViewModel::onScrolledToBottom,
                        onScrollToBottom = chatViewModel::onScrolledToBottom,
                        onToggleThinking = chatViewModel::toggleThinkingBlock,
                        onToggleTool = chatViewModel::toggleToolBlock,
                        modifier = Modifier.weight(1f),
                    )
                    Composer(
                        state = chatState.composerState,
                        activeProvider = settingsState.currentProvider,
                        effort = chatState.activeThinkingEffort,
                        onEffortChange = chatViewModel::setEffort,
                        onSend = chatViewModel::sendMessage,
                        onStop = chatViewModel::cancelTurn,
                    )
                }
            }
        }
    },
    extraPane = {
        // 右侧：任务/Todo 面板（原 extraPane，名称不变）
        AnimatedPane {
            TodoPanel()
        }
    },
)
```

- [ ] **Step 4：验证构建**

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL。如果出现 `ThreePaneScaffoldDefaults.slideMotion` 无法解析的错误，检查以下备选 API 名称（不同 adaptive 库版本 API 名称略有差异）：
- `ThreePaneScaffoldDefaults.slideWithFlatAnimation()`
- `ThreePaneMotion.Companion.slideMotion`

如构建失败时报 `slideMotion` 找不到，在 `ui/mobile-android/` 目录执行：
```bash
./gradlew :app:dependencies | grep adaptive
```
查看实际引入的 adaptive 库版本，然后查阅对应版本的 API 文档确认正确的 `paneMotion` 配置名称。

- [ ] **Step 5：提交**

```bash
cd ui/mobile-android
git add app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt
git commit -m "feat(android): ChatScreen 迁移至 ThreePaneScaffold + slideMotion 推走动画

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2：真机验证清单

本 Task 为人工验证，无代码改动。安装 APK 后按以下场景测试：

- [ ] **场景 1：手机竖屏 — 左侧会话栏（SessionPanel）**
  - 点击 TopAppBar 左侧汉堡按钮
  - 预期：SessionPanel 从左侧滑入，聊天内容同步向右推出屏幕（不可见）
  - 对比旧行为：旧版是会话列表覆盖在聊天内容上面，两者同时可见

- [ ] **场景 2：手机竖屏 — 右侧 TodoPanel**
  - 点击 TopAppBar 右侧 Checklist 按钮
  - 预期：TodoPanel 从右侧滑入，聊天内容向左推出
  - 两个侧栏不能同时展开（手机模式互斥）

- [ ] **场景 3：手机竖屏 — 关闭侧栏**
  - 侧栏展开时按返回键或向反方向滑动
  - 预期：侧栏收回，聊天内容原路滑回

- [ ] **场景 4：侧栏展开时切换会话**
  - 打开 SessionPanel，点击一条会话
  - 预期：`navigateTo(ThreePaneScaffoldRole.Detail)` 让聊天内容显示回来，SessionPanel 自动收回

- [ ] **场景 5：平板横屏（如有，≥1000dp 宽度）**
  - 预期：左侧 SessionPanel 和中间聊天区常驻并排，无需手势切换

如发现任何场景与预期不符，在此 Task 下记录问题描述，单独提 issue 修复。

---

## 完成验收

```bash
cd ui/mobile-android && ./gradlew :app:assembleDebug
```

真机验证 Task 2 所有场景通过，则本计划完成。

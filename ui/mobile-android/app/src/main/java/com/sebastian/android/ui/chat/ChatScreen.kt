// com/sebastian/android/ui/chat/ChatScreen.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.common.ApprovalDialog
import com.sebastian.android.ui.common.ErrorBanner
import com.sebastian.android.ui.composer.Composer
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.ChatViewModel
import com.sebastian.android.viewmodel.SessionViewModel
import com.sebastian.android.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    navController: NavController,
    chatViewModel: ChatViewModel = hiltViewModel(),
    sessionViewModel: SessionViewModel = hiltViewModel(),
    settingsViewModel: SettingsViewModel = hiltViewModel(),
) {
    val chatState by chatViewModel.uiState.collectAsState()
    val sessionState by sessionViewModel.uiState.collectAsState()
    val settingsState by settingsViewModel.uiState.collectAsState()
    var activePane by rememberSaveable(
        stateSaver = Saver<SidePane, String>(
            save = { it.name },
            restore = { SidePane.valueOf(it) },
        ),
        init = { mutableStateOf(SidePane.NONE) },
    )

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> chatViewModel.onAppStart()
                Lifecycle.Event.ON_STOP -> chatViewModel.onAppStop()
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    // Approval Dialog（出现时阻断其他交互）
    chatState.pendingApprovals.firstOrNull()?.let { approval ->
        ApprovalDialog(
            approval = approval,
            onGrant = { chatViewModel.grantApproval(it) },
            onDeny = { chatViewModel.denyApproval(it) },
        )
    }

    SlidingThreePaneLayout(
        activePane = activePane,
        onPaneChange = { activePane = it },
        leftPane = {
            SessionPanel(
                sessions = sessionState.sessions,
                activeSessionId = chatState.activeSessionId,
                isNewSession = chatState.messages.isEmpty(),
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
        mainPane = {
            Scaffold(
                topBar = {
                    TopAppBar(
                        title = { Text("Sebastian") },
                        navigationIcon = {
                            IconButton(onClick = {
                                activePane = if (activePane == SidePane.LEFT) SidePane.NONE else SidePane.LEFT
                            }) {
                                Icon(Icons.Default.Menu, contentDescription = "会话列表")
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
                },
            ) { innerPadding ->
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(innerPadding)
                        .imePadding(),
                ) {
                    // 未配置服务器地址
                    AnimatedVisibility(visible = chatState.isServerNotConfigured) {
                        ErrorBanner(message = "请先在设置中配置服务器地址")
                    }
                    // 网络断开
                    AnimatedVisibility(visible = chatState.isOffline && !chatState.isServerNotConfigured) {
                        ErrorBanner(message = "网络已断开，重连中…")
                    }
                    // SSE 连接失败
                    AnimatedVisibility(
                        visible = chatState.connectionFailed &&
                            !chatState.isOffline &&
                            !chatState.isServerNotConfigured,
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
        },
        rightPane = {
            TodoPanel()
        },
    )
}

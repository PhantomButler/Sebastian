// com/sebastian/android/ui/chat/ChatScreen.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import com.kyant.backdrop.drawBackdrop
import com.kyant.backdrop.backdrops.layerBackdrop
import com.kyant.backdrop.backdrops.rememberLayerBackdrop
import com.kyant.backdrop.effects.blur
import com.kyant.backdrop.effects.vibrancy
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
    agentId: String? = null,
    agentName: String? = null,
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

    // Load appropriate sessions based on mode
    LaunchedEffect(agentId) {
        if (agentId != null) {
            sessionViewModel.loadAgentSessions(agentId)
        } else {
            sessionViewModel.loadSessions()
        }
    }

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

    SlidingThreePaneLayout(
        activePane = activePane,
        onPaneChange = { activePane = it },
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
        mainPane = {
            Scaffold(
                topBar = {
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

                    // Composer 悬浮于消息列表之上，液态玻璃背景 + 顶部渐变阴影
                    val backgroundColor = MaterialTheme.colorScheme.background
                    val surfaceColor = MaterialTheme.colorScheme.surface
                    val backdrop = rememberLayerBackdrop {
                        drawRect(backgroundColor)
                        drawContent()
                    }
                    Box(modifier = Modifier.weight(1f)) {
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
                            // contentPadding 留出 Composer 高度（最后一条消息可滚到 Composer 上方）
                            // 但 MessageList 的布局边界填满整个 Box，确保 backdrop 能采样整个区域
                            contentPadding = PaddingValues(bottom = 112.dp),
                            modifier = Modifier
                                .fillMaxSize()
                                .layerBackdrop(backdrop),
                        )

                        // 渐变遮罩：消息列表底部渐隐，营造 Composer 悬浮阴影感
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(40.dp)
                                .align(Alignment.BottomCenter)
                                .offset(y = (-112).dp)
                                .background(
                                    Brush.verticalGradient(
                                        listOf(
                                            Color.Transparent,
                                            backgroundColor.copy(alpha = 0.95f),
                                        )
                                    )
                                ),
                        )

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
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .drawBackdrop(
                                    backdrop = backdrop,
                                    shape = { androidx.compose.foundation.shape.RoundedCornerShape(24.dp) },
                                    effects = {
                                        vibrancy()
                                        blur(20f)
                                    },
                                    shadow = null,
                                    onDrawSurface = { drawRect(surfaceColor.copy(alpha = 0.5f)) },
                                ),
                        )
                    }
                }
            }
        },
        rightPane = {
            TodoPanel()
        },
    )
}

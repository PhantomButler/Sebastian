// com/sebastian/android/ui/chat/ChatScreen.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import android.widget.Toast
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import com.sebastian.android.data.model.Session
import com.sebastian.android.ui.common.ErrorBanner
import com.sebastian.android.ui.common.SebastianIcons
import com.sebastian.android.ui.common.glass.GlassSurface
import com.sebastian.android.ui.common.glass.pressScale
import com.sebastian.android.ui.common.glass.rememberGlassState
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
    var deleteTarget by remember { mutableStateOf<Session?>(null) }

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
                agentName = agentName,
                onSessionClick = { session ->
                    chatViewModel.switchSession(session.id)
                    activePane = SidePane.NONE
                },
                onDeleteSession = { deleteTarget = it },
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
            val glassState = rememberGlassState(MaterialTheme.colorScheme.background)
            val context = LocalContext.current
            // 单例 Toast：连点时先 cancel 上一个，避免排队连续弹
            var newSessionToast by remember { mutableStateOf<Toast?>(null) }
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .navigationBarsPadding()
                    .imePadding(),
            ) {
                // 内容层：MessageList 铺满全屏，顶部留出悬浮栏空间
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
                    contentPadding = PaddingValues(top = 88.dp, bottom = 112.dp),
                    modifier = Modifier
                        .fillMaxSize()
                        .then(glassState.contentModifier),
                )

                // Error banners：显示在悬浮顶部栏下方
                Column(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .padding(top = 72.dp),
                ) {
                    AnimatedVisibility(visible = chatState.isServerNotConfigured) {
                        ErrorBanner(message = "请先在设置中配置服务器地址")
                    }
                    AnimatedVisibility(visible = chatState.isOffline && !chatState.isServerNotConfigured) {
                        ErrorBanner(message = "网络已断开，重连中…")
                    }
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
                }

                // 悬浮顶部栏：左按钮 | 中间 title | 右按钮
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                ) {
                    val leftButtonSource = remember { MutableInteractionSource() }
                    GlassSurface(
                        state = glassState,
                        shape = CircleShape,
                        shadowCornerRadius = 22.dp,
                        modifier = Modifier
                            .size(44.dp)
                            .pressScale(leftButtonSource),
                    ) {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .fillMaxSize()
                                .clickable(
                                    interactionSource = leftButtonSource,
                                    indication = null,
                                ) {
                                    if (agentId != null) {
                                        navController.popBackStack()
                                    } else {
                                        activePane = if (activePane == SidePane.LEFT) SidePane.NONE else SidePane.LEFT
                                    }
                                },
                        ) {
                            Icon(
                                imageVector = if (agentId != null) Icons.AutoMirrored.Filled.ArrowBack else SebastianIcons.Sidebar,
                                contentDescription = if (agentId != null) "返回" else "会话列表",
                                tint = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                    }

                    Box(
                        contentAlignment = Alignment.CenterStart,
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 8.dp),
                    ) {
                        GlassSurface(
                            state = glassState,
                            shape = CircleShape,
                            shadowCornerRadius = 100.dp,
                        ) {
                            Text(
                                text = agentName ?: "Sebastian",
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                            )
                        }
                    }

                    GlassSurface(
                        state = glassState,
                        shape = RoundedCornerShape(22.dp),
                        shadowCornerRadius = 22.dp,
                        modifier = Modifier.size(width = 92.dp, height = 44.dp),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(horizontal = 6.dp),
                        ) {
                            // 新对话：若已在空白新对话，弹 Toast 提示而非重复创建
                            val newChatSource = remember { MutableInteractionSource() }
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .weight(1f)
                                    .fillMaxSize()
                                    .pressScale(newChatSource)
                                    .clickable(
                                        interactionSource = newChatSource,
                                        indication = null,
                                    ) {
                                        if (chatState.messages.isEmpty()) {
                                            newSessionToast?.cancel()
                                            newSessionToast = Toast.makeText(
                                                context,
                                                "Already in a new chat",
                                                Toast.LENGTH_SHORT,
                                            ).also { it.show() }
                                        } else {
                                            chatViewModel.newSession()
                                        }
                                    },
                            ) {
                                Icon(
                                    imageVector = SebastianIcons.Edit,
                                    contentDescription = "新对话",
                                    tint = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                            // 待办
                            val todoSource = remember { MutableInteractionSource() }
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .weight(1f)
                                    .fillMaxSize()
                                    .pressScale(todoSource)
                                    .clickable(
                                        interactionSource = todoSource,
                                        indication = null,
                                    ) {
                                        activePane = if (activePane == SidePane.RIGHT) SidePane.NONE else SidePane.RIGHT
                                    },
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Checklist,
                                    contentDescription = "待办事项",
                                    tint = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                        }
                    }
                }

                Composer(
                    state = chatState.composerState,
                    glassState = glassState,
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
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
        },
        rightPane = {
            TodoPanel()
        },
    )

    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除会话") },
            text = { Text("确定删除「${target.title.ifBlank { "新对话" }}」？此操作不可恢复。") },
            confirmButton = {
                TextButton(onClick = {
                    sessionViewModel.deleteSession(target.id)
                    if (chatState.activeSessionId == target.id) {
                        chatViewModel.newSession()
                    }
                    deleteTarget = null
                }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) { Text("取消") }
            },
        )
    }
}

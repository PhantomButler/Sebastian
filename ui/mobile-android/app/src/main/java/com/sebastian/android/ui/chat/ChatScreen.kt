// com/sebastian/android/ui/chat/ChatScreen.kt
package com.sebastian.android.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi
import androidx.compose.material3.adaptive.layout.AnimatedPane
import androidx.compose.material3.adaptive.layout.SupportingPaneScaffold
import androidx.compose.material3.adaptive.layout.SupportingPaneScaffoldRole
import androidx.compose.material3.adaptive.navigation.rememberSupportingPaneScaffoldNavigator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.style.TextAlign
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.sebastian.android.ui.common.ApprovalDialog
import com.sebastian.android.ui.composer.Composer
import com.sebastian.android.ui.navigation.Route
import com.sebastian.android.viewmodel.ChatViewModel
import com.sebastian.android.viewmodel.SessionViewModel
import com.sebastian.android.viewmodel.SettingsViewModel
import kotlinx.coroutines.launch

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
    val navigator = rememberSupportingPaneScaffoldNavigator<Nothing>()
    val scope = rememberCoroutineScope()

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

    SupportingPaneScaffold(
        directive = navigator.scaffoldDirective,
        value = navigator.scaffoldValue,
        mainPane = {
            AnimatedPane {
                Scaffold(
                    topBar = {
                        TopAppBar(
                            title = { Text("Sebastian") },
                            navigationIcon = {
                                IconButton(onClick = {
                                    scope.launch {
                                        navigator.navigateTo(SupportingPaneScaffoldRole.Supporting)
                                    }
                                }) {
                                    Icon(Icons.Default.Menu, contentDescription = "会话列表")
                                }
                            },
                            actions = {
                                IconButton(onClick = {
                                    scope.launch {
                                        navigator.navigateTo(SupportingPaneScaffoldRole.Extra)
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
                        AnimatedVisibility(visible = chatState.isOffline) {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(MaterialTheme.colorScheme.errorContainer)
                                    .padding(vertical = 4.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    text = "网络已断开，重连中…",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onErrorContainer,
                                    textAlign = TextAlign.Center,
                                )
                            }
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
                        val providers by settingsViewModel.uiState.collectAsState()

                        Composer(
                            state = chatState.composerState,
                            activeProvider = providers.providers.firstOrNull { it.isDefault },
                            effort = chatState.activeThinkingEffort,
                            onEffortChange = chatViewModel::setEffort,
                            onSend = chatViewModel::sendMessage,
                            onStop = chatViewModel::cancelTurn,
                        )
                    }
                }
            }
        },
        supportingPane = {
            AnimatedPane {
                SessionPanel(
                    sessions = sessionState.sessions,
                    activeSessionId = chatState.activeSessionId,
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
            }
        },
        extraPane = {
            AnimatedPane {
                TodoPanel()
            }
        },
    )
}

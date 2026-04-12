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

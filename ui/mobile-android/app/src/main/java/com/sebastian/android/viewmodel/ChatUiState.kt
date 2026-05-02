package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.ModelInputCapabilities
import com.sebastian.android.data.model.PendingAttachment
import com.sebastian.android.data.model.TodoItem

enum class ComposerState { IDLE_EMPTY, IDLE_READY, PENDING, STREAMING, CANCELLING }
enum class AgentAnimState { IDLE, PENDING, THINKING, STREAMING, WORKING }

sealed interface ChatUiEffect {
    data class RestoreComposerText(val text: String) : ChatUiEffect
    data class ShowToast(val message: String) : ChatUiEffect
    object RequestImagePicker : ChatUiEffect
}

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeSessionId: String? = null,       // null = 新对话
    val isOffline: Boolean = false,
    val error: String? = null,
    val isServerNotConfigured: Boolean = false,
    val connectionFailed: Boolean = false,
    val flushTick: Long = 0L,
    val todos: List<TodoItem> = emptyList(),
    val pendingAttachments: List<PendingAttachment> = emptyList(),
    val inputCapabilities: ModelInputCapabilities = ModelInputCapabilities(),
    val isSessionSwitching: Boolean = false,
    val activeSoulName: String = "Sebastian",
)

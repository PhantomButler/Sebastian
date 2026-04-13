package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.local.MarkdownParser
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import kotlin.coroutines.cancellation.CancellationException
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject

enum class ComposerState { IDLE_EMPTY, IDLE_READY, SENDING, STREAMING, CANCELLING }
enum class ScrollFollowState { FOLLOWING, DETACHED, NEAR_BOTTOM }
enum class AgentAnimState { IDLE, THINKING, STREAMING, WORKING }

data class PendingApproval(
    val approvalId: String,
    val sessionId: String,
    val description: String,
)

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeThinkingEffort: ThinkingEffort = ThinkingEffort.AUTO,
    val activeSessionId: String? = null,       // null = 新对话
    val isOffline: Boolean = false,
    val pendingApprovals: List<PendingApproval> = emptyList(),
    val error: String? = null,
    val isServerNotConfigured: Boolean = false,
    val connectionFailed: Boolean = false,
    val flushTick: Long = 0L,
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val settingsRepository: SettingsRepository,
    private val networkMonitor: NetworkMonitor,
    private val markdownParser: MarkdownParser,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    private val pendingDeltas = ConcurrentHashMap<String, StringBuilder>()

    private var sseJob: Job? = null
    private var currentAssistantMessageId: String? = null
    private var pendingTurnSessionId: String? = null

    init {
        observeNetwork()
        startDeltaFlusher()
        // activeSessionId starts as null → blank new conversation
    }

    private fun startDeltaFlusher() {
        viewModelScope.launch(dispatcher) {
            while (true) {
                delay(50L)
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
                        flushTick = state.flushTick + 1,
                    )
                }
            }
        }
    }

    private fun observeNetwork() {
        viewModelScope.launch(dispatcher) {
            networkMonitor.isOnline.collect { isOnline ->
                _uiState.update { it.copy(isOffline = !isOnline) }
                if (isOnline) {
                    _uiState.update { it.copy(connectionFailed = false) }
                    if (sseJob?.isActive != true && _uiState.value.activeSessionId != null) {
                        startSseCollection()
                    }
                }
            }
        }
    }

    private fun startSseCollection() {
        val sessionId = _uiState.value.activeSessionId ?: return
        sseJob?.cancel()
        sseJob = viewModelScope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) {
                _uiState.update { it.copy(isServerNotConfigured = true) }
                return@launch
            }
            _uiState.update { it.copy(isServerNotConfigured = false, connectionFailed = false) }
            try {
                chatRepository.sessionStream(baseUrl, sessionId).collect { event ->
                    handleEvent(event)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                if (!_uiState.value.isOffline) {
                    _uiState.update { it.copy(connectionFailed = true) }
                }
            }
        }
    }

    private fun handleEvent(event: StreamEvent) {
        when (event) {
            is StreamEvent.TurnReceived -> {
                pendingTurnSessionId = event.sessionId
                currentAssistantMessageId = UUID.randomUUID().toString()
            }

            is StreamEvent.ThinkingBlockStart -> {
                val block = ContentBlock.ThinkingBlock(blockId = event.blockId, text = "")
                appendBlockToCurrentMessage(block, agentAnimState = AgentAnimState.THINKING)
            }

            is StreamEvent.ThinkingDelta -> {
                updateBlockInCurrentMessage(event.blockId) { existing ->
                    if (existing is ContentBlock.ThinkingBlock) {
                        existing.copy(text = existing.text + event.delta)
                    } else existing
                }
            }

            is StreamEvent.ThinkingBlockStop -> {
                updateBlockInCurrentMessage(event.blockId) { existing ->
                    if (existing is ContentBlock.ThinkingBlock) existing.copy(done = true)
                    else existing
                }
            }

            is StreamEvent.TextBlockStart -> {
                val block = ContentBlock.TextBlock(blockId = event.blockId, text = "")
                appendBlockToCurrentMessage(
                    block,
                    composerState = ComposerState.STREAMING,
                    agentAnimState = AgentAnimState.STREAMING,
                )
            }

            is StreamEvent.TextDelta -> {
                pendingDeltas.getOrPut(event.blockId) { StringBuilder() }.append(event.delta)
            }

            is StreamEvent.TextBlockStop -> {
                viewModelScope.launch(dispatcher) {
                    val msgId = currentAssistantMessageId ?: return@launch
                    val pendingText = pendingDeltas.remove(event.blockId)?.toString() ?: ""
                    val baseText = _uiState.value.messages
                        .find { it.id == msgId }
                        ?.blocks?.find { it.blockId == event.blockId }
                        ?.let { (it as? ContentBlock.TextBlock)?.text } ?: ""
                    val rawText = baseText + pendingText
                    val rendered = withContext(dispatcher) {
                        markdownParser.parse(rawText)
                    }
                    updateBlockInCurrentMessage(event.blockId) { existing ->
                        if (existing is ContentBlock.TextBlock)
                            existing.copy(text = rawText, done = true, renderedMarkdown = rendered)
                        else existing
                    }
                }
            }

            is StreamEvent.ToolBlockStart -> {
                val block = ContentBlock.ToolBlock(
                    blockId = event.blockId,
                    toolId = event.toolId,
                    name = event.name,
                    inputs = "",
                    status = ToolStatus.PENDING,
                )
                appendBlockToCurrentMessage(block, agentAnimState = AgentAnimState.WORKING)
            }

            is StreamEvent.ToolBlockStop -> {
                updateBlockInCurrentMessage(event.blockId) { existing ->
                    if (existing is ContentBlock.ToolBlock) existing.copy(inputs = event.inputs) else existing
                }
            }

            is StreamEvent.ToolRunning -> {
                updateToolBlockByToolId(event.toolId) { existing ->
                    existing.copy(status = ToolStatus.RUNNING)
                }
            }

            is StreamEvent.ToolExecuted -> {
                updateToolBlockByToolId(event.toolId) { existing ->
                    existing.copy(status = ToolStatus.DONE, resultSummary = event.resultSummary)
                }
            }

            is StreamEvent.ToolFailed -> {
                updateToolBlockByToolId(event.toolId) { existing ->
                    existing.copy(status = ToolStatus.FAILED, error = event.error)
                }
            }

            is StreamEvent.TurnResponse -> {
                currentAssistantMessageId = null
                pendingTurnSessionId = null
                _uiState.update {
                    it.copy(
                        composerState = ComposerState.IDLE_EMPTY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
                }
            }

            is StreamEvent.TurnInterrupted -> {
                currentAssistantMessageId = null
                pendingTurnSessionId = null
                _uiState.update {
                    it.copy(
                        composerState = ComposerState.IDLE_EMPTY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
                }
            }

            is StreamEvent.ApprovalRequested -> {
                val approval = PendingApproval(
                    approvalId = event.approvalId,
                    sessionId = event.sessionId,
                    description = event.description,
                )
                _uiState.update { it.copy(pendingApprovals = it.pendingApprovals + approval) }
            }

            is StreamEvent.ApprovalGranted -> {
                _uiState.update {
                    it.copy(pendingApprovals = it.pendingApprovals.filter { a -> a.approvalId != event.approvalId })
                }
            }

            is StreamEvent.ApprovalDenied -> {
                _uiState.update {
                    it.copy(pendingApprovals = it.pendingApprovals.filter { a -> a.approvalId != event.approvalId })
                }
            }

            else -> Unit
        }
    }

    // ── Public mutation surface ──────────────────────────────────────────────

    fun sendMessage(text: String) {
        if (text.isBlank()) return
        val currentSessionId = _uiState.value.activeSessionId
        val userMsg = Message(
            id = UUID.randomUUID().toString(),
            sessionId = currentSessionId ?: "pending",
            role = MessageRole.USER,
            text = text,
        )
        _uiState.update { state ->
            state.copy(
                messages = state.messages + userMsg,
                composerState = ComposerState.SENDING,
                scrollFollowState = ScrollFollowState.FOLLOWING,
            )
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.sendTurn(currentSessionId, text, _uiState.value.activeThinkingEffort)
                .onSuccess { returnedSessionId ->
                    if (currentSessionId == null || currentSessionId != returnedSessionId) {
                        // New session created by backend — switch to it
                        _uiState.update { it.copy(activeSessionId = returnedSessionId) }
                        startSseCollection()
                        // Refresh session list so the sidebar picks up the new session
                        sessionRepository.loadSessions()
                    }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                }
        }
    }

    fun sendSessionMessage(sessionId: String, text: String) {
        if (text.isBlank()) return
        val userMsg = Message(id = UUID.randomUUID().toString(), sessionId = sessionId, role = MessageRole.USER, text = text)
        _uiState.update { state ->
            state.copy(messages = state.messages + userMsg, composerState = ComposerState.SENDING, scrollFollowState = ScrollFollowState.FOLLOWING)
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.sendSessionTurn(sessionId, text, _uiState.value.activeThinkingEffort)
                .onFailure { e -> _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) } }
        }
    }

    fun cancelTurn() {
        val sessionId = _uiState.value.activeSessionId ?: return
        _uiState.update { it.copy(composerState = ComposerState.CANCELLING) }
        viewModelScope.launch(dispatcher) {
            withTimeoutOrNull(5_000L) {
                chatRepository.cancelTurn(sessionId)
                    .onFailure { e ->
                        _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY, error = e.message) }
                    }
            } ?: _uiState.update { it.copy(composerState = ComposerState.IDLE_EMPTY) }
        }
    }

    fun switchSession(sessionId: String) {
        sseJob?.cancel()
        sseJob = null
        pendingDeltas.clear()
        currentAssistantMessageId = null
        pendingTurnSessionId = null
        _uiState.update {
            it.copy(
                activeSessionId = sessionId,
                messages = emptyList(),
                composerState = ComposerState.IDLE_EMPTY,
                agentAnimState = AgentAnimState.IDLE,
                pendingApprovals = emptyList(),
            )
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.getMessages(sessionId)
                .onSuccess { history ->
                    _uiState.update { it.copy(messages = history) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message) }
                }
            startSseCollection()
        }
    }

    /** Start a new conversation (no session yet). */
    fun newSession() {
        sseJob?.cancel()
        sseJob = null
        pendingDeltas.clear()
        currentAssistantMessageId = null
        pendingTurnSessionId = null
        _uiState.update {
            it.copy(
                activeSessionId = null,
                messages = emptyList(),
                composerState = ComposerState.IDLE_EMPTY,
                agentAnimState = AgentAnimState.IDLE,
                pendingApprovals = emptyList(),
                connectionFailed = false,
            )
        }
    }

    fun retryConnection() {
        _uiState.update { it.copy(connectionFailed = false) }
        startSseCollection()
    }

    fun onAppStart() {
        if (sseJob?.isActive != true && !_uiState.value.isOffline && _uiState.value.activeSessionId != null) {
            startSseCollection()
        }
    }

    fun onAppStop() {
        sseJob?.cancel()
        sseJob = null
    }

    fun setEffort(effort: ThinkingEffort) {
        _uiState.update { it.copy(activeThinkingEffort = effort) }
    }

    fun grantApproval(approvalId: String) {
        viewModelScope.launch(dispatcher) {
            chatRepository.grantApproval(approvalId)
                .onFailure { e -> _uiState.update { it.copy(error = e.message) } }
        }
    }

    fun denyApproval(approvalId: String) {
        viewModelScope.launch(dispatcher) {
            chatRepository.denyApproval(approvalId)
                .onFailure { e -> _uiState.update { it.copy(error = e.message) } }
        }
    }

    fun onUserScrolled() {
        _uiState.update { it.copy(scrollFollowState = ScrollFollowState.DETACHED) }
    }

    fun onScrolledNearBottom() {
        _uiState.update { it.copy(scrollFollowState = ScrollFollowState.NEAR_BOTTOM) }
    }

    fun onScrolledToBottom() {
        _uiState.update { it.copy(scrollFollowState = ScrollFollowState.FOLLOWING) }
    }

    fun toggleThinkingBlock(blockId: String) {
        updateBlock(blockId) { block ->
            if (block is ContentBlock.ThinkingBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun toggleToolBlock(blockId: String) {
        updateBlock(blockId) { block ->
            if (block is ContentBlock.ToolBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }

    // ── Private helpers ──────────────────────────────────────────────────────

    private fun updateBlock(blockId: String, transform: (ContentBlock) -> ContentBlock) {
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    msg.copy(blocks = msg.blocks.map { b -> if (b.blockId == blockId) transform(b) else b })
                },
            )
        }
    }

    private fun appendBlockToCurrentMessage(
        block: ContentBlock,
        composerState: ComposerState? = null,
        agentAnimState: AgentAnimState? = null,
    ) {
        val msgId = currentAssistantMessageId ?: return
        val sessionId = pendingTurnSessionId
        pendingTurnSessionId = null
        _uiState.update { state ->
            val messages = if (sessionId != null && state.messages.none { it.id == msgId }) {
                val newMsg = Message(
                    id = msgId,
                    sessionId = sessionId,
                    role = MessageRole.ASSISTANT,
                    blocks = listOf(block),
                )
                state.messages + newMsg
            } else {
                state.messages.map { msg ->
                    if (msg.id == msgId) msg.copy(blocks = msg.blocks + block) else msg
                }
            }
            state.copy(
                messages = messages,
                composerState = composerState ?: state.composerState,
                agentAnimState = agentAnimState ?: state.agentAnimState,
            )
        }
    }

    private fun updateBlockInCurrentMessage(blockId: String, transform: (ContentBlock) -> ContentBlock) {
        val msgId = currentAssistantMessageId ?: return
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    if (msg.id == msgId) {
                        msg.copy(blocks = msg.blocks.map { b -> if (b.blockId == blockId) transform(b) else b })
                    } else msg
                },
            )
        }
    }

    private fun updateToolBlockByToolId(toolId: String, transform: (ContentBlock.ToolBlock) -> ContentBlock.ToolBlock) {
        val msgId = currentAssistantMessageId ?: return
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    if (msg.id == msgId) {
                        msg.copy(
                            blocks = msg.blocks.map { b ->
                                if (b is ContentBlock.ToolBlock && b.toolId == toolId) transform(b) else b
                            },
                        )
                    } else msg
                },
            )
        }
    }
}

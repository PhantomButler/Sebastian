package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
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
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import kotlin.coroutines.cancellation.CancellationException
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject

enum class ComposerState { IDLE_EMPTY, IDLE_READY, PENDING, STREAMING, CANCELLING }
enum class ScrollFollowState { FOLLOWING, DETACHED, NEAR_BOTTOM }
enum class AgentAnimState { IDLE, PENDING, THINKING, STREAMING, WORKING }

data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
    val agentAnimState: AgentAnimState = AgentAnimState.IDLE,
    val activeSessionId: String? = null,       // null = 新对话
    val isOffline: Boolean = false,
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
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
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

    /**
     * @param replayFromStart 为 true 时发送 Last-Event-ID: 0，请求服务端回放缓冲事件。
     *   用于刚发送 turn 后立即建连的场景，避免 REST→SSE 窗口期内丢失事件。
     */
    private fun startSseCollection(replayFromStart: Boolean = false) {
        val sessionId = _uiState.value.activeSessionId ?: return
        sseJob?.cancel()
        sseJob = viewModelScope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) {
                _uiState.update { it.copy(isServerNotConfigured = true) }
                return@launch
            }
            _uiState.update { it.copy(isServerNotConfigured = false, connectionFailed = false) }
            val lastEventId = if (replayFromStart) "0" else null
            try {
                chatRepository.sessionStream(baseUrl, sessionId, lastEventId).collect { event ->
                    handleEvent(event)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                if (!_uiState.value.isOffline) {
                    _uiState.update { state ->
                        state.copy(
                            connectionFailed = true,
                            // If we lost the connection mid-turn, reset the composer so the
                            // button doesn't stay spinning with no way to dismiss.
                            composerState = if (state.composerState == ComposerState.PENDING ||
                                state.composerState == ComposerState.STREAMING
                            ) ComposerState.IDLE_EMPTY else state.composerState,
                        )
                    }
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
                appendBlockToCurrentMessage(block, composerState = ComposerState.STREAMING, agentAnimState = AgentAnimState.THINKING)
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
                    if (existing is ContentBlock.ThinkingBlock)
                        existing.copy(
                            done = true,
                            durationMs = event.durationMs,
                        )
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
                // Capture msgId synchronously — TurnResponse may clear it before any coroutine runs.
                val msgId = currentAssistantMessageId ?: return
                // Flush remaining pending text synchronously so no delta is ever lost.
                val pendingText = pendingDeltas.remove(event.blockId)?.toString() ?: ""
                updateBlockById(msgId, event.blockId) { existing ->
                    if (existing is ContentBlock.TextBlock)
                        existing.copy(
                            text = if (pendingText.isNotEmpty()) existing.text + pendingText else existing.text,
                            done = true,
                        )
                    else existing
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
                appendBlockToCurrentMessage(block, composerState = ComposerState.STREAMING, agentAnimState = AgentAnimState.WORKING)
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
                // Flush any deltas that arrived between the last flusher tick and now.
                flushPendingDeltasForCurrentMessage()
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
                flushPendingDeltasForCurrentMessage()
                currentAssistantMessageId = null
                pendingTurnSessionId = null
                _uiState.update {
                    it.copy(
                        composerState = ComposerState.IDLE_EMPTY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
                }
            }

            is StreamEvent.TurnCancelled -> {
                flushPendingDeltasForCurrentMessage()
                currentAssistantMessageId = null
                pendingTurnSessionId = null
                _uiState.update {
                    it.copy(
                        composerState = ComposerState.IDLE_EMPTY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
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
                composerState = ComposerState.PENDING,
                agentAnimState = AgentAnimState.PENDING,
                scrollFollowState = ScrollFollowState.FOLLOWING,
            )
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.sendTurn(currentSessionId, text)
                .onSuccess { returnedSessionId ->
                    // REST returned — leave PENDING; SSE block events will drive the transition.
                    if (currentSessionId == null || currentSessionId != returnedSessionId) {
                        // New session created by backend — switch to it
                        _uiState.update { it.copy(activeSessionId = returnedSessionId) }
                        // replayFromStart=true: REST 到 SSE 建连之间的事件需要回放
                        startSseCollection(replayFromStart = true)
                        // Refresh session list so the sidebar picks up the new session
                        sessionRepository.loadSessions()
                    } else {
                        // Existing session — SSE should already be running.
                        // If it died silently, restart with replay to catch in-flight events.
                        if (sseJob?.isActive != true) {
                            startSseCollection(replayFromStart = true)
                        }
                    }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                }
        }
    }

    fun sendAgentMessage(agentId: String, text: String) {
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
                composerState = ComposerState.PENDING,
                agentAnimState = AgentAnimState.PENDING,
                scrollFollowState = ScrollFollowState.FOLLOWING,
            )
        }
        viewModelScope.launch(dispatcher) {
            if (currentSessionId == null) {
                // New agent session: create + start SSE
                sessionRepository.createAgentSession(agentId, text)
                    .onSuccess { session ->
                        _uiState.update { it.copy(activeSessionId = session.id, composerState = ComposerState.IDLE_EMPTY) }
                        startSseCollection(replayFromStart = true)
                        sessionRepository.loadAgentSessions(agentId)
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                    }
            } else {
                // Existing session: send turn — leave PENDING; SSE block events drive the transition.
                chatRepository.sendSessionTurn(currentSessionId, text)
                    .onSuccess {
                        if (sseJob?.isActive != true) {
                            startSseCollection(replayFromStart = true)
                        }
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) }
                    }
            }
        }
    }

    fun sendSessionMessage(sessionId: String, text: String) {
        if (text.isBlank()) return
        val userMsg = Message(id = UUID.randomUUID().toString(), sessionId = sessionId, role = MessageRole.USER, text = text)
        _uiState.update { state ->
            state.copy(
                messages = state.messages + userMsg,
                composerState = ComposerState.PENDING,
                agentAnimState = AgentAnimState.PENDING,
                scrollFollowState = ScrollFollowState.FOLLOWING,
            )
        }
        viewModelScope.launch(dispatcher) {
            // Leave PENDING on success; SSE block events drive the transition.
            chatRepository.sendSessionTurn(sessionId, text)
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
            )
        }
        viewModelScope.launch(dispatcher) {
            val needsReplay = chatRepository.getMessages(sessionId)
                .onSuccess { history ->
                    _uiState.update { it.copy(messages = history) }
                }
                .map { history ->
                    // 最后一条消息是 user → turn 进行中，需要回放以补回流式事件
                    history.isEmpty() || history.lastOrNull()?.role == MessageRole.USER
                }
                .getOrDefault(true) // hydration 失败时保守回放
            startSseCollection(replayFromStart = needsReplay)
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
                connectionFailed = false,
            )
        }
    }

    fun retryConnection() {
        _uiState.update { it.copy(connectionFailed = false) }
        startSseCollection()
    }

    /**
     * 回前台时调用。承担 spec 的 chat reconcile 职责：复用 [switchSession] 作为幂等
     * reconcile 原语（清空 → getMessages 全量 hydrate → SSE Last-Event-ID replay），
     * 覆盖"切后台回来半截 assistant 气泡 / 输入框状态错乱"场景。
     *
     * Streaming/Sending/Cancelling 期间跳过，避免把正在流的 turn 切断；离线时跳过，
     * 留给 [observeNetwork] 在网络恢复后接管重连。IDLE_READY 期间跳过，避免把用户
     * 在 Composer 里未发送的半截输入对应的发送按钮状态拨回 IDLE_EMPTY（Composer 文本
     * 存在 ChatScreen 的 local remember state，ViewModel 不感知）造成视觉错位。
     */
    fun onAppStart() {
        val state = _uiState.value
        val sessionId = state.activeSessionId ?: return
        if (state.isOffline) return
        if (state.composerState == ComposerState.STREAMING ||
            state.composerState == ComposerState.PENDING ||
            state.composerState == ComposerState.CANCELLING ||
            state.composerState == ComposerState.IDLE_READY
        ) return
        switchSession(sessionId)
    }

    fun onAppStop() {
        sseJob?.cancel()
        sseJob = null
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

    fun toggleThinkingBlock(msgId: String, blockId: String) {
        updateBlockById(msgId, blockId) { block ->
            if (block is ContentBlock.ThinkingBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun toggleToolBlock(msgId: String, blockId: String) {
        updateBlockById(msgId, blockId) { block ->
            if (block is ContentBlock.ToolBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }

    // ── Private helpers ──────────────────────────────────────────────────────

    /**
     * Like [updateBlockInCurrentMessage] but takes an explicit [msgId] instead of reading
     * [currentAssistantMessageId]. Use this in async coroutines where the assistant message
     * reference must be captured before [currentAssistantMessageId] is cleared by TurnResponse.
     */
    private fun updateBlockById(
        msgId: String,
        blockId: String,
        transform: (ContentBlock) -> ContentBlock,
    ) {
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { msg ->
                    if (msg.id != msgId) return@map msg
                    msg.copy(blocks = msg.blocks.map { b -> if (b.blockId == blockId) transform(b) else b })
                },
            )
        }
    }

    /**
     * Synchronously drain [pendingDeltas] into the current assistant message.
     * Must be called before clearing [currentAssistantMessageId] (e.g. in TurnResponse handler)
     * to avoid losing the last batch of deltas that the 50ms flusher hasn't yet applied.
     */
    private fun flushPendingDeltasForCurrentMessage() {
        val msgId = currentAssistantMessageId ?: return
        if (pendingDeltas.isEmpty()) return
        val snapshot = pendingDeltas.keys.toList().mapNotNull { key ->
            pendingDeltas.remove(key)?.toString()?.let { key to it }
        }
        if (snapshot.isEmpty()) return
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

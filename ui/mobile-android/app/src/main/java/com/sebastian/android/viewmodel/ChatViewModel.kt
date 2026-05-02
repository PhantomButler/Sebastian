package com.sebastian.android.viewmodel

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.qualifiers.ApplicationContext
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.AttachmentArtifact
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.ModelInputCapabilities
import com.sebastian.android.data.model.PendingAttachment
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import kotlin.coroutines.cancellation.CancellationException
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject


@HiltViewModel
class ChatViewModel @Inject constructor(
    @ApplicationContext private val appContext: Context,
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val settingsRepository: SettingsRepository,
    private val agentRepository: AgentRepository,
    private val networkMonitor: NetworkMonitor,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    private val serverUrl: StateFlow<String> = settingsRepository.serverUrl
        .stateIn(viewModelScope, SharingStarted.Eagerly, "")

    private val _toastEvents = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val toastEvents: SharedFlow<String> = _toastEvents.asSharedFlow()

    private val _uiEffects = MutableSharedFlow<ChatUiEffect>(extraBufferCapacity = 4)
    val uiEffects: SharedFlow<ChatUiEffect> = _uiEffects.asSharedFlow()

    private val lastDeliveredSseEventIds = ConcurrentHashMap<String, String>()
    internal var sessionIdProvider: () -> String = { UUID.randomUUID().toString() }
    @Volatile private var isProvisionalSession = false

    private val pendingDeltas = ConcurrentHashMap<String, StringBuilder>()

    private var sseJob: Job? = null
    private var sendTurnJob: Job? = null
    private var currentAssistantMessageId: String? = null
    private var pendingTurnSessionId: String? = null
    // Number of TurnReceived events to skip during SSE replay after switchSession.
    // Prevents duplicate assistant messages when replaying already-hydrated completed turns.
    private var sseReplayTurnSkipCount = 0

    private var pendingTimeoutJob: Job? = null
    private var pendingTimeoutElapsedMs: Long = 0L
    private var pendingTimeoutStartAtMs: Long = 0L

    // Overrideable in tests to use virtual time.
    internal var clock: () -> Long = { System.currentTimeMillis() }

    // ── Test helpers (not for production use) ────────────────────────────────
    internal fun setInputCapabilities(caps: ModelInputCapabilities) {
        _uiState.update { it.copy(inputCapabilities = caps) }
    }

    internal fun setTestPendingAttachments(attachments: List<PendingAttachment>) {
        _uiState.update { it.copy(pendingAttachments = attachments) }
    }

    internal val attachmentManager = ChatAttachmentManager(
        context = appContext,
        chatRepository = chatRepository,
        dispatcher = dispatcher,
        scope = viewModelScope,
        uiState = _uiState,
        uiEffects = _uiEffects,
    )

    companion object {
        private const val PENDING_TIMEOUT_MS = 15_000L
    }

    init {
        observeNetwork()
        startDeltaFlusher()
        // activeSessionId starts as null → blank new conversation
        observeActiveSoul()
        fetchInitialSoulIfNeeded()
    }

    private fun observeActiveSoul() {
        viewModelScope.launch(dispatcher) {
            settingsRepository.activeSoul.collect { name ->
                if (name.isNotBlank()) {
                    _uiState.update { it.copy(activeSoulName = name.replaceFirstChar { c -> c.uppercase() }) }
                }
            }
        }
    }

    private fun fetchInitialSoulIfNeeded() {
        viewModelScope.launch(dispatcher) {
            val cached = settingsRepository.activeSoul.first()  // Flow<String>.first(), NOT .value
            if (cached.isNotBlank()) return@launch
            settingsRepository.fetchActiveSoul()
                .onSuccess { name ->
                    settingsRepository.saveActiveSoul(name)
                }
        }
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

    private fun startSseCollection(
        sessionId: String = requireNotNull(_uiState.value.activeSessionId),
        lastEventId: String? = lastDeliveredSseEventIds[sessionId],
    ) {
        sseJob?.cancel()
        sseJob = viewModelScope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) {
                _uiState.update { it.copy(isServerNotConfigured = true) }
                return@launch
            }
            _uiState.update { it.copy(isServerNotConfigured = false, connectionFailed = false) }
            try {
                chatRepository.sessionStream(baseUrl, sessionId, lastEventId)
                    .collect { envelope ->
                        handleEvent(envelope.event)
                        envelope.eventId?.let { lastDeliveredSseEventIds[sessionId] = it }
                    }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                if (!_uiState.value.isOffline) {
                    _uiState.update { state ->
                        state.copy(
                            connectionFailed = true,
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
        cancelPendingTimeout()
        when (event) {
            is StreamEvent.TurnReceived -> {
                if (sseReplayTurnSkipCount > 0) {
                    sseReplayTurnSkipCount--
                    return  // skip replayed completed turn; currentAssistantMessageId stays null
                }
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
                    displayName = event.name,  // 初始 fallback，ToolRunning 时会更新
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
                    existing.copy(
                        status = ToolStatus.RUNNING,
                        displayName = event.displayName,
                    )
                }
            }

            is StreamEvent.ToolExecuted -> {
                if (event.artifact != null) {
                    // Artifact replaces the ToolBlock entirely; displayName was already set by ToolRunning.
                    val sessionId = _uiState.value.activeSessionId
                    if (sessionId == event.sessionId && currentAssistantMessageId != null) {
                        replaceOrAppendArtifactBlock(
                            event.toolId,
                            artifactToContentBlock(event.sessionId, event.artifact),
                        )
                    }
                } else {
                    updateToolBlockByToolId(event.toolId) { existing ->
                        existing.copy(
                            status = ToolStatus.DONE,
                            resultSummary = event.resultSummary,
                            displayName = event.displayName,
                        )
                    }
                }
            }

            is StreamEvent.ToolFailed -> {
                updateToolBlockByToolId(event.toolId) { existing ->
                    existing.copy(
                        status = ToolStatus.FAILED,
                        error = event.error,
                        displayName = event.displayName,
                    )
                }
            }

            is StreamEvent.TodoUpdated -> {
                val sessionId = _uiState.value.activeSessionId ?: return
                viewModelScope.launch(dispatcher) {
                    chatRepository.getTodos(sessionId).onSuccess { todos ->
                        _uiState.update { state ->
                            if (state.activeSessionId == sessionId) state.copy(todos = todos) else state
                        }
                    }
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

    fun refreshInputCapabilities(agentId: String?) {
        viewModelScope.launch(dispatcher) {
            val caps = if (agentId == null) {
                settingsRepository.getDefaultBinding()
                    .getOrNull()
                    ?.resolved
                    ?.toInputCapabilities()
            } else {
                agentRepository.getAgentBinding(agentId)
                    .getOrNull()
                    ?.resolved
                    ?.toInputCapabilities()
            } ?: ModelInputCapabilities()

            _uiState.update { it.copy(inputCapabilities = caps) }
        }
    }

    fun sendMessage(
        text: String,
        attachments: List<PendingAttachment> = _uiState.value.pendingAttachments,
    ) {
        if (text.isBlank() && attachments.isEmpty()) return
        val currentSessionId = _uiState.value.activeSessionId
        val contentResolver = appContext.contentResolver

        if (currentSessionId == null) {
            val clientSessionId = sessionIdProvider()
            val userMsgId = UUID.randomUUID().toString()
            val userMsg = Message(
                id = userMsgId,
                sessionId = clientSessionId,
                role = MessageRole.USER,
                text = text,
                blocks = attachments.map { it.toContentBlock(serverUrl.value.trimEnd('/')) },
            )
            isProvisionalSession = true
            _uiState.update { state ->
                state.copy(
                    messages = state.messages + userMsg,
                    activeSessionId = clientSessionId,
                    composerState = ComposerState.PENDING,
                    agentAnimState = AgentAnimState.PENDING,
                )
            }
            startPendingTimeout()
            startSseCollection(sessionId = clientSessionId, lastEventId = "0")
            sendTurnJob = viewModelScope.launch(dispatcher) {
                val uploadedAttachments = attachmentManager.uploadPendingAttachments(attachments, contentResolver)
                if (uploadedAttachments == null) {
                    // uploadPendingAttachments already set composerState=IDLE_READY and showed toast.
                    // Also clean up the provisional session state.
                    // Note: pendingAttachments is intentionally NOT cleared here — failed-upload
                    // entries retain AttachmentUploadState.Failed so the user can retry or remove them.
                    cancelPendingTimeout()
                    sendTurnJob = null
                    isProvisionalSession = false
                    sseJob?.cancel()
                    sseJob = null
                    _uiState.update { state ->
                        state.copy(
                            messages = state.messages.filter { it.id != userMsgId },
                            activeSessionId = null,
                            composerState = ComposerState.IDLE_READY,
                            agentAnimState = AgentAnimState.IDLE,
                        )
                    }
                    viewModelScope.launch {
                        _uiEffects.emit(ChatUiEffect.RestoreComposerText(text))
                    }
                    return@launch
                }
                val attachmentIds = uploadedAttachments.mapNotNull { it.attachmentId }
                chatRepository.sendTurn(clientSessionId, text, attachmentIds)
                    .onSuccess { _ ->
                        sendTurnJob = null
                        isProvisionalSession = false
                        _uiState.update { it.copy(pendingAttachments = emptyList()) }
                        sessionRepository.loadSessions()
                    }
                    .onFailure { e -> handleNewSessionSendFailure(userMsgId, text, e) }
            }
        } else {
            val userMsgId = UUID.randomUUID().toString()
            val userMsg = Message(
                id = userMsgId,
                sessionId = currentSessionId,
                role = MessageRole.USER,
                text = text,
                blocks = attachments.map { it.toContentBlock(serverUrl.value.trimEnd('/')) },
            )
            _uiState.update { state ->
                state.copy(
                    messages = state.messages + userMsg,
                    composerState = ComposerState.PENDING,
                    agentAnimState = AgentAnimState.PENDING,
                )
            }
            startPendingTimeout()
            sendTurnJob = viewModelScope.launch(dispatcher) {
                val uploadedAttachments = attachmentManager.uploadPendingAttachments(attachments, contentResolver)
                if (uploadedAttachments == null) return@launch  // upload failed, already handled
                val attachmentIds = uploadedAttachments.mapNotNull { it.attachmentId }
                chatRepository.sendTurn(currentSessionId, text, attachmentIds)
                    .onSuccess { returnedSessionId ->
                        sendTurnJob = null
                        _uiState.update { it.copy(pendingAttachments = emptyList()) }
                        if (currentSessionId != returnedSessionId) {
                            _uiState.update { it.copy(activeSessionId = returnedSessionId) }
                            startSseCollection(lastEventId = "0")
                            sessionRepository.loadSessions()
                        } else {
                            if (sseJob?.isActive != true) startSseCollection(
                                lastEventId = lastDeliveredSseEventIds[currentSessionId],
                            )
                        }
                    }
                    .onFailure { e -> handleExistingSessionSendFailure(userMsgId, text, e) }
            }
        }
    }

    fun sendAgentMessage(
        agentId: String,
        text: String,
        attachments: List<PendingAttachment> = _uiState.value.pendingAttachments,
    ) {
        if (text.isBlank() && attachments.isEmpty()) return
        val currentSessionId = _uiState.value.activeSessionId
        val contentResolver = appContext.contentResolver

        if (currentSessionId == null) {
            val clientSessionId = sessionIdProvider()
            val userMsgId = UUID.randomUUID().toString()
            val userMsg = Message(
                id = userMsgId,
                sessionId = clientSessionId,
                role = MessageRole.USER,
                text = text,
                blocks = attachments.map { it.toContentBlock(serverUrl.value.trimEnd('/')) },
            )
            isProvisionalSession = true
            _uiState.update { state ->
                state.copy(
                    messages = state.messages + userMsg,
                    activeSessionId = clientSessionId,
                    composerState = ComposerState.PENDING,
                    agentAnimState = AgentAnimState.PENDING,
                )
            }
            startPendingTimeout()
            startSseCollection(sessionId = clientSessionId, lastEventId = "0")
            sendTurnJob = viewModelScope.launch(dispatcher) {
                val uploadedAttachments = attachmentManager.uploadPendingAttachments(attachments, contentResolver)
                if (uploadedAttachments == null) {
                    // uploadPendingAttachments already set composerState=IDLE_READY and showed toast.
                    // Also clean up the provisional session state.
                    cancelPendingTimeout()
                    sendTurnJob = null
                    isProvisionalSession = false
                    sseJob?.cancel()
                    sseJob = null
                    _uiState.update { state ->
                        state.copy(
                            messages = state.messages.filter { it.id != userMsgId },
                            activeSessionId = null,
                            composerState = ComposerState.IDLE_READY,
                            agentAnimState = AgentAnimState.IDLE,
                        )
                    }
                    viewModelScope.launch {
                        _uiEffects.emit(ChatUiEffect.RestoreComposerText(text))
                    }
                    return@launch
                }
                val attachmentIds = uploadedAttachments.mapNotNull { it.attachmentId }
                sessionRepository.createAgentSession(agentId, text, sessionId = clientSessionId, attachmentIds = attachmentIds)
                    .onSuccess { _ ->
                        sendTurnJob = null
                        isProvisionalSession = false
                        _uiState.update { it.copy(pendingAttachments = emptyList()) }
                        sessionRepository.loadAgentSessions(agentId)
                    }
                    .onFailure { e -> handleNewSessionSendFailure(userMsgId, text, e) }
            }
        } else {
            val userMsgId = UUID.randomUUID().toString()
            val userMsg = Message(
                id = userMsgId,
                sessionId = currentSessionId,
                role = MessageRole.USER,
                text = text,
                blocks = attachments.map { it.toContentBlock(serverUrl.value.trimEnd('/')) },
            )
            _uiState.update { state ->
                state.copy(
                    messages = state.messages + userMsg,
                    composerState = ComposerState.PENDING,
                    agentAnimState = AgentAnimState.PENDING,
                )
            }
            startPendingTimeout()
            sendTurnJob = viewModelScope.launch(dispatcher) {
                val uploadedAttachments = attachmentManager.uploadPendingAttachments(attachments, contentResolver)
                if (uploadedAttachments == null) return@launch
                val attachmentIds = uploadedAttachments.mapNotNull { it.attachmentId }
                chatRepository.sendSessionTurn(currentSessionId, text, attachmentIds)
                    .onSuccess {
                        sendTurnJob = null
                        _uiState.update { it.copy(pendingAttachments = emptyList()) }
                        if (sseJob?.isActive != true) {
                            startSseCollection(
                                lastEventId = lastDeliveredSseEventIds[currentSessionId],
                            )
                        }
                    }
                    .onFailure { e -> handleExistingSessionSendFailure(userMsgId, text, e) }
            }
        }
    }

    // ── Attachment methods ──────────────────────────────────────────────────

    fun onAttachmentMenuImageSelected() = attachmentManager.onAttachmentMenuImageSelected()
    fun onAttachmentImagePicked(uri: Uri, filename: String, mimeType: String, sizeBytes: Long) =
        attachmentManager.onAttachmentImagePicked(uri, filename, mimeType, sizeBytes)
    fun onAttachmentFilePicked(uri: Uri, filename: String, mimeType: String, sizeBytes: Long) =
        attachmentManager.onAttachmentFilePicked(uri, filename, mimeType, sizeBytes)
    fun onRemoveAttachment(localId: String) = attachmentManager.onRemoveAttachment(localId)
    fun onRetryAttachment(localId: String) = attachmentManager.onRetryAttachment(localId)

    fun sendSessionMessage(sessionId: String, text: String) {
        if (text.isBlank()) return
        val userMsg = Message(id = UUID.randomUUID().toString(), sessionId = sessionId, role = MessageRole.USER, text = text)
        _uiState.update { state ->
            state.copy(
                messages = state.messages + userMsg,
                composerState = ComposerState.PENDING,
                agentAnimState = AgentAnimState.PENDING,
            )
        }
        viewModelScope.launch(dispatcher) {
            // Leave PENDING on success; SSE block events drive the transition.
            chatRepository.sendSessionTurn(sessionId, text)
                .onFailure { e -> _uiState.update { it.copy(composerState = ComposerState.IDLE_READY, error = e.message) } }
        }
    }

    fun cancelTurn() {
        cancelPendingTimeout()
        val sessionId = _uiState.value.activeSessionId
        if (sessionId == null || isProvisionalSession) {
            // Still pre-REST (no session) or provisional session — cancel the local job,
            // keep user bubble for editing/retry.
            sendTurnJob?.cancel()
            sendTurnJob = null
            sseJob?.cancel()
            sseJob = null
            isProvisionalSession = false
            _uiState.update {
                it.copy(
                    activeSessionId = null,
                    composerState = ComposerState.IDLE_READY,
                    agentAnimState = AgentAnimState.IDLE,
                )
            }
            return
        }
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
        sseReplayTurnSkipCount = 0
        _uiState.update {
            it.copy(
                activeSessionId = sessionId,
                messages = emptyList(),
                todos = emptyList(),
                composerState = ComposerState.IDLE_EMPTY,
                agentAnimState = AgentAnimState.IDLE,
                isSessionSwitching = true,
            )
        }
        viewModelScope.launch(dispatcher) {
            // Determine SSE lastEventId before hydrating, then adjust after REST history is known.
            var lastEventId: String? = lastDeliveredSseEventIds[sessionId]
            chatRepository.getMessages(sessionId)
                .onSuccess { history ->
                    _uiState.update { it.copy(messages = history, isSessionSwitching = false) }
                    // First visit to a session whose last message is USER means a turn is still
                    // in progress. Replay from ring buffer start ("0") so that TurnReceived is
                    // delivered and in-progress streaming events are visible immediately.
                    if (lastEventId == null && history.lastOrNull()?.role == MessageRole.USER) {
                        // Skip TurnReceived for turns already loaded via REST to avoid duplicates.
                        sseReplayTurnSkipCount = history.count { it.role == MessageRole.ASSISTANT }
                        lastEventId = "0"
                    }
                }
                .onFailure {
                    _uiState.update { state ->
                        if (state.activeSessionId == sessionId) state.copy(isSessionSwitching = false) else state
                    }
                }
            chatRepository.getTodos(sessionId).onSuccess { todos ->
                _uiState.update { state ->
                    if (state.activeSessionId == sessionId) state.copy(todos = todos) else state
                }
            }
            startSseCollection(sessionId = sessionId, lastEventId = lastEventId)
        }
    }

    /** Start a new conversation (no session yet). */
    fun newSession() {
        sseJob?.cancel()
        sseJob = null
        pendingDeltas.clear()
        currentAssistantMessageId = null
        pendingTurnSessionId = null
        sseReplayTurnSkipCount = 0
        _uiState.update {
            it.copy(
                activeSessionId = null,
                messages = emptyList(),
                todos = emptyList(),
                pendingAttachments = emptyList(),
                composerState = ComposerState.IDLE_EMPTY,
                agentAnimState = AgentAnimState.IDLE,
                connectionFailed = false,
            )
        }
    }

    fun retryConnection() {
        if (_uiState.value.activeSessionId == null) return
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
        resumePendingTimeoutIfNeeded()
        val state = _uiState.value
        if (state.isOffline) return

        if (state.composerState == ComposerState.PENDING) {
            val sessionId = state.activeSessionId ?: run {
                // Provisional session still open — SSE is already running
                return
            }
            viewModelScope.launch(dispatcher) {
                chatRepository.getMessages(sessionId)
                    .onSuccess { msgs ->
                        val last = msgs.lastOrNull()
                        val turnDone = last?.role == MessageRole.ASSISTANT &&
                            last.blocks.lastOrNull()?.isDone == true
                        if (turnDone) {
                            cancelPendingTimeout()
                            _uiState.update {
                                it.copy(
                                    messages = msgs,
                                    composerState = ComposerState.IDLE_EMPTY,
                                    agentAnimState = AgentAnimState.IDLE,
                                )
                            }
                            // 补刷 todos：turn 已完成说明 todo_write 可能已执行
                            chatRepository.getTodos(sessionId).onSuccess { todos ->
                                _uiState.update { state ->
                                    if (state.activeSessionId == sessionId) state.copy(todos = todos) else state
                                }
                            }
                        }
                        startSseCollection()
                    }
                    .onFailure {
                        startSseCollection()
                    }
            }
            return
        }

        val sessionId = state.activeSessionId ?: return
        if (state.composerState == ComposerState.STREAMING ||
            state.composerState == ComposerState.CANCELLING ||
            state.composerState == ComposerState.IDLE_READY
        ) return
        switchSession(sessionId)
    }

    fun onAppStop() {
        pausePendingTimeout()
        sseJob?.cancel()
        sseJob = null
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

    fun toggleSummaryBlock(msgId: String, blockId: String) {
        updateBlockById(msgId, blockId) { block ->
            if (block is ContentBlock.SummaryBlock) block.copy(expanded = !block.expanded) else block
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }

    // ── Pending timeout helpers ──────────────────────────────────────────────

    private fun startPendingTimeout() {
        pendingTimeoutElapsedMs = 0L
        launchPendingTimeoutSegment(PENDING_TIMEOUT_MS)
    }

    private fun launchPendingTimeoutSegment(remaining: Long) {
        pendingTimeoutJob?.cancel()
        pendingTimeoutStartAtMs = clock()
        pendingTimeoutJob = viewModelScope.launch(dispatcher) {
            delay(remaining)
            _toastEvents.emit("响应较慢，可点停止后重试")
        }
    }

    private fun pausePendingTimeout() {
        if (pendingTimeoutJob?.isActive == true) {
            pendingTimeoutElapsedMs += clock() - pendingTimeoutStartAtMs
            pendingTimeoutJob?.cancel()
            pendingTimeoutJob = null
        }
    }

    private fun resumePendingTimeoutIfNeeded() {
        if (_uiState.value.composerState != ComposerState.PENDING) return
        val remaining = (PENDING_TIMEOUT_MS - pendingTimeoutElapsedMs).coerceAtLeast(0L)
        if (remaining == 0L) return
        launchPendingTimeoutSegment(remaining)
    }

    private fun cancelPendingTimeout() {
        pendingTimeoutJob?.cancel()
        pendingTimeoutJob = null
        pendingTimeoutElapsedMs = 0L
    }

    private fun handleNewSessionSendFailure(userMsgId: String, text: String, e: Throwable) {
        sendTurnJob = null
        isProvisionalSession = false
        sseJob?.cancel()
        sseJob = null
        _uiState.update { state ->
            state.copy(
                messages = state.messages.filter { it.id != userMsgId },
                activeSessionId = null,
                composerState = ComposerState.IDLE_EMPTY,
                agentAnimState = AgentAnimState.IDLE,
                error = e.message,
            )
        }
        viewModelScope.launch {
            _uiEffects.emit(ChatUiEffect.RestoreComposerText(text))
            _uiEffects.emit(ChatUiEffect.ShowToast("发送失败，请重试"))
        }
    }

    private fun handleExistingSessionSendFailure(userMsgId: String, text: String, e: Throwable) {
        sendTurnJob = null
        _uiState.update { state ->
            state.copy(
                messages = state.messages.filter { it.id != userMsgId },
                composerState = ComposerState.IDLE_READY,
                error = e.message,
            )
        }
        viewModelScope.launch {
            _uiEffects.emit(ChatUiEffect.RestoreComposerText(text))
            _uiEffects.emit(ChatUiEffect.ShowToast("发送失败，请重试"))
        }
    }

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

    private fun artifactToContentBlock(sessionId: String, artifact: AttachmentArtifact): ContentBlock {
        val base = serverUrl.value.trimEnd('/')
        fun absolute(url: String): String =
            if (url.startsWith("http://") || url.startsWith("https://")) url else "$base$url"

        return when (artifact.kind) {
            "image" -> ContentBlock.ImageBlock(
                blockId = "stream-$sessionId-artifact-${artifact.attachmentId}",
                attachmentId = artifact.attachmentId,
                filename = artifact.filename,
                mimeType = artifact.mimeType,
                sizeBytes = artifact.sizeBytes,
                downloadUrl = absolute(artifact.downloadUrl),
                thumbnailUrl = artifact.thumbnailUrl?.let(::absolute),
            )
            "text_file" -> ContentBlock.FileBlock(
                blockId = "stream-$sessionId-artifact-${artifact.attachmentId}",
                attachmentId = artifact.attachmentId,
                filename = artifact.filename,
                mimeType = artifact.mimeType,
                sizeBytes = artifact.sizeBytes,
                downloadUrl = absolute(artifact.downloadUrl),
                textExcerpt = artifact.textExcerpt,
            )
            else -> {
                // Unknown kind: log and fall back to FileBlock to avoid leaving ToolBlock in PENDING
                android.util.Log.w("ChatViewModel", "Unknown artifact kind '${artifact.kind}', rendering as file block")
                ContentBlock.FileBlock(
                    blockId = "stream-$sessionId-artifact-${artifact.attachmentId}",
                    attachmentId = artifact.attachmentId,
                    filename = artifact.filename,
                    mimeType = artifact.mimeType,
                    sizeBytes = artifact.sizeBytes,
                    downloadUrl = absolute(artifact.downloadUrl),
                    textExcerpt = artifact.textExcerpt,
                )
            }
        }
    }

    private fun ContentBlock.attachmentIdOrNull(): String? = when (this) {
        is ContentBlock.ImageBlock -> attachmentId
        is ContentBlock.FileBlock -> attachmentId
        else -> null
    }

    private fun replaceOrAppendArtifactBlock(toolId: String, artifactBlock: ContentBlock) {
        val artifactAttId = artifactBlock.attachmentIdOrNull() ?: return
        val msgId = currentAssistantMessageId ?: return
        _uiState.update { state ->
            val existingMsg = state.messages.find { it.id == msgId } ?: return@update state

            var replaced = false
            val newBlocks = existingMsg.blocks.map { block ->
                if (block is ContentBlock.ToolBlock && block.toolId == toolId) {
                    replaced = true
                    artifactBlock
                } else block
            }

            if (replaced) {
                // ToolBlock was replaced — no dedup needed
                state.copy(
                    messages = state.messages.map { msg ->
                        if (msg.id == msgId) msg.copy(blocks = newBlocks) else msg
                    },
                )
            } else {
                // No ToolBlock to replace — append with dedup across all messages
                val alreadyPresent = state.messages.any { msg ->
                    msg.blocks.any { it.attachmentIdOrNull() == artifactAttId }
                }
                if (alreadyPresent) return@update state
                state.copy(
                    messages = state.messages.map { msg ->
                        if (msg.id == msgId) msg.copy(blocks = msg.blocks + artifactBlock) else msg
                    },
                )
            }
        }
    }
}

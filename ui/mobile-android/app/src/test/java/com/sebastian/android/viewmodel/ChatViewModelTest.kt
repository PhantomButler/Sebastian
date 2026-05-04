package com.sebastian.android.viewmodel

import android.content.ContentResolver
import android.content.Context
import app.cash.turbine.test
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.ApprovalSnapshot
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.AttachmentArtifact
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ToolStatus
import com.sebastian.android.data.remote.SseEnvelope
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Before
import org.junit.Test
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.mockito.kotlin.any
import org.mockito.kotlin.anyOrNull
import org.mockito.kotlin.doSuspendableAnswer
import org.mockito.kotlin.eq
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.times
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever
import com.sebastian.android.viewmodel.ChatUiEffect
import java.util.UUID

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {

    private lateinit var chatRepository: ChatRepository
    private lateinit var sessionRepository: SessionRepository
    private lateinit var settingsRepository: SettingsRepository
    private lateinit var agentRepository: AgentRepository
    private lateinit var networkMonitor: NetworkMonitor
    private lateinit var viewModel: ChatViewModel
    private lateinit var appContext: Context
    private val dispatcher = StandardTestDispatcher()
    private val sseFlow = MutableSharedFlow<SseEnvelope>(extraBufferCapacity = 64)
    private val serverUrlFlow = MutableStateFlow("http://test.local:8823")
    private val onlineFlow = MutableStateFlow(true)

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        chatRepository = mock()
        sessionRepository = mock()
        settingsRepository = mock()
        agentRepository = mock()
        networkMonitor = mock()
        appContext = mock()
        val contentResolver: ContentResolver = mock()
        whenever(appContext.contentResolver).thenReturn(contentResolver)
        whenever(networkMonitor.isOnline).thenReturn(onlineFlow)
        whenever(settingsRepository.serverUrl).thenReturn(serverUrlFlow)
        whenever(settingsRepository.activeSoul).thenReturn(flowOf(""))
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenReturn(sseFlow)
        whenever(chatRepository.globalStream(any(), any())).thenReturn(flowOf())
        runBlocking {
            whenever(settingsRepository.readServerUrl()).thenReturn("http://test.local:8823")
            whenever(settingsRepository.readActiveSoul()).thenReturn("")
            whenever(chatRepository.sendTurn(any(), any(), any())).thenReturn(Result.success("s1"))
            whenever(chatRepository.grantApproval(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.denyApproval(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.cancelTurn(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.getMessages(any())).thenReturn(Result.success(emptyList()))
            whenever(chatRepository.getTodos(any())).thenReturn(Result.success(emptyList()))
        }
        viewModel = ChatViewModel(appContext, chatRepository, sessionRepository, settingsRepository, agentRepository, networkMonitor, dispatcher)
        viewModel.clock = { dispatcher.scheduler.currentTime }
        dispatcher.scheduler.advanceTimeBy(200)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    /**
     * Wraps [runTest] so that the ViewModel's infinite delta-flusher coroutine
     * (`while(true) { delay(50) }`) is cancelled before [runTest]'s internal
     * `advanceUntilIdle` cleanup, which would otherwise spin forever.
     */
    private fun vmTest(testBody: suspend TestScope.() -> Unit) = runTest(dispatcher) {
        try {
            testBody()
        } finally {
            viewModel.viewModelScope.cancel()
        }
    }

    /** Activate a session so SSE collection starts. Call before `test {}`. */
    private fun activateSession(sessionId: String = "s1") {
        viewModel.switchSession(sessionId)
        dispatcher.scheduler.advanceTimeBy(200)
    }

    /** Convenience wrapper: emit a StreamEvent into sseFlow wrapped in SseEnvelope. */
    private suspend fun emitEvent(event: StreamEvent) {
        sseFlow.emit(SseEnvelope(eventId = null, event = event))
    }

    @Test
    fun `initial state is IDLE_EMPTY`() = vmTest {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(ComposerState.IDLE_EMPTY, state.composerState)
            assertTrue(state.messages.isEmpty())
        }
    }

    @Test
    fun `text_block_start creates new streaming TextBlock`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem() // post-session state

            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            val assistantMsg = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
            assertFalse(assistantMsg == null)
            val block = assistantMsg!!.blocks.find { it.blockId == "b0_0" }
            assertTrue(block is ContentBlock.TextBlock)
            assertFalse((block as ContentBlock.TextBlock).done)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `text_delta appends to TextBlock`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            emitEvent(StreamEvent.TextDelta("s1", "b0_0", "好的"))
            emitEvent(StreamEvent.TextDelta("s1", "b0_0", "，我来帮你"))
            dispatcher.scheduler.advanceTimeBy(200)

            var found = false
            while (!found) {
                val state = awaitItem()
                val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                    ?.blocks?.find { it.blockId == "b0_0" }
                if (block is ContentBlock.TextBlock && block.text.contains("我来帮你")) {
                    found = true
                    assertEquals("好的，我来帮你", block.text)
                }
            }
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `text_block_stop marks block as done`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            emitEvent(StreamEvent.TextDelta("s1", "b0_0", "完成"))
            emitEvent(StreamEvent.TextBlockStop("s1", "b0_0"))
            dispatcher.scheduler.advanceTimeBy(200)

            var found = false
            while (!found) {
                val state = awaitItem()
                val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                    ?.blocks?.find { it.blockId == "b0_0" }
                if (block is ContentBlock.TextBlock && block.done) {
                    found = true
                }
            }
            assertTrue(found)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `thinking_block_start creates ThinkingBlock`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.ThinkingBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                ?.blocks?.find { it.blockId == "b0_0" }
            assertTrue(block is ContentBlock.ThinkingBlock)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `composerState becomes STREAMING during text block`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            assertEquals(ComposerState.STREAMING, state.composerState)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `composerState returns to IDLE_EMPTY after turn_response`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            emitEvent(StreamEvent.TextBlockStop("s1", "b0_0"))
            emitEvent(StreamEvent.TurnResponse("s1", "完成"))
            dispatcher.scheduler.advanceTimeBy(200)

            var found = false
            while (!found) {
                val state = awaitItem()
                if (state.composerState == ComposerState.IDLE_EMPTY) found = true
            }
            assertTrue(found)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `sendMessage adds user message and sets composerState PENDING`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial

            viewModel.sendMessage("你好")
            dispatcher.scheduler.advanceTimeBy(50)

            val state = awaitItem()
            assertEquals(ComposerState.PENDING, state.composerState)
            assertEquals(AgentAnimState.PENDING, state.agentAnimState)
            val userMsg = state.messages.lastOrNull { it.role == MessageRole.USER }
            assertTrue(userMsg != null)
            assertEquals("你好", userMsg!!.text)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `clearError clears error from uiState`() {
        // Cancel old ViewModel's infinite flusher before creating a new one
        viewModel.viewModelScope.cancel()
        // Anonymous fake: Mockito cannot reliably return Kotlin Result (inline class)
        val failingRepo = object : ChatRepository {
            override fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String?) = sseFlow
            override fun globalStream(baseUrl: String, lastEventId: String?) = flowOf<SseEnvelope>()
            override suspend fun getMessages(sessionId: String) = Result.success(emptyList<Message>())
            override suspend fun sendTurn(sessionId: String?, content: String, attachmentIds: List<String>) =
                Result.failure<String>(RuntimeException("网络错误"))
            override suspend fun sendSessionTurn(sessionId: String, content: String, attachmentIds: List<String>) =
                Result.success(Unit)
            override suspend fun cancelTurn(sessionId: String) = Result.success(Unit)
            override suspend fun grantApproval(approvalId: String) = Result.success(Unit)
            override suspend fun denyApproval(approvalId: String) = Result.success(Unit)
            override suspend fun getPendingApprovals() = Result.success(emptyList<ApprovalSnapshot>())
            override suspend fun getTodos(sessionId: String) = Result.success(emptyList<com.sebastian.android.data.model.TodoItem>())
            override suspend fun uploadAttachment(pending: com.sebastian.android.data.model.PendingAttachment, contentResolver: android.content.ContentResolver): Result<com.sebastian.android.data.model.PendingAttachment> =
                Result.failure(UnsupportedOperationException())
        }
        viewModel = ChatViewModel(appContext, failingRepo, sessionRepository, settingsRepository, agentRepository, networkMonitor, dispatcher)
        viewModel.clock = { dispatcher.scheduler.currentTime }
        dispatcher.scheduler.advanceTimeBy(200)

        vmTest {
            viewModel.uiState.test {
                awaitItem() // initial

                viewModel.sendMessage("test")
                dispatcher.scheduler.advanceTimeBy(200)

                // Consume states until we find the error
                var errorState: ChatUiState? = null
                while (errorState?.error == null) {
                    errorState = awaitItem()
                }
                assertEquals("网络错误", errorState!!.error)

                viewModel.clearError()
                dispatcher.scheduler.advanceTimeBy(200)

                val clearedState = awaitItem()
                assertNull(clearedState.error)
                cancelAndIgnoreRemainingEvents()
            }
        }
    }

    @Test
    fun `cancelTurn sets state CANCELLING and calls repository`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()

            viewModel.cancelTurn()
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            assertEquals(ComposerState.CANCELLING, state.composerState)
            runBlocking { verify(chatRepository).cancelTurn("s1") }
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `isOffline becomes true when network is lost`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial

            onlineFlow.emit(false)
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            assertTrue(state.isOffline)
        }
    }

    @Test
    fun `switchSession clears messages and sets activeSessionId`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem() // post-activation state

            // Pre-populate a message via SSE
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceTimeBy(200)
            awaitItem() // streaming state

            viewModel.switchSession("session-42")
            dispatcher.scheduler.advanceTimeBy(200)

            var found = false
            while (!found) {
                val state = awaitItem()
                if (state.activeSessionId == "session-42") {
                    found = true
                    assertTrue(state.messages.isEmpty())
                }
            }
            assertTrue(found)
            cancelAndIgnoreRemainingEvents()
        }
    }

    /**
     * 回归保护：后端 `block_id_prefix=f"b{iteration}_"` 跨 turn 重复（turn1/turn2 都会发 `b0_1`），
     * toggleToolBlock 必须按 (msgId, blockId) 精确定位，不能把两个 turn 的 tool card 一起翻。
     */
    @Test
    fun `toggleToolBlock scoped by msgId does not collide across turns`() = vmTest {
        activateSession()

        // Turn 1：tool block blockId=b0_1
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "b0_1", "t1", "Bash"))
        emitEvent(StreamEvent.ToolBlockStop("s1", "b0_1", "t1", "Bash", """{"command":"ls"}"""))
        emitEvent(StreamEvent.ToolExecuted("s1", "t1", "Bash", "ok"))
        emitEvent(StreamEvent.TurnResponse("s1", ""))
        dispatcher.scheduler.advanceTimeBy(200)

        // Turn 2：同样的 blockId=b0_1（后端 iteration 重置）
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "b0_1", "t2", "Bash"))
        emitEvent(StreamEvent.ToolBlockStop("s1", "b0_1", "t2", "Bash", """{"command":"pwd"}"""))
        emitEvent(StreamEvent.ToolExecuted("s1", "t2", "Bash", "ok"))
        emitEvent(StreamEvent.TurnResponse("s1", ""))
        dispatcher.scheduler.advanceTimeBy(200)

        val assistants = viewModel.uiState.value.messages.filter { it.role == MessageRole.ASSISTANT }
        assertEquals(2, assistants.size)
        val msg1 = assistants[0]
        val msg2 = assistants[1]
        // 两条消息各自持有一个 blockId 相同的 ToolBlock
        val block1 = msg1.blocks.first { it is ContentBlock.ToolBlock } as ContentBlock.ToolBlock
        val block2 = msg2.blocks.first { it is ContentBlock.ToolBlock } as ContentBlock.ToolBlock
        assertEquals("b0_1", block1.blockId)
        assertEquals("b0_1", block2.blockId)
        assertFalse(block1.expanded)
        assertFalse(block2.expanded)

        viewModel.toggleToolBlock(msg1.id, "b0_1")
        dispatcher.scheduler.advanceTimeBy(50)

        val after = viewModel.uiState.value
        val after1 = after.messages.first { it.id == msg1.id }
            .blocks.first { it is ContentBlock.ToolBlock } as ContentBlock.ToolBlock
        val after2 = after.messages.first { it.id == msg2.id }
            .blocks.first { it is ContentBlock.ToolBlock } as ContentBlock.ToolBlock
        assertTrue(after1.expanded)
        assertFalse(after2.expanded)
    }

    // ── onAppStart：回前台 chat reconcile ─────────────────────────────────────

    @Test
    fun `onAppStart in IDLE triggers switchSession re-hydrate`() = vmTest {
        activateSession()  // getMessages 调用一次
        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(200)
        // activateSession + onAppStart = 两次 getMessages
        runBlocking { verify(chatRepository, times(2)).getMessages("s1") }
    }

    @Test
    fun `onAppStart during STREAMING skips reconcile`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem()  // post-activation state
            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceTimeBy(200)

            // 等状态变 STREAMING
            var streaming = false
            while (!streaming) {
                val state = awaitItem()
                if (state.composerState == ComposerState.STREAMING) streaming = true
            }

            viewModel.onAppStart()
            dispatcher.scheduler.advanceTimeBy(200)

            // 仅 activateSession 那次，onAppStart 不再触发
            runBlocking { verify(chatRepository, times(1)).getMessages("s1") }
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `onAppStart when offline skips reconcile`() = vmTest {
        activateSession()
        onlineFlow.emit(false)
        dispatcher.scheduler.advanceTimeBy(200)

        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(200)

        runBlocking { verify(chatRepository, times(1)).getMessages("s1") }
    }

    @Test
    fun `onAppStart with null activeSessionId does not fetch`() = vmTest {
        // 不 activate 任何 session
        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(200)

        runBlocking { verify(chatRepository, never()).getMessages(any()) }
    }

    @Test
    fun `onAppStart in IDLE_READY skips reconcile`() = vmTest {
        activateSession()  // getMessages #1
        // 构造 IDLE_READY：发送失败后 ViewModel 会把 composerState 拨到 IDLE_READY + 保留 error
        runBlocking {
            whenever(chatRepository.sendTurn(any(), any(), any()))
                .thenReturn(Result.failure(RuntimeException("boom")))
        }
        viewModel.sendMessage("半截话")
        dispatcher.scheduler.advanceTimeBy(200)
        assertEquals(ComposerState.IDLE_READY, viewModel.uiState.value.composerState)

        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(200)

        // 仅 activateSession 那次
        runBlocking { verify(chatRepository, times(1)).getMessages("s1") }
    }

    @Test
    fun `TurnCancelled event resets composerState to IDLE_EMPTY and agentAnimState to IDLE`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem() // post-session state

            emitEvent(StreamEvent.TurnReceived("s1"))
            emitEvent(StreamEvent.TextBlockStart("s1", "b0_0"))
            emitEvent(StreamEvent.TextDelta("s1", "b0_0", "hello"))
            dispatcher.scheduler.advanceTimeBy(200)
            // Consume intermediate states until we see STREAMING
            var seenStreaming = false
            while (!seenStreaming) {
                val state = awaitItem()
                if (state.composerState == ComposerState.STREAMING) seenStreaming = true
            }

            emitEvent(StreamEvent.TurnCancelled("s1", "hello"))
            dispatcher.scheduler.advanceTimeBy(200)

            var found = false
            while (!found) {
                val state = awaitItem()
                if (state.composerState == ComposerState.IDLE_EMPTY && state.agentAnimState == AgentAnimState.IDLE) {
                    found = true
                }
            }
            assertTrue(found)

            // Verify currentAssistantMessageId is cleared: a TextDelta emitted after
            // TurnCancelled should be dropped (no active message to append to).
            // Capture the message list snapshot right after cancel settled.
            val snapshotAfterCancel = viewModel.uiState.value.messages
            val assistantTextAfterCancel = snapshotAfterCancel
                .lastOrNull { it.role == MessageRole.ASSISTANT }
                ?.blocks
                ?.filterIsInstance<ContentBlock.TextBlock>()
                ?.joinToString("") { it.text }
                ?: ""

            emitEvent(StreamEvent.TextDelta("s1", "b0", " extra"))
            dispatcher.scheduler.advanceTimeBy(200)

            // No new state item should carry " extra" — any emitted item must not
            // contain text beyond what was present right after TurnCancelled.
            val snapshotAfterOrphanDelta = viewModel.uiState.value.messages
            val assistantTextAfterDelta = snapshotAfterOrphanDelta
                .lastOrNull { it.role == MessageRole.ASSISTANT }
                ?.blocks
                ?.filterIsInstance<ContentBlock.TextBlock>()
                ?.joinToString("") { it.text }
                ?: ""
            assertFalse(
                "Orphan TextDelta after TurnCancelled must be dropped",
                assistantTextAfterDelta.contains(" extra")
            )
            assertEquals(
                "Assistant message text must not grow after TurnCancelled",
                assistantTextAfterCancel,
                assistantTextAfterDelta
            )

            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `sendMessage enters PENDING and stays PENDING through sendTurn REST success`() = vmTest {
        activateSession()
        viewModel.uiState.test {
            awaitItem() // post-session state

            viewModel.sendMessage("hi")
            dispatcher.scheduler.advanceTimeBy(50)

            val immediate = awaitItem()
            assertEquals(ComposerState.PENDING, immediate.composerState)
            assertEquals(AgentAnimState.PENDING, immediate.agentAnimState)

            dispatcher.scheduler.advanceTimeBy(500) // let sendTurn REST finish
            // State should STILL be PENDING after REST returns — not reset to IDLE
            expectNoEvents()
        }
    }

    @Test
    fun `first TextBlockStart transitions PENDING to STREAMING`() = vmTest {
        activateSession()
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(500) // let REST finish

        viewModel.uiState.test {
            awaitItem() // current PENDING state

            emitEvent(StreamEvent.TurnReceived("s1"))
            dispatcher.scheduler.advanceTimeBy(50)
            expectNoEvents() // TurnReceived should NOT change state

            emitEvent(StreamEvent.TextBlockStart("s1", "b0"))
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            assertEquals(ComposerState.STREAMING, state.composerState)
            assertEquals(AgentAnimState.STREAMING, state.agentAnimState)
        }
    }

    @Test
    fun `cancelTurn with null activeSessionId cancels sendTurnJob and resets to IDLE_READY`() = vmTest {
        // No active session initially — simulates first ever message
        // Mock sendTurn to hang so we can cancel while PENDING
        whenever(chatRepository.sendTurn(anyOrNull(), any(), any())).doSuspendableAnswer {
            kotlinx.coroutines.delay(30_000)
            Result.success("s1")
        }

        viewModel.uiState.test {
            awaitItem() // initial state

            viewModel.sendMessage("hi")
            dispatcher.scheduler.advanceTimeBy(50)

            val pending = awaitItem()
            assertEquals(ComposerState.PENDING, pending.composerState)
            // Provisional session: activeSessionId is now the client-generated UUID (not null)
            assertFalse("provisional session id must be set", pending.activeSessionId == null)

            viewModel.cancelTurn()
            dispatcher.scheduler.advanceTimeBy(50)

            val afterCancel = awaitItem()
            assertEquals(ComposerState.IDLE_READY, afterCancel.composerState)
            assertEquals(AgentAnimState.IDLE, afterCancel.agentAnimState)
            // User bubble is preserved
            assertTrue(afterCancel.messages.any { it.role == MessageRole.USER })
        }
    }

    // ── PENDING 15s 前台累计超时 ──────────────────────────────────────────────

    @Test
    fun `pending timeout emits toast after 15s foreground`() = vmTest {
        activateSession()
        val toasts = mutableListOf<String>()
        val collectJob = launch {
            viewModel.toastEvents.collect { toasts.add(it) }
        }

        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(50) // PENDING set

        // 14s — no toast yet
        dispatcher.scheduler.advanceTimeBy(14_000)
        assertTrue("No toast before 15s", toasts.isEmpty())

        // 1.1s more — total 15.1s > 15s
        dispatcher.scheduler.advanceTimeBy(1_100)
        assertEquals("Toast must fire after 15s", 1, toasts.size)
        assertTrue(toasts[0].contains("响应较慢"))

        collectJob.cancel()
    }

    @Test
    fun `pending timeout is cancelled when SSE event arrives`() = vmTest {
        activateSession()
        val toasts = mutableListOf<String>()
        val collectJob = launch {
            viewModel.toastEvents.collect { toasts.add(it) }
        }

        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(500) // REST finishes

        // SSE event arrives — must cancel the timeout
        emitEvent(StreamEvent.TurnReceived("s1"))
        dispatcher.scheduler.advanceTimeBy(20_000) // well past 15s

        assertTrue("No toast when SSE event cancels timeout", toasts.isEmpty())

        collectJob.cancel()
    }

    @Test
    fun `pending timeout pauses on app stop and resumes on app start`() = vmTest {
        activateSession()
        val toasts = mutableListOf<String>()
        val collectJob = launch {
            viewModel.toastEvents.collect { toasts.add(it) }
        }

        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(50)

        // 10s foreground, then background
        dispatcher.scheduler.advanceTimeBy(10_000)
        viewModel.onAppStop()
        assertTrue("No toast at 10s", toasts.isEmpty())

        // 30s in background — must NOT fire (timer paused)
        dispatcher.scheduler.advanceTimeBy(30_000)
        assertTrue("No toast while backgrounded", toasts.isEmpty())

        // Return to foreground — timer resumes with 5s remaining
        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(4_900)
        assertTrue("No toast before remaining 5s", toasts.isEmpty())

        dispatcher.scheduler.advanceTimeBy(200) // crosses 15s
        assertEquals("Toast fires after total 15s foreground", 1, toasts.size)

        collectJob.cancel()
    }

    // ── onAppStart PENDING 分支 ────────────────────────────────────────────────

    @Test
    fun `onAppStart in PENDING with completed assistant message resets to IDLE_EMPTY`() = vmTest {
        activateSession()
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(500)
        // Now in PENDING

        // Mock getMessages to return a completed assistant turn
        whenever(chatRepository.getMessages("s1")).thenReturn(
            Result.success(listOf(
                Message(
                    id = "m1",
                    sessionId = "s1",
                    role = MessageRole.USER,
                    text = "hi",
                ),
                Message(
                    id = "m2",
                    sessionId = "s1",
                    role = MessageRole.ASSISTANT,
                    blocks = listOf(ContentBlock.TextBlock(blockId = "b0", text = "done", done = true)),
                ),
            ))
        )

        viewModel.onAppStop()
        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(300)

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(ComposerState.IDLE_EMPTY, state.composerState)
            assertEquals(AgentAnimState.IDLE, state.agentAnimState)
        }
    }

    @Test
    fun `onAppStart in PENDING with only user message stays PENDING`() = vmTest {
        activateSession()
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(500)

        whenever(chatRepository.getMessages("s1")).thenReturn(
            Result.success(listOf(
                Message(
                    id = "m1",
                    sessionId = "s1",
                    role = MessageRole.USER,
                    text = "hi",
                ),
            ))
        )

        viewModel.onAppStop()
        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(300)

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(ComposerState.PENDING, state.composerState)
        }
    }

    // ── Task 7: provisional session + SSE cursor ──────────────────────────────

    @Test
    fun `new main session generates client id before sse and sendTurn`() = vmTest {
        val capturedStreamIds = mutableListOf<String?>()
        // Install a fixed client session id so we can verify SSE + sendTurn use the same one
        val fixedClientId = "client-uuid-test-123"
        viewModel.sessionIdProvider = { fixedClientId }
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenAnswer { inv ->
            capturedStreamIds.add(inv.getArgument(1))
            sseFlow
        }
        // sendTurn mock must return success with the fixedClientId (already set up in @Before as "s1",
        // but we override to return the client id so the provisional flow doesn't restart SSE)
        whenever(chatRepository.sendTurn(anyOrNull(), any(), any())).thenReturn(Result.success(fixedClientId))

        viewModel.sendMessage("hello")
        dispatcher.scheduler.advanceTimeBy(200)

        assertTrue("SSE must be started with a client session id", capturedStreamIds.isNotEmpty())
        val sseId = capturedStreamIds.last()
        assertEquals("SSE must use the client session id", fixedClientId, sseId)

        // activeSessionId is set to the client id (not null, not "pending")
        assertEquals("activeSessionId must be the client id", fixedClientId, viewModel.uiState.value.activeSessionId)

        // Verify sendTurn was called with the same client id
        runBlocking { verify(chatRepository).sendTurn(fixedClientId, "hello", emptyList()) }
    }

    @Test
    fun `new main session failure removes user bubble and clears active session`() = vmTest {
        whenever(chatRepository.sendTurn(anyOrNull(), any(), any())).thenReturn(
            Result.failure(RuntimeException("net error"))
        )

        viewModel.uiState.test {
            awaitItem() // initial

            viewModel.sendMessage("hello")
            dispatcher.scheduler.advanceTimeBy(200)

            var foundRollback = false
            while (!foundRollback) {
                val state = awaitItem()
                if (state.composerState == ComposerState.IDLE_EMPTY && state.activeSessionId == null) {
                    foundRollback = true
                    assertTrue("User bubble must be removed", state.messages.none { it.role == MessageRole.USER })
                }
            }
            assertTrue(foundRollback)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `new main session failure emits uiEffects for rollback`() = vmTest {
        whenever(chatRepository.sendTurn(anyOrNull(), any(), any())).thenReturn(
            Result.failure(RuntimeException("net error"))
        )

        val effects = mutableListOf<ChatUiEffect>()
        val job = launch { viewModel.uiEffects.collect { effects.add(it) } }

        viewModel.sendMessage("hello")
        dispatcher.scheduler.advanceTimeBy(200)

        assertTrue("Must emit RestoreComposerText", effects.any { it is ChatUiEffect.RestoreComposerText && (it as ChatUiEffect.RestoreComposerText).text == "hello" })
        assertTrue("Must emit ShowToast", effects.any { it is ChatUiEffect.ShowToast })

        job.cancel()
    }

    @Test
    fun `reconnect uses last delivered sse event id as cursor`() = vmTest {
        val capturedLastEventIds = mutableListOf<String?>()
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenAnswer { inv ->
            capturedLastEventIds.add(inv.getArgument(2))
            sseFlow
        }

        activateSession("s1")
        dispatcher.scheduler.advanceTimeBy(200)

        // Emit an envelope with eventId "7"
        sseFlow.emit(SseEnvelope(eventId = "7", event = StreamEvent.Unknown))
        dispatcher.scheduler.advanceTimeBy(100)

        // Trigger reconnect by switching and switching back
        viewModel.switchSession("other")
        dispatcher.scheduler.advanceTimeBy(100)
        viewModel.switchSession("s1")
        dispatcher.scheduler.advanceTimeBy(200)

        val lastCallForS1 = capturedLastEventIds.lastOrNull()
        assertEquals("Reconnect must use saved cursor", "7", lastCallForS1)
    }

    @Test
    fun `existing session with no prior events reconnects with null cursor`() = vmTest {
        val capturedLastEventIds = mutableListOf<String?>()
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenAnswer { inv ->
            capturedLastEventIds.add(inv.getArgument(2))
            sseFlow
        }

        activateSession("s1")
        dispatcher.scheduler.advanceTimeBy(200)

        // No events received — cursor should be null for reconnect
        val firstCallCursor = capturedLastEventIds.firstOrNull()
        assertNull("Existing session first connect should use null cursor", firstCallCursor)
    }

    @Test
    fun `sendMessage to existing session with SSE inactive reconnects with stored cursor`() = vmTest {
        val capturedLastEventIds = mutableListOf<String?>()
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenAnswer { inv ->
            capturedLastEventIds.add(inv.getArgument(2))
            sseFlow
        }

        activateSession("s1")
        dispatcher.scheduler.advanceTimeBy(200)

        // Emit an event with eventId "42" so cursor is stored
        sseFlow.emit(SseEnvelope(eventId = "42", event = StreamEvent.Unknown))
        dispatcher.scheduler.advanceTimeBy(100)

        // Stop SSE
        viewModel.onAppStop()
        dispatcher.scheduler.advanceTimeBy(100)

        // sendMessage on existing session "s1" — sendTurn returns "s1" (same id)
        viewModel.sendMessage("test")
        dispatcher.scheduler.advanceTimeBy(200)

        val lastCursor = capturedLastEventIds.lastOrNull()
        assertEquals("SSE reconnect after sendMessage must use stored cursor", "42", lastCursor)
    }

    @Test
    fun `sendAgentMessage to existing session with SSE inactive reconnects with stored cursor`() = vmTest {
        val capturedLastEventIds = mutableListOf<String?>()
        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenAnswer { inv ->
            capturedLastEventIds.add(inv.getArgument(2))
            sseFlow
        }
        runBlocking {
            whenever(chatRepository.sendSessionTurn(any(), any(), any())).thenReturn(Result.success(Unit))
        }

        activateSession("s1")
        dispatcher.scheduler.advanceTimeBy(200)

        // Emit an event with eventId "42" so cursor is stored
        sseFlow.emit(SseEnvelope(eventId = "42", event = StreamEvent.Unknown))
        dispatcher.scheduler.advanceTimeBy(100)

        // Stop SSE
        viewModel.onAppStop()
        dispatcher.scheduler.advanceTimeBy(100)

        // sendAgentMessage on existing session "s1"
        viewModel.sendAgentMessage("research", "test")
        dispatcher.scheduler.advanceTimeBy(200)

        val lastCursor = capturedLastEventIds.lastOrNull()
        assertEquals("SSE reconnect after sendAgentMessage must use stored cursor", "42", lastCursor)
    }

    // ── Task 8: provisional session for SubAgent ─────────────────────────────

    @Test
    fun `new agent session generates client id before sse and createAgentSession`() = vmTest {
        val capturedStreamIds = mutableListOf<String?>()
        val capturedCreateSessionIds = mutableListOf<String?>()

        whenever(chatRepository.sessionStream(any(), any(), anyOrNull())).thenAnswer { inv ->
            capturedStreamIds.add(inv.getArgument(1))
            sseFlow
        }
        whenever(sessionRepository.createAgentSession(any(), anyOrNull(), anyOrNull(), any())).thenReturn(
            Result.success(com.sebastian.android.data.model.Session(id = "agent-s1", title = "Test", agentType = "research"))
        )

        viewModel.sendAgentMessage("research", "find sources")
        dispatcher.scheduler.advanceTimeBy(200)

        // SSE started with non-null client session id
        assertTrue(capturedStreamIds.isNotEmpty())
        val sseId = capturedStreamIds.last()
        assertFalse("SSE session id must not be null", sseId == null)

        // createAgentSession received the same id
        runBlocking { verify(sessionRepository).createAgentSession(eq("research"), anyOrNull(), anyOrNull(), any()) }
    }

    @Test
    fun `new agent session failure removes user bubble and clears active session`() = vmTest {
        whenever(sessionRepository.createAgentSession(any(), anyOrNull(), anyOrNull(), any())).thenReturn(
            Result.failure(RuntimeException("server error"))
        )

        viewModel.uiState.test {
            awaitItem() // initial

            viewModel.sendAgentMessage("research", "hello")
            dispatcher.scheduler.advanceTimeBy(200)

            var foundRollback = false
            while (!foundRollback) {
                val state = awaitItem()
                if (state.composerState == ComposerState.IDLE_EMPTY && state.activeSessionId == null) {
                    foundRollback = true
                    assertTrue("User bubble must be removed on failure", state.messages.none { it.role == MessageRole.USER })
                }
            }
            assertTrue(foundRollback)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `new agent session failure emits uiEffects for rollback`() = vmTest {
        whenever(sessionRepository.createAgentSession(any(), anyOrNull(), anyOrNull(), any())).thenReturn(
            Result.failure(RuntimeException("server error"))
        )

        val effects = mutableListOf<ChatUiEffect>()
        val job = launch { viewModel.uiEffects.collect { effects.add(it) } }

        viewModel.sendAgentMessage("research", "find sources")
        dispatcher.scheduler.advanceTimeBy(200)

        assertTrue("Must emit RestoreComposerText", effects.any { it is ChatUiEffect.RestoreComposerText })
        assertTrue("Must emit ShowToast", effects.any { it is ChatUiEffect.ShowToast })

        job.cancel()
    }

    @Test
    fun `toggleSummaryBlock flips expanded state`() = vmTest {
        activateSession("s1")

        whenever(chatRepository.getMessages(any())).thenReturn(
            Result.success(listOf(
                com.sebastian.android.data.model.Message(
                    id = "msg-1",
                    sessionId = "s1",
                    role = com.sebastian.android.data.model.MessageRole.ASSISTANT,
                    blocks = listOf(
                        com.sebastian.android.data.model.ContentBlock.SummaryBlock(
                            blockId = "summary-1",
                            text = "Earlier content was compressed.",
                            expanded = false,
                        )
                    ),
                )
            ))
        )

        viewModel.switchSession("s1")
        dispatcher.scheduler.advanceTimeBy(300)

        val before = viewModel.uiState.value.messages
            .find { it.id == "msg-1" }
            ?.blocks?.single() as? com.sebastian.android.data.model.ContentBlock.SummaryBlock
        assertFalse("SummaryBlock must start collapsed", before?.expanded ?: true)

        viewModel.toggleSummaryBlock("msg-1", "summary-1")
        dispatcher.scheduler.advanceTimeBy(50)

        val after = viewModel.uiState.value.messages
            .find { it.id == "msg-1" }
            ?.blocks?.single() as? com.sebastian.android.data.model.ContentBlock.SummaryBlock
        assertTrue("SummaryBlock must be expanded after toggle", after?.expanded ?: false)
    }

    // ── Todo 状态 bug 修复测试 ─────────────────────────────────────────────────

    @Test
    fun `switch session clears todos immediately even when getTodos fails`() = vmTest {
        val todosS1 = listOf(com.sebastian.android.data.model.TodoItem("s1-task", "", "pending"))
        runBlocking {
            whenever(chatRepository.getTodos("s1")).thenReturn(Result.success(todosS1))
            whenever(chatRepository.getTodos("s2")).thenReturn(Result.failure(RuntimeException("network error")))
            whenever(chatRepository.getMessages(any())).thenReturn(Result.success(emptyList()))
        }

        viewModel.switchSession("s1")
        dispatcher.scheduler.advanceTimeBy(500)
        assertEquals(todosS1, viewModel.uiState.value.todos)

        viewModel.switchSession("s2")
        assertTrue(viewModel.uiState.value.todos.isEmpty())

        dispatcher.scheduler.advanceTimeBy(500)
        assertTrue(viewModel.uiState.value.todos.isEmpty())
    }

    @Test
    fun `todo_updated does not overwrite todos after session switch`() = vmTest {
        val todosS1 = listOf(com.sebastian.android.data.model.TodoItem("s1-task", "", "pending"))
        val todosS2 = listOf(com.sebastian.android.data.model.TodoItem("s2-task", "", "in_progress"))
        runBlocking {
            whenever(chatRepository.getTodos("s1")).thenReturn(Result.success(todosS1))
            whenever(chatRepository.getTodos("s2")).thenReturn(Result.success(todosS2))
            whenever(chatRepository.getMessages(any())).thenReturn(Result.success(emptyList()))
        }

        viewModel.switchSession("s1")
        dispatcher.scheduler.advanceTimeBy(500)
        assertEquals(todosS1, viewModel.uiState.value.todos)

        // Emit TodoUpdated for s1, then immediately switch to s2.
        // The TodoUpdated coroutine for s1 must not overwrite s2's todos.
        emitEvent(StreamEvent.TodoUpdated("s1", 1))
        viewModel.switchSession("s2")
        dispatcher.scheduler.advanceTimeBy(500)

        val finalState = viewModel.uiState.value
        assertEquals("s2", finalState.activeSessionId)
        assertEquals(todosS2, finalState.todos)
    }

    @Test
    fun `onAppStart in PENDING state fetches todos when turn is done`() = vmTest {
        val completedMsg = com.sebastian.android.data.model.Message(
            id = "m1",
            sessionId = "s1",
            role = MessageRole.ASSISTANT,
            blocks = listOf(
                com.sebastian.android.data.model.ContentBlock.TextBlock(
                    blockId = "b1",
                    text = "done",
                    done = true,
                )
            ),
        )
        val todos = listOf(com.sebastian.android.data.model.TodoItem("task", "", "completed"))
        runBlocking {
            whenever(chatRepository.getMessages("s1")).thenReturn(Result.success(listOf(completedMsg)))
            whenever(chatRepository.getTodos("s1")).thenReturn(Result.success(todos))
            whenever(chatRepository.sendTurn(any(), any(), any())).thenReturn(Result.success("s1"))
        }

        // 先 switchSession 让 activeSessionId = "s1"
        viewModel.switchSession("s1")
        dispatcher.scheduler.advanceTimeBy(500)

        // 发送消息让 composerState 进入 PENDING
        viewModel.sendMessage("hello")
        // 不 advance，让它停留在 PENDING

        // onAppStart：处于 PENDING，getMessages 返回已完成的 turn → 触发 getTodos
        viewModel.onAppStart()
        dispatcher.scheduler.advanceTimeBy(500)

        assertEquals(todos, viewModel.uiState.value.todos)
    }

    // ── Task 5: send_file artifact → ImageBlock / FileBlock ──────────────────

    @Test
    fun `send_file tool executed with image artifact replaces tool block`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_1", "send_file"))
        emitEvent(StreamEvent.ToolExecuted(
            sessionId = "s1",
            toolId = "toolu_1",
            name = "send_file",
            resultSummary = "已向用户发送图片 photo.png",
            artifact = AttachmentArtifact(
                kind = "image",
                attachmentId = "att-1",
                filename = "photo.png",
                mimeType = "image/png",
                sizeBytes = 123L,
                downloadUrl = "/api/v1/attachments/att-1",
                thumbnailUrl = "/api/v1/attachments/att-1/thumbnail",
            ),
        ))
        dispatcher.scheduler.advanceTimeBy(200)

        val blocks = viewModel.uiState.value.messages.last().blocks
        assertTrue(blocks.none { it is ContentBlock.ToolBlock })
        val image = blocks.filterIsInstance<ContentBlock.ImageBlock>().single()
        assertEquals("att-1", image.attachmentId)
    }

    @Test
    fun `duplicate send_file artifact event is idempotent`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_1", "send_file"))
        val artifact = AttachmentArtifact(
            kind = "image",
            attachmentId = "att-1",
            filename = "photo.png",
            mimeType = "image/png",
            sizeBytes = 123L,
            downloadUrl = "/api/v1/attachments/att-1",
        )
        // First event replaces ToolBlock; second (SSE replay) is deduped
        emitEvent(StreamEvent.ToolExecuted("s1", "toolu_1", "send_file", "sent", artifact))
        emitEvent(StreamEvent.ToolExecuted("s1", "toolu_1", "send_file", "sent", artifact))
        dispatcher.scheduler.advanceTimeBy(200)

        val blocks = viewModel.uiState.value.messages.last().blocks
        assertTrue(blocks.none { it is ContentBlock.ToolBlock })
        assertEquals(1, blocks.filterIsInstance<ContentBlock.ImageBlock>().size)
    }

    @Test
    fun `send_file artifact dropped when assistant message not yet materialized`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        // No ToolBlockStart → assistant message never added to state
        emitEvent(StreamEvent.ToolExecuted(
            sessionId = "s1",
            toolId = "toolu_1",
            name = "send_file",
            resultSummary = "sent",
            artifact = AttachmentArtifact(
                kind = "image",
                attachmentId = "att-99",
                filename = "img.png",
                mimeType = "image/png",
                sizeBytes = 100L,
                downloadUrl = "/api/v1/attachments/att-99",
            ),
        ))
        dispatcher.scheduler.runCurrent()

        // Spec: do not create a temporary message — history hydration handles the final state
        assertTrue(viewModel.uiState.value.messages.isEmpty())
    }

    @Test
    fun `send_file artifact appended when message exists but no matching tool block`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        // Another tool creates the assistant message
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-other", "toolu_other", "list_files"))
        // send_file executed without a corresponding ToolBlockStart
        emitEvent(StreamEvent.ToolExecuted(
            sessionId = "s1",
            toolId = "toolu_sf",
            name = "send_file",
            resultSummary = "sent",
            artifact = AttachmentArtifact(
                kind = "image",
                attachmentId = "att-5",
                filename = "img.png",
                mimeType = "image/png",
                sizeBytes = 100L,
                downloadUrl = "/api/v1/attachments/att-5",
            ),
        ))
        dispatcher.scheduler.runCurrent()

        val blocks = viewModel.uiState.value.messages.last().blocks
        assertTrue(blocks.any { it is ContentBlock.ToolBlock }) // list_files block still present
        val image = blocks.filterIsInstance<ContentBlock.ImageBlock>().single()
        assertEquals("att-5", image.attachmentId)
    }

    @Test
    fun `ToolFailed for send_file renders tool block as FAILED`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_sf", "send_file"))
        emitEvent(StreamEvent.ToolFailed(
            sessionId = "s1",
            toolId = "toolu_sf",
            name = "send_file",
            error = "File not found: /tmp/missing.png. Do not retry automatically.",
        ))
        dispatcher.scheduler.runCurrent()

        val blocks = viewModel.uiState.value.messages.last().blocks
        val tool = blocks.filterIsInstance<ContentBlock.ToolBlock>().single()
        assertEquals(ToolStatus.FAILED, tool.status)
        assertTrue(tool.error?.contains("not found") == true)
    }

    @Test
    fun `ToolRunning event updates ToolBlock displayName`() = vmTest {
        // Arrange: pre-insert a ToolBlock in PENDING state via ToolBlockStart
        val toolId = "toolu_test_dn"
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-1", toolId, "memory_save"))

        // Act
        emitEvent(
            StreamEvent.ToolRunning(
                sessionId = "s1",
                toolId = toolId,
                name = "memory_save",
                displayName = "Save Memory",
            )
        )
        dispatcher.scheduler.runCurrent()

        // Assert
        val block = viewModel.uiState.value.messages
            .flatMap { it.blocks }
            .filterIsInstance<ContentBlock.ToolBlock>()
            .first { it.toolId == toolId }
        assertEquals("Save Memory", block.displayName)
        assertEquals(ToolStatus.RUNNING, block.status)
    }

    @Test
    fun `ToolExecuted event updates ToolBlock displayName`() = vmTest {
        val toolId = "toolu_test_dn_executed"
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-2", toolId, "memory_save"))

        emitEvent(
            StreamEvent.ToolExecuted(
                sessionId = "s1",
                toolId = toolId,
                name = "memory_save",
                resultSummary = "saved",
                artifact = null,
                displayName = "Save Memory",
            )
        )
        dispatcher.scheduler.runCurrent()

        val block = viewModel.uiState.value.messages
            .flatMap { it.blocks }
            .filterIsInstance<ContentBlock.ToolBlock>()
            .first { it.toolId == toolId }
        assertEquals("Save Memory", block.displayName)
        assertEquals(ToolStatus.DONE, block.status)
    }

    @Test
    fun `ToolFailed event updates ToolBlock displayName`() = vmTest {
        val toolId = "toolu_test_dn_failed"
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-3", toolId, "memory_save"))

        emitEvent(
            StreamEvent.ToolFailed(
                sessionId = "s1",
                toolId = toolId,
                name = "memory_save",
                error = "timeout",
                displayName = "Save Memory",
            )
        )
        dispatcher.scheduler.runCurrent()

        val block = viewModel.uiState.value.messages
            .flatMap { it.blocks }
            .filterIsInstance<ContentBlock.ToolBlock>()
            .first { it.toolId == toolId }
        assertEquals("Save Memory", block.displayName)
        assertEquals(ToolStatus.FAILED, block.status)
    }

    @Test
    fun `send_file tool executed without artifact marks tool block done`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_1", "send_file"))
        emitEvent(StreamEvent.ToolExecuted("s1", "toolu_1", "send_file", "result summary", null))
        dispatcher.scheduler.advanceTimeBy(200)

        val blocks = viewModel.uiState.value.messages.last().blocks
        val tool = blocks.filterIsInstance<ContentBlock.ToolBlock>().single()
        assertEquals(ToolStatus.DONE, tool.status)
    }

    @Test
    fun `send_file tool executed with text_file artifact replaces tool block with file block`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_2", "send_file"))
        emitEvent(StreamEvent.ToolExecuted(
            sessionId = "s1",
            toolId = "toolu_2",
            name = "send_file",
            resultSummary = "已向用户发送文件 notes.md",
            artifact = AttachmentArtifact(
                kind = "text_file",
                attachmentId = "att-2",
                filename = "notes.md",
                mimeType = "text/markdown",
                sizeBytes = 500L,
                downloadUrl = "/api/v1/attachments/att-2",
                textExcerpt = "# Hello",
            ),
        ))
        dispatcher.scheduler.runCurrent()

        val blocks = viewModel.uiState.value.messages.last().blocks
        assertTrue(blocks.none { it is ContentBlock.ToolBlock })
        val file = blocks.filterIsInstance<ContentBlock.FileBlock>().single()
        assertEquals("att-2", file.attachmentId)
        assertEquals("# Hello", file.textExcerpt)
    }

    @Test
    fun `send_file tool executed with download artifact replaces tool block with file block`() = vmTest {
        activateSession()
        emitEvent(StreamEvent.TurnReceived("s1"))
        emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_download", "send_file"))
        emitEvent(StreamEvent.ToolExecuted(
            sessionId = "s1",
            toolId = "toolu_download",
            name = "send_file",
            resultSummary = "已向用户发送文件 report.pdf",
            artifact = AttachmentArtifact(
                kind = "download",
                attachmentId = "att-1",
                filename = "report.pdf",
                mimeType = "application/pdf",
                sizeBytes = 1234L,
                downloadUrl = "/api/v1/attachments/att-1",
            ),
        ))
        dispatcher.scheduler.runCurrent()

        val blocks = viewModel.uiState.value.messages.last().blocks
        assertTrue(blocks.none { it is ContentBlock.ToolBlock })
        val file = blocks.filterIsInstance<ContentBlock.FileBlock>().single()
        assertEquals("att-1", file.attachmentId)
        assertEquals("report.pdf", file.filename)
        assertEquals("application/pdf", file.mimeType)
        assertEquals(1234L, file.sizeBytes)
        assertEquals("http://test.local:8823/api/v1/attachments/att-1", file.downloadUrl)
        assertEquals(null, file.textExcerpt)
    }

    @Test
    fun `fetchInitialSoulIfNeeded keeps default activeSoulName when network fails`() = vmTest {
        // fetchActiveSoul fails with a network error; readActiveSoul() returns "" (from setup)
        whenever(settingsRepository.fetchActiveSoul()).thenReturn(Result.failure(RuntimeException("network error")))

        viewModel.viewModelScope.cancel()
        val vm = ChatViewModel(appContext, chatRepository, sessionRepository, settingsRepository, agentRepository, networkMonitor, dispatcher)
        try {
            dispatcher.scheduler.runCurrent()  // let coroutines settle

            // Default "Sebastian" must be preserved
            assertEquals("Sebastian", vm.uiState.value.activeSoulName)
        } finally {
            vm.viewModelScope.cancel()
        }
    }

    @Test
    fun `connectionFailed while PENDING resets composerState to IDLE_EMPTY`() = vmTest {
        // Cancel old ViewModel so we can install a throwing SSE flow
        viewModel.viewModelScope.cancel()

        // A shared flow whose collect throws immediately, simulating a connection failure
        val throwingFlow = kotlinx.coroutines.flow.flow<SseEnvelope> {
            throw RuntimeException("SSE connection lost")
        }

        val failingRepo = object : ChatRepository {
            override fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String?) =
                throwingFlow
            override fun globalStream(baseUrl: String, lastEventId: String?) = flowOf<SseEnvelope>()
            override suspend fun getMessages(sessionId: String) = Result.success(emptyList<Message>())
            override suspend fun sendTurn(sessionId: String?, content: String, attachmentIds: List<String>) =
                Result.success("s1")
            override suspend fun sendSessionTurn(sessionId: String, content: String, attachmentIds: List<String>) =
                Result.success(Unit)
            override suspend fun cancelTurn(sessionId: String) = Result.success(Unit)
            override suspend fun grantApproval(approvalId: String) = Result.success(Unit)
            override suspend fun denyApproval(approvalId: String) = Result.success(Unit)
            override suspend fun getPendingApprovals() = Result.success(emptyList<ApprovalSnapshot>())
            override suspend fun getTodos(sessionId: String) = Result.success(emptyList<com.sebastian.android.data.model.TodoItem>())
            override suspend fun uploadAttachment(pending: com.sebastian.android.data.model.PendingAttachment, contentResolver: android.content.ContentResolver): Result<com.sebastian.android.data.model.PendingAttachment> =
                Result.failure(UnsupportedOperationException())
        }

        viewModel = ChatViewModel(appContext, failingRepo, sessionRepository, settingsRepository, agentRepository, networkMonitor, dispatcher)
        viewModel.clock = { dispatcher.scheduler.currentTime }
        dispatcher.scheduler.advanceTimeBy(200)

        // Activate a session so SSE collection starts (and immediately fails)
        viewModel.switchSession("s1")
        dispatcher.scheduler.advanceTimeBy(200)

        // Manually force PENDING state to simulate sendMessage having been called
        // before the SSE failure is processed. We reuse sendMessage with a mock that hangs
        // so the REST hasn't returned yet when the SSE fails — but the simpler approach
        // is to directly update state and verify the connectionFailed handler resets it.
        //
        // Instead, test the realistic path: send a message (REST will succeed instantly),
        // then the SSE collector (which always throws) triggers connectionFailed.
        // After sendTurn returns, composerState stays PENDING until SSE events arrive —
        // the failing SSE sets connectionFailed=true and resets PENDING → IDLE_EMPTY.
        viewModel.sendMessage("hi")
        dispatcher.scheduler.advanceTimeBy(500)

        assertEquals(
            "connectionFailed while PENDING must reset composerState to IDLE_EMPTY",
            ComposerState.IDLE_EMPTY,
            viewModel.uiState.value.composerState,
        )
        assertTrue(
            "connectionFailed flag must be set",
            viewModel.uiState.value.connectionFailed,
        )
    }
}

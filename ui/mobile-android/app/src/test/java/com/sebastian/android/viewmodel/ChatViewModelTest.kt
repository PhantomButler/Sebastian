package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.local.MarkdownParser
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
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
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {

    private lateinit var chatRepository: ChatRepository
    private lateinit var sessionRepository: SessionRepository
    private lateinit var settingsRepository: SettingsRepository
    private lateinit var networkMonitor: NetworkMonitor
    private lateinit var markdownParser: MarkdownParser
    private lateinit var viewModel: ChatViewModel
    private val dispatcher = StandardTestDispatcher()
    private val sseFlow = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)
    private val serverUrlFlow = MutableStateFlow("http://test.local:8823")
    private val onlineFlow = MutableStateFlow(true)

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        chatRepository = mock()
        sessionRepository = mock()
        settingsRepository = mock()
        networkMonitor = mock()
        markdownParser = mock()
        whenever(markdownParser.parse(any())).thenAnswer { it.arguments[0] as String }
        whenever(networkMonitor.isOnline).thenReturn(onlineFlow)
        whenever(settingsRepository.serverUrl).thenReturn(serverUrlFlow)
        whenever(chatRepository.sessionStream(any(), any(), any())).thenReturn(sseFlow)
        whenever(chatRepository.globalStream(any(), any())).thenReturn(flowOf())
        runBlocking {
            whenever(chatRepository.sendTurn(any(), any(), any())).thenReturn(Result.success("s1"))
            whenever(chatRepository.grantApproval(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.denyApproval(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.cancelTurn(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.getMessages(any())).thenReturn(Result.success(emptyList()))
        }
        viewModel = ChatViewModel(chatRepository, sessionRepository, settingsRepository, networkMonitor, markdownParser, dispatcher)
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

            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
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
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "好的"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "，我来帮你"))
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
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "完成"))
            sseFlow.emit(StreamEvent.TextBlockStop("s1", "b0_0"))
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
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.ThinkingBlockStart("s1", "b0_0"))
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
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
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
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextBlockStop("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TurnResponse("s1", "完成"))
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
    fun `sendMessage adds user message and sets composerState SENDING`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial

            viewModel.sendMessage("你好")
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            assertEquals(ComposerState.SENDING, state.composerState)
            assertEquals(ScrollFollowState.FOLLOWING, state.scrollFollowState)
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
            override fun globalStream(baseUrl: String, lastEventId: String?) = flowOf<StreamEvent>()
            override suspend fun getMessages(sessionId: String) = Result.success(emptyList<Message>())
            override suspend fun sendTurn(sessionId: String?, content: String, effort: com.sebastian.android.data.model.ThinkingEffort) =
                Result.failure<String>(RuntimeException("网络错误"))
            override suspend fun sendSessionTurn(sessionId: String, content: String, effort: com.sebastian.android.data.model.ThinkingEffort) =
                Result.success(Unit)
            override suspend fun cancelTurn(sessionId: String) = Result.success(Unit)
            override suspend fun grantApproval(approvalId: String) = Result.success(Unit)
            override suspend fun denyApproval(approvalId: String) = Result.success(Unit)
        }
        viewModel = ChatViewModel(failingRepo, sessionRepository, settingsRepository, networkMonitor, markdownParser, dispatcher)
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
    fun `onUserScrolled sets scrollFollowState DETACHED`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial (FOLLOWING)

            viewModel.onUserScrolled()
            dispatcher.scheduler.advanceTimeBy(200)

            val state = awaitItem()
            assertEquals(ScrollFollowState.DETACHED, state.scrollFollowState)
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
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
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
}

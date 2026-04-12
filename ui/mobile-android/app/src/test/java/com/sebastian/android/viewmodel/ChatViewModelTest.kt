package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import kotlinx.coroutines.runBlocking
import org.mockito.kotlin.any
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {

    private lateinit var chatRepository: ChatRepository
    private lateinit var settingsRepository: SettingsRepository
    private lateinit var viewModel: ChatViewModel
    private val dispatcher = StandardTestDispatcher()
    private val sseFlow = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)
    private val serverUrlFlow = MutableStateFlow("http://test.local:8823")

    @Before
    fun setup() {
        chatRepository = mock()
        settingsRepository = mock()
        whenever(settingsRepository.serverUrl).thenReturn(serverUrlFlow)
        whenever(chatRepository.sessionStream(any(), any(), any())).thenReturn(sseFlow)
        whenever(chatRepository.globalStream(any(), any())).thenReturn(flowOf())
        runBlocking {
            whenever(chatRepository.sendTurn(any(), any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.grantApproval(any())).thenReturn(Result.success(Unit))
            whenever(chatRepository.denyApproval(any())).thenReturn(Result.success(Unit))
        }
        viewModel = ChatViewModel(chatRepository, settingsRepository, dispatcher)
    }

    @Test
    fun `initial state is IDLE_EMPTY`() = runTest(dispatcher) {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(ComposerState.IDLE_EMPTY, state.composerState)
            assertTrue(state.messages.isEmpty())
        }
    }

    @Test
    fun `text_block_start creates new streaming TextBlock`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial

            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            val assistantMsg = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
            assertFalse(assistantMsg == null)
            val block = assistantMsg!!.blocks.find { it.blockId == "b0_0" }
            assertTrue(block is ContentBlock.TextBlock)
            assertFalse((block as ContentBlock.TextBlock).done)
        }
    }

    @Test
    fun `text_delta appends to TextBlock`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "好的"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "，我来帮你"))
            dispatcher.scheduler.advanceUntilIdle()

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
        }
    }

    @Test
    fun `text_block_stop marks block as done`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextDelta("s1", "b0_0", "完成"))
            sseFlow.emit(StreamEvent.TextBlockStop("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

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
        }
    }

    @Test
    fun `thinking_block_start creates ThinkingBlock`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.ThinkingBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            val block = state.messages.lastOrNull { it.role == MessageRole.ASSISTANT }
                ?.blocks?.find { it.blockId == "b0_0" }
            assertTrue(block is ContentBlock.ThinkingBlock)
        }
    }

    @Test
    fun `composerState becomes STREAMING during text block`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            assertEquals(ComposerState.STREAMING, state.composerState)
        }
    }

    @Test
    fun `composerState returns to IDLE_EMPTY after turn_response`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.TurnReceived("s1"))
            sseFlow.emit(StreamEvent.TextBlockStart("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TextBlockStop("s1", "b0_0"))
            sseFlow.emit(StreamEvent.TurnResponse("s1", "完成"))
            dispatcher.scheduler.advanceUntilIdle()

            var found = false
            while (!found) {
                val state = awaitItem()
                if (state.composerState == ComposerState.IDLE_EMPTY) found = true
            }
            assertTrue(found)
        }
    }

    @Test
    fun `approval_requested creates pending approval`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem()
            sseFlow.emit(StreamEvent.ApprovalRequested("s1", "ap_1", "删除文件 foo.txt"))
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            assertEquals(1, state.pendingApprovals.size)
            assertEquals("ap_1", state.pendingApprovals[0].approvalId)
        }
    }

    @Test
    fun `sendMessage adds user message and sets composerState SENDING`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial

            viewModel.sendMessage("你好")
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            assertEquals(ComposerState.SENDING, state.composerState)
            assertEquals(ScrollFollowState.FOLLOWING, state.scrollFollowState)
            val userMsg = state.messages.lastOrNull { it.role == MessageRole.USER }
            assertTrue(userMsg != null)
            assertEquals("你好", userMsg!!.text)
        }
    }

    @Test
    fun `grantApproval calls chatRepository grantApproval`() = runTest(dispatcher) {
        viewModel.grantApproval("ap_42")
        dispatcher.scheduler.advanceUntilIdle()

        runBlocking { verify(chatRepository).grantApproval("ap_42") }
    }

    @Test
    fun `clearError clears error from uiState`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial

            // Inject an error via sendMessage failure
            runBlocking {
                whenever(chatRepository.sendTurn(any(), any()))
                    .thenReturn(Result.failure(RuntimeException("网络错误")))
            }
            viewModel.sendMessage("test")
            dispatcher.scheduler.advanceUntilIdle()

            // Consume SENDING state
            awaitItem()
            // Consume error state
            val errorState = awaitItem()
            assertEquals("网络错误", errorState.error)

            viewModel.clearError()
            dispatcher.scheduler.advanceUntilIdle()

            val clearedState = awaitItem()
            assertNull(clearedState.error)
        }
    }

    @Test
    fun `onUserScrolled sets scrollFollowState DETACHED`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial (FOLLOWING)

            viewModel.onUserScrolled()
            dispatcher.scheduler.advanceUntilIdle()

            val state = awaitItem()
            assertEquals(ScrollFollowState.DETACHED, state.scrollFollowState)
        }
    }
}

package com.sebastian.android.viewmodel

import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.local.NetworkMonitor
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelReconcileTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `replaceMessages overrides the current list`() = runTest(dispatcher) {
        val chatRepo: ChatRepository = mock()
        val sessionRepo: SessionRepository = mock()
        val settings: SettingsRepository = mock()
        val net: NetworkMonitor = mock()
        whenever(net.isOnline).thenReturn(flowOf(true))

        val vm = ChatViewModel(chatRepo, sessionRepo, settings, net, dispatcher)
        // Let init() (observeNetwork + startDeltaFlusher) get scheduled.
        dispatcher.scheduler.advanceTimeBy(100)

        val snapshot = listOf(
            Message(
                id = "m1",
                sessionId = "s1",
                role = MessageRole.USER,
                blocks = listOf(ContentBlock.TextBlock("b1", "hello")),
            ),
            Message(
                id = "m2",
                sessionId = "s1",
                role = MessageRole.ASSISTANT,
                blocks = listOf(ContentBlock.TextBlock("b2", "world")),
            ),
        )
        vm.replaceMessages(snapshot)

        assertEquals(listOf("m1", "m2"), vm.uiState.value.messages.map { it.id })

        // Cancel the infinite flusher so runTest can finish.
        vm.viewModelScope.cancel()
    }
}

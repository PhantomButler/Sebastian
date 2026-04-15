package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.ApprovalSnapshot
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.repository.ChatRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
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
class GlobalApprovalViewModelTest {

    private lateinit var chatRepository: ChatRepository
    private lateinit var sseDispatcher: GlobalSseDispatcher
    private val dispatcher = StandardTestDispatcher()
    private val eventsFlow = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        chatRepository = mock()
        sseDispatcher = mock()
        whenever(sseDispatcher.events).thenReturn(eventsFlow as SharedFlow<StreamEvent>)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `replaceAll upserts by approvalId without duplicating SSE-pushed items`() = runTest(dispatcher) {
        val vm = GlobalApprovalViewModel(chatRepository, sseDispatcher, dispatcher)
        advanceUntilIdle() // 让 init 里的 collect 先订阅 SharedFlow
        // SSE pushes approval a1 first
        eventsFlow.emit(
            StreamEvent.ApprovalRequested(
                approvalId = "a1",
                sessionId = "s1",
                agentType = "sebastian",
                toolName = "bash",
                toolInputJson = "{}",
                reason = "test",
            )
        )
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.approvals.size)

        // Server snapshot contains a1 (same id, updated reason) and a new a2
        vm.replaceAll(
            listOf(
                ApprovalSnapshot(
                    approvalId = "a1",
                    sessionId = "s1",
                    agentType = "sebastian",
                    toolName = "bash",
                    toolInputJson = "{}",
                    reason = "updated",
                ),
                ApprovalSnapshot(
                    approvalId = "a2",
                    sessionId = "s2",
                    agentType = "sebastian",
                    toolName = "bash",
                    toolInputJson = "{}",
                    reason = "snapshot-only",
                ),
            )
        )
        advanceUntilIdle()

        val approvals = vm.uiState.value.approvals
        assertEquals(2, approvals.size)
        assertEquals("updated", approvals.first { it.approvalId == "a1" }.reason)
        assertEquals("snapshot-only", approvals.first { it.approvalId == "a2" }.reason)
    }

    @Test
    fun `replaceAll removes items no longer in server snapshot`() = runTest(dispatcher) {
        val vm = GlobalApprovalViewModel(chatRepository, sseDispatcher, dispatcher)
        advanceUntilIdle() // 让 init 里的 collect 先订阅 SharedFlow
        eventsFlow.emit(
            StreamEvent.ApprovalRequested(
                approvalId = "a1",
                sessionId = "s1",
                agentType = "sebastian",
                toolName = "bash",
                toolInputJson = "{}",
                reason = "test",
            )
        )
        eventsFlow.emit(
            StreamEvent.ApprovalRequested(
                approvalId = "a2",
                sessionId = "s2",
                agentType = "sebastian",
                toolName = "bash",
                toolInputJson = "{}",
                reason = "test",
            )
        )
        advanceUntilIdle()
        assertEquals(2, vm.uiState.value.approvals.size)

        // Server snapshot only has a2
        vm.replaceAll(
            listOf(
                ApprovalSnapshot(
                    approvalId = "a2",
                    sessionId = "s2",
                    agentType = "sebastian",
                    toolName = "bash",
                    toolInputJson = "{}",
                    reason = "test",
                ),
            )
        )
        advanceUntilIdle()

        val approvals = vm.uiState.value.approvals
        assertEquals(1, approvals.size)
        assertEquals("a2", approvals[0].approvalId)
    }
}

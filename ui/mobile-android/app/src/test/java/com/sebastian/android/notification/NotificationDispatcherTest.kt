package com.sebastian.android.notification

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.argThat
import org.mockito.kotlin.eq
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class NotificationDispatcherTest {

    private fun matchNotification(channelId: String, title: String) = argThat<NotificationSpec> {
        this.channelId == channelId && this.title == title
    }

    private fun buildSse(
        upstream: MutableSharedFlow<StreamEvent>,
        dispatcher: kotlinx.coroutines.CoroutineDispatcher,
    ): GlobalSseDispatcher {
        val chatRepo = mock<ChatRepository>()
        val settings = mock<SettingsRepository>()
        whenever(settings.serverUrl).thenReturn(MutableStateFlow("http://x"))
        whenever(chatRepo.globalStream("http://x", null)).thenReturn(upstream)
        return GlobalSseDispatcher(chatRepo, settings, dispatcher)
    }

    @Test
    fun `foreground suppresses approval notification`() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        val upstream = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)
        val sse = buildSse(upstream, dispatcher)
        val sink = mock<NotificationSink>()
        val scope = TestScope(dispatcher)

        val sut = NotificationDispatcher(
            sseDispatcher = sse,
            sink = sink,
            foregroundChecker = { true },
            dispatcher = dispatcher,
        )
        sse.start(scope)
        sut.start(scope)
        testScheduler.advanceUntilIdle()

        upstream.emit(
            StreamEvent.ApprovalRequested(
                sessionId = "s1",
                approvalId = "a1",
                agentType = "sebastian",
                toolName = "shell",
                toolInputJson = "{}",
                reason = "run",
            )
        )
        testScheduler.advanceUntilIdle()

        verify(sink, never()).notify(any(), any())
        sut.stop()
        sse.stop()
    }

    @Test
    fun `background approval emits heads up notification`() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        val upstream = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)
        val sse = buildSse(upstream, dispatcher)
        val sink = mock<NotificationSink>()
        val scope = TestScope(dispatcher)

        val sut = NotificationDispatcher(
            sseDispatcher = sse,
            sink = sink,
            foregroundChecker = { false },
            dispatcher = dispatcher,
        )
        sse.start(scope)
        sut.start(scope)
        testScheduler.advanceUntilIdle()

        upstream.emit(
            StreamEvent.ApprovalRequested(
                sessionId = "s1",
                approvalId = "a1",
                agentType = "sebastian",
                toolName = "shell",
                toolInputJson = "{}",
                reason = "run",
            )
        )
        testScheduler.advanceUntilIdle()

        verify(sink).notify(
            eq("a1".hashCode()),
            matchNotification(NotificationChannels.APPROVAL, "shell"),
        )
        sut.stop()
        sse.stop()
    }

    @Test
    fun `approval granted cancels prior notification`() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        val upstream = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)
        val sse = buildSse(upstream, dispatcher)
        val sink = mock<NotificationSink>()
        val scope = TestScope(dispatcher)

        val sut = NotificationDispatcher(
            sseDispatcher = sse,
            sink = sink,
            foregroundChecker = { false },
            dispatcher = dispatcher,
        )
        sse.start(scope)
        sut.start(scope)
        testScheduler.advanceUntilIdle()

        upstream.emit(StreamEvent.ApprovalGranted("a1"))
        testScheduler.advanceUntilIdle()

        verify(sink).cancel(eq("a1".hashCode()))
        sut.stop()
        sse.stop()
    }
}

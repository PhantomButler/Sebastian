package com.sebastian.android.data.repository

import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.SseClient
import com.sebastian.android.data.remote.dto.MessageDto
import com.sebastian.android.data.remote.dto.SessionDetailResponse
import com.sebastian.android.data.remote.dto.SessionDto
import com.sebastian.android.data.remote.dto.TimelineItemDto
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import org.mockito.kotlin.eq

class ChatRepositoryImplTest {

    private val sseClient = mock(SseClient::class.java)
    private val settingsRepository = mock(SettingsRepository::class.java).also {
        `when`(it.serverUrl).thenReturn(flowOf("http://10.0.2.2:8823"))
    }

    private fun makeSessionDto(id: String = "sess-1") = SessionDto(
        id = id,
        title = "Test",
        agentType = "sebastian",
    )

    private fun makeTimelineItem(
        sessionId: String = "sess-1",
        seq: Long = 1L,
        kind: String = "user_message",
        content: String = "hello",
    ) = TimelineItemDto(
        id = "item-$seq",
        sessionId = sessionId,
        seq = seq,
        kind = kind,
        content = content,
    )

    private fun makeMessageDto(role: String = "user", content: String = "hi") =
        MessageDto(role = role, content = content)

    // ── 1. include_archived=true 必须包含在请求中 ──────────────────────────────

    @Test
    fun `getMessagesCallsIncludeArchivedTrue`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.getSession(eq("sess-1"), eq(true))).thenReturn(
            SessionDetailResponse(
                session = makeSessionDto("sess-1"),
                messages = emptyList(),
                timelineItems = emptyList(),
            )
        )
        val repo = ChatRepositoryImpl(api, sseClient, settingsRepository)

        repo.getMessages("sess-1")

        verify(api).getSession(eq("sess-1"), eq(true))
    }

    // ── 2. timelineItems が空でないときは timeline から変換すること ──────────

    @Test
    fun `getMessagesUsesTimelineWhenPresent`() = runTest {
        val api = mock(ApiService::class.java)
        val timelineItem = makeTimelineItem(sessionId = "sess-2", seq = 1L, kind = "user_message", content = "from timeline")
        `when`(api.getSession(eq("sess-2"), eq(true))).thenReturn(
            SessionDetailResponse(
                session = makeSessionDto("sess-2"),
                messages = listOf(makeMessageDto(content = "from legacy")),
                timelineItems = listOf(timelineItem),
            )
        )
        val repo = ChatRepositoryImpl(api, sseClient, settingsRepository)

        val result = repo.getMessages("sess-2")

        assertTrue(result.isSuccess)
        val messages = result.getOrThrow()
        assertEquals(1, messages.size)
        // timeline-mapped user message uses content from TimelineItemDto
        assertEquals("from timeline", messages[0].text)
    }

    // ── 3. timelineItems が空のときは legacy messages にフォールバックすること

    @Test
    fun `getMessagesFallsBackToLegacyWhenTimelineEmpty`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.getSession(eq("sess-3"), eq(true))).thenReturn(
            SessionDetailResponse(
                session = makeSessionDto("sess-3"),
                messages = listOf(makeMessageDto(role = "user", content = "legacy msg")),
                timelineItems = emptyList(),
            )
        )
        val repo = ChatRepositoryImpl(api, sseClient, settingsRepository)

        val result = repo.getMessages("sess-3")

        assertTrue(result.isSuccess)
        val messages = result.getOrThrow()
        assertEquals(1, messages.size)
        assertEquals("legacy msg", messages[0].text)
    }
}

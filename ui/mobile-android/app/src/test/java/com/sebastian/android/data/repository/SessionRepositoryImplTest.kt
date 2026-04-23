package com.sebastian.android.data.repository

import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.CreateSessionRequest
import com.sebastian.android.data.remote.dto.TurnDto
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.argumentCaptor
import org.mockito.kotlin.mock
import org.mockito.kotlin.whenever

class SessionRepositoryImplTest {

    private val apiService: ApiService = mock()
    private val repository = SessionRepositoryImpl(apiService)

    @Test
    fun `createAgentSession with sessionId sends session_id in request body`() = runTest {
        whenever(apiService.createAgentSession(any(), any())).thenReturn(
            TurnDto(sessionId = "client-id-1", ts = "2026-01-01T00:00:00Z")
        )

        repository.createAgentSession("research", "find sources", sessionId = "client-id-1")

        val captor = argumentCaptor<CreateSessionRequest>()
        org.mockito.kotlin.verify(apiService).createAgentSession(any(), captor.capture())
        assertEquals("client-id-1", captor.firstValue.sessionId)
        assertEquals("find sources", captor.firstValue.content)
    }

    @Test
    fun `createAgentSession without sessionId sends null session_id`() = runTest {
        whenever(apiService.createAgentSession(any(), any())).thenReturn(
            TurnDto(sessionId = "server-id", ts = "2026-01-01T00:00:00Z")
        )

        repository.createAgentSession("research", "find sources", sessionId = null)

        val captor = argumentCaptor<CreateSessionRequest>()
        org.mockito.kotlin.verify(apiService).createAgentSession(any(), captor.capture())
        assertEquals(null, captor.firstValue.sessionId)
    }
}

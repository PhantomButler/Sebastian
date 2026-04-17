package com.sebastian.android.data.repository

import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.SetBindingRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import org.mockito.kotlin.any
import org.mockito.kotlin.argumentCaptor
import org.mockito.kotlin.eq

class AgentRepositoryImplTest {

    @Test
    fun `setBinding sends provider_id and OFF effort as null thinking_effort`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setAgentBinding(eq("forge"), any())).thenReturn(
            AgentBindingDto(agentType = "forge", providerId = "p1", thinkingEffort = null)
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.setBinding("forge", "p1", ThinkingEffort.OFF)

        assertTrue(result.isSuccess)
        val captor = argumentCaptor<SetBindingRequest>()
        verify(api).setAgentBinding(eq("forge"), captor.capture())
        assertEquals("p1", captor.firstValue.providerId)
        assertNull(captor.firstValue.thinkingEffort)
    }

    @Test
    fun `setBinding maps HIGH effort to high string in request body`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setAgentBinding(eq("forge"), any())).thenReturn(
            AgentBindingDto(agentType = "forge", providerId = "p1", thinkingEffort = "high")
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        repo.setBinding("forge", "p1", ThinkingEffort.HIGH)

        val captor = argumentCaptor<SetBindingRequest>()
        verify(api).setAgentBinding(eq("forge"), captor.capture())
        assertEquals("high", captor.firstValue.thinkingEffort)
    }

    @Test
    fun `setBinding allows null provider_id for use-default`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setAgentBinding(eq("forge"), any())).thenReturn(
            AgentBindingDto(agentType = "forge", providerId = null, thinkingEffort = null)
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        repo.setBinding("forge", null, ThinkingEffort.OFF)

        val captor = argumentCaptor<SetBindingRequest>()
        verify(api).setAgentBinding(eq("forge"), captor.capture())
        assertNull(captor.firstValue.providerId)
    }

    @Test
    fun `clearBinding calls clearAgentBinding and returns success`() = runTest {
        val api = mock(ApiService::class.java)
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.clearBinding("forge")
        assertTrue(result.isSuccess)
        verify(api).clearAgentBinding("forge")
    }
}

package com.sebastian.android.data.repository

import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.SetBindingRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.mockito.Mockito.*
import org.mockito.kotlin.any
import org.mockito.kotlin.eq

class AgentRepositoryImplTest {

    @Test
    fun `setBinding passes provider_id and returns success`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setAgentBinding(eq("forge"), any())).thenReturn(
            AgentBindingDto(agentType = "forge", providerId = "p1")
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.setBinding("forge", "p1")
        assertTrue(result.isSuccess)
        assertEquals("p1", result.getOrNull()?.providerId)
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

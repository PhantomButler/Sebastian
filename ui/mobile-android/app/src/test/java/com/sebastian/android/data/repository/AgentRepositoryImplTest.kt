package com.sebastian.android.data.repository

import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.MemoryComponentBindingDto
import com.sebastian.android.data.remote.dto.MemoryComponentDto
import com.sebastian.android.data.remote.dto.MemoryComponentsResponse
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

    // ── Memory Component tests ──────────────────────────────────────────────

    @Test
    fun `listMemoryComponents maps null binding to null boundProviderId and OFF effort`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.listMemoryComponents()).thenReturn(
            MemoryComponentsResponse(
                components = listOf(
                    MemoryComponentDto(
                        componentType = "episodic",
                        displayName = "Episodic Memory",
                        description = "Stores episodic events",
                        binding = null,
                    )
                )
            )
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.listMemoryComponents()

        assertTrue(result.isSuccess)
        val components = result.getOrThrow()
        assertEquals(1, components.size)
        val info = components[0]
        assertEquals("episodic", info.componentType)
        assertNull(info.boundProviderId)
        assertEquals(ThinkingEffort.OFF, info.thinkingEffort)
    }

    @Test
    fun `listMemoryComponents maps binding to correct boundProviderId and thinkingEffort`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.listMemoryComponents()).thenReturn(
            MemoryComponentsResponse(
                components = listOf(
                    MemoryComponentDto(
                        componentType = "semantic",
                        displayName = "Semantic Memory",
                        description = "Stores semantic facts",
                        binding = MemoryComponentBindingDto(
                            componentType = "semantic",
                            providerId = "prov-42",
                            thinkingEffort = "high",
                        ),
                    )
                )
            )
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.listMemoryComponents()

        assertTrue(result.isSuccess)
        val info = result.getOrThrow()[0]
        assertEquals("prov-42", info.boundProviderId)
        assertEquals(ThinkingEffort.HIGH, info.thinkingEffort)
    }

    @Test
    fun `getMemoryComponentBinding fills agentType with componentType`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.getMemoryComponentBinding("episodic")).thenReturn(
            MemoryComponentBindingDto(
                componentType = "episodic",
                providerId = "prov-1",
                thinkingEffort = null,
            )
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.getMemoryComponentBinding("episodic")

        assertTrue(result.isSuccess)
        val dto = result.getOrThrow()
        assertEquals("episodic", dto.agentType)
        assertEquals("prov-1", dto.providerId)
        assertNull(dto.thinkingEffort)
    }

    @Test
    fun `setMemoryComponentBinding sends correct request with OFF effort as null`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setMemoryComponentBinding(eq("semantic"), any())).thenReturn(
            MemoryComponentBindingDto(componentType = "semantic", providerId = "p2", thinkingEffort = null)
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.setMemoryComponentBinding("semantic", "p2", ThinkingEffort.OFF)

        assertTrue(result.isSuccess)
        val captor = argumentCaptor<SetBindingRequest>()
        verify(api).setMemoryComponentBinding(eq("semantic"), captor.capture())
        assertEquals("p2", captor.firstValue.providerId)
        assertNull(captor.firstValue.thinkingEffort)
    }

    @Test
    fun `setMemoryComponentBinding maps HIGH effort to high string`() = runTest {
        val api = mock(ApiService::class.java)
        `when`(api.setMemoryComponentBinding(eq("semantic"), any())).thenReturn(
            MemoryComponentBindingDto(componentType = "semantic", providerId = "p2", thinkingEffort = "high")
        )
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        repo.setMemoryComponentBinding("semantic", "p2", ThinkingEffort.HIGH)

        val captor = argumentCaptor<SetBindingRequest>()
        verify(api).setMemoryComponentBinding(eq("semantic"), captor.capture())
        assertEquals("high", captor.firstValue.thinkingEffort)
    }

    @Test
    fun `clearMemoryComponentBinding calls correct API endpoint and returns success`() = runTest {
        val api = mock(ApiService::class.java)
        val repo = AgentRepositoryImpl(api, Dispatchers.Unconfined)

        val result = repo.clearMemoryComponentBinding("episodic")

        assertTrue(result.isSuccess)
        verify(api).clearMemoryComponentBinding("episodic")
    }
}

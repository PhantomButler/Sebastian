package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class AgentBindingsViewModelTest {

    private lateinit var agentRepo: AgentRepository
    private lateinit var settingsRepo: SettingsRepository
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        agentRepo = mock()
        settingsRepo = mock()
    }

    @After
    fun teardown() {
        Dispatchers.resetMain()
    }

    private fun sampleAgent(
        agentType: String = "forge",
        boundId: String? = null,
        isOrchestrator: Boolean = false,
    ) = AgentInfo(
        agentType = agentType,
        displayName = agentType.replaceFirstChar { it.uppercase() },
        description = "Code",
        isOrchestrator = isOrchestrator,
        boundProviderId = boundId,
    )

    private fun sampleProvider() = Provider(
        id = "p1",
        name = "Test Provider",
        type = "anthropic",
        baseUrl = null,
        model = "claude-3-5-sonnet",
        isDefault = true,
        thinkingCapability = ThinkingCapability.NONE,
    )

    @Test
    fun `load emits agents and providers`() = runTest(dispatcher) {
        wheneverBlocking { agentRepo.getAgents() }.thenReturn(Result.success(listOf(sampleAgent())))
        wheneverBlocking { agentRepo.listMemoryComponents() }.thenReturn(Result.success(emptyList()))
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(Result.success(listOf(sampleProvider())))

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, state.agents.size)
        assertEquals(1, state.providers.size)
        assertNull(state.errorMessage)
    }

    @Test
    fun `load partitions orchestrator from sub-agents`() = runTest(dispatcher) {
        val orchestrator = sampleAgent(agentType = "orchestrator", isOrchestrator = true)
        val subAgent = sampleAgent(agentType = "forge", isOrchestrator = false)
        wheneverBlocking { agentRepo.getAgents() }.thenReturn(
            Result.success(listOf(orchestrator, subAgent))
        )
        wheneverBlocking { agentRepo.listMemoryComponents() }.thenReturn(Result.success(emptyList()))
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(Result.success(emptyList()))

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()

        val agents = vm.uiState.value.agents
        assertEquals(2, agents.size)
        val (orch, subs) = agents.partition { it.isOrchestrator }
        assertEquals(1, orch.size)
        assertEquals(1, subs.size)
        assertEquals("orchestrator", orch.first().agentType)
        assertEquals("forge", subs.first().agentType)
    }
}

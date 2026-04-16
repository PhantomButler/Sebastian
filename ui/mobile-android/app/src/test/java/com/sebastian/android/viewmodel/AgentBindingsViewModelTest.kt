package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.remote.dto.AgentBindingDto
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

    private fun sampleAgent(boundId: String? = null) = AgentInfo(
        agentType = "forge",
        displayName = "Forge",
        description = "Code",
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
    fun `bind sets provider and refreshes agents`() = runTest(dispatcher) {
        wheneverBlocking { agentRepo.getAgents() }.thenReturn(Result.success(listOf(sampleAgent("p1"))))
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(Result.success(listOf(sampleProvider())))
        wheneverBlocking { agentRepo.setBinding("forge", "p1") }.thenReturn(
            Result.success(AgentBindingDto(agentType = "forge", providerId = "p1"))
        )

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()
        vm.bind("forge", "p1")
        advanceUntilIdle()

        assertEquals("p1", vm.uiState.value.agents.first().boundProviderId)
        assertEquals(AgentBindingsEvent.BindingUpdated, vm.events.replayCache.last())
    }

    @Test
    fun `useDefault clears binding and refreshes`() = runTest(dispatcher) {
        wheneverBlocking { agentRepo.getAgents() }.thenReturn(Result.success(listOf(sampleAgent(null))))
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(Result.success(listOf(sampleProvider())))
        wheneverBlocking { agentRepo.clearBinding("forge") }.thenReturn(Result.success(Unit))

        val vm = AgentBindingsViewModel(agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()
        vm.useDefault("forge")
        advanceUntilIdle()

        assertNull(vm.uiState.value.agents.first().boundProviderId)
        assertEquals(AgentBindingsEvent.BindingUpdated, vm.events.replayCache.last())
    }
}

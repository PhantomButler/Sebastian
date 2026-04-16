package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
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
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class AgentBindingEditorViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var agentRepo: AgentRepository
    private lateinit var settingsRepo: SettingsRepository

    @Before
    fun before() {
        Dispatchers.setMain(dispatcher)
        agentRepo = mock()
        settingsRepo = mock()
    }

    @After
    fun after() {
        Dispatchers.resetMain()
    }

    private fun provider(
        id: String,
        capability: ThinkingCapability,
        isDefault: Boolean = false,
    ) = Provider(
        id = id,
        name = id.uppercase(),
        type = "anthropic",
        baseUrl = null,
        model = "m",
        isDefault = isDefault,
        thinkingCapability = capability,
    )

    @Test
    fun `selectProvider resets thinking config and debounce-puts`() = runTest(dispatcher) {
        val adaptive = provider("p1", ThinkingCapability.ADAPTIVE)
        val effort = provider("p2", ThinkingCapability.EFFORT)
        wheneverBlocking { agentRepo.getBinding("sebastian") }.thenReturn(
            Result.success(AgentBindingDto("sebastian", "p1", "high")),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(adaptive, effort)),
        )
        wheneverBlocking {
            agentRepo.setBinding("sebastian", "p2", ThinkingEffort.OFF)
        }.thenReturn(Result.success(Unit))

        val vm = AgentBindingEditorViewModel("sebastian", agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()

        vm.selectProvider("p2")
        // 本地立即重置
        assertEquals(ThinkingEffort.OFF, vm.uiState.value.thinkingEffort)

        // 300ms 后 PUT
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()
        verify(agentRepo).setBinding("sebastian", "p2", ThinkingEffort.OFF)
    }

    @Test
    fun `setEffort debounces consecutive changes into single put`() = runTest(dispatcher) {
        val p = provider("p1", ThinkingCapability.EFFORT)
        wheneverBlocking { agentRepo.getBinding("sebastian") }.thenReturn(
            Result.success(AgentBindingDto("sebastian", "p1", null)),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(p)),
        )
        wheneverBlocking {
            agentRepo.setBinding("sebastian", "p1", ThinkingEffort.HIGH)
        }.thenReturn(Result.success(Unit))

        val vm = AgentBindingEditorViewModel("sebastian", agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()

        vm.setEffort(ThinkingEffort.LOW)
        dispatcher.scheduler.advanceTimeBy(100)
        vm.setEffort(ThinkingEffort.MEDIUM)
        dispatcher.scheduler.advanceTimeBy(100)
        vm.setEffort(ThinkingEffort.HIGH)
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()

        verify(agentRepo).setBinding("sebastian", "p1", ThinkingEffort.HIGH)
    }

    @Test
    fun `effective capability falls back to default provider when binding has no provider`() = runTest(dispatcher) {
        val def = provider("pd", ThinkingCapability.ADAPTIVE, isDefault = true)
        wheneverBlocking { agentRepo.getBinding("foo") }.thenReturn(
            Result.success(AgentBindingDto("foo", null, null)),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(def)),
        )

        val vm = AgentBindingEditorViewModel("foo", agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()

        assertEquals(ThinkingCapability.ADAPTIVE, vm.uiState.value.effectiveCapability)
    }

    @Test
    fun `out-of-range effort is coerced to highest valid step on init`() = runTest(dispatcher) {
        val effortOnly = provider("p", ThinkingCapability.EFFORT)
        // DB 里留下 max（上一任 provider 是 adaptive），EFFORT 只到 high
        wheneverBlocking { agentRepo.getBinding("foo") }.thenReturn(
            Result.success(AgentBindingDto("foo", "p", "max")),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(effortOnly)),
        )
        wheneverBlocking {
            agentRepo.setBinding("foo", "p", ThinkingEffort.HIGH)
        }.thenReturn(Result.success(Unit))

        val vm = AgentBindingEditorViewModel("foo", agentRepo, settingsRepo)
        vm.load()
        advanceUntilIdle()

        assertEquals(ThinkingEffort.HIGH, vm.uiState.value.thinkingEffort)
        // 并且触发 PUT 纠正
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()
        verify(agentRepo).setBinding("foo", "p", ThinkingEffort.HIGH)
    }
}

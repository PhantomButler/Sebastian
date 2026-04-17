package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.anyOrNull
import org.mockito.kotlin.eq
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.times
import org.mockito.kotlin.verify
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class AgentBindingEditorViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var agentRepo: AgentRepository
    private lateinit var settingsRepo: SettingsRepository
    private lateinit var appScope: CoroutineScope

    @Before
    fun before() {
        Dispatchers.setMain(dispatcher)
        agentRepo = mock()
        settingsRepo = mock()
        appScope = CoroutineScope(dispatcher)
    }

    @After
    fun after() {
        appScope.cancel()
        Dispatchers.resetMain()
    }

    private fun makeVm(agentType: String) =
        AgentBindingEditorViewModel(agentType, agentRepo, settingsRepo, appScope)

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

        val vm = makeVm("sebastian")
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

        val vm = makeVm("sebastian")
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

        val vm = makeVm("foo")
        vm.load()
        advanceUntilIdle()

        assertEquals(ThinkingCapability.ADAPTIVE, vm.uiState.value.effectiveCapability)
        // 合法的初始状态不应触发 PUT
        dispatcher.scheduler.advanceTimeBy(400)
        advanceUntilIdle()
        verify(agentRepo, never()).setBinding(any(), anyOrNull(), any())
    }

    @Test
    fun `concurrent load calls dedupe into a single getBinding`() = runTest(dispatcher) {
        val p = provider("p1", ThinkingCapability.EFFORT, isDefault = true)
        wheneverBlocking { agentRepo.getBinding("foo") }.thenReturn(
            Result.success(AgentBindingDto("foo", "p1", null)),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(p)),
        )

        val vm = makeVm("foo")
        // 模拟页面首次进入 + 旋转/重组再次触发
        vm.load()
        vm.load()
        advanceUntilIdle()

        verify(agentRepo, times(1)).getBinding("foo")
        verify(settingsRepo, times(1)).getProviders()
    }

    @Test
    fun `NONE capability with OFF effort does not trigger PUT on load`() = runTest(dispatcher) {
        val noThink = provider("pn", ThinkingCapability.NONE)
        wheneverBlocking { agentRepo.getBinding("foo") }.thenReturn(
            Result.success(AgentBindingDto("foo", "pn", null)),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(noThink)),
        )

        val vm = makeVm("foo")
        vm.load()
        advanceUntilIdle()
        dispatcher.scheduler.advanceTimeBy(400)
        advanceUntilIdle()

        assertEquals(ThinkingEffort.OFF, vm.uiState.value.thinkingEffort)
        verify(agentRepo, never()).setBinding(eq("foo"), anyOrNull(), any())
    }

    @Test
    fun `ALWAYS_ON capability with OFF effort does not trigger PUT on load`() = runTest(dispatcher) {
        val alwaysOn = provider("pa", ThinkingCapability.ALWAYS_ON)
        wheneverBlocking { agentRepo.getBinding("foo") }.thenReturn(
            Result.success(AgentBindingDto("foo", "pa", null)),
        )
        wheneverBlocking { settingsRepo.getProviders() }.thenReturn(
            Result.success(listOf(alwaysOn)),
        )

        val vm = makeVm("foo")
        vm.load()
        advanceUntilIdle()
        dispatcher.scheduler.advanceTimeBy(400)
        advanceUntilIdle()

        assertEquals(ThinkingEffort.OFF, vm.uiState.value.thinkingEffort)
        verify(agentRepo, never()).setBinding(eq("foo"), anyOrNull(), any())
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

        val vm = makeVm("foo")
        vm.load()
        advanceUntilIdle()

        assertEquals(ThinkingEffort.HIGH, vm.uiState.value.thinkingEffort)
        // 并且触发 PUT 纠正
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()
        verify(agentRepo).setBinding("foo", "p", ThinkingEffort.HIGH)
    }

    @Test
    fun `pending debounced PUT is flushed via applicationScope on cleared`() = runTest(dispatcher) {
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

        val vm = makeVm("sebastian")
        vm.load()
        advanceUntilIdle()

        // 把 VM 放进 ViewModelStore，store.clear() 会取消 viewModelScope 并回调 onCleared，
        // 与真实 Activity/Fragment 销毁路径一致
        val store = androidx.lifecycle.ViewModelStore()
        store.put("vm", vm)

        vm.setEffort(ThinkingEffort.HIGH)
        // debounce 未到期：尚未触发 PUT
        dispatcher.scheduler.advanceTimeBy(100)
        verify(agentRepo, never()).setBinding("sebastian", "p1", ThinkingEffort.HIGH)

        // 模拟用户离开页面
        store.clear()
        advanceUntilIdle()

        // viewModelScope 已被 store.clear 取消，delay 未到期的 putJob 不会 setBinding；
        // 依赖 applicationScope 补发
        verify(agentRepo).setBinding("sebastian", "p1", ThinkingEffort.HIGH)
    }
}

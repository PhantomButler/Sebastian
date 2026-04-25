package com.sebastian.android.viewmodel

import com.sebastian.android.data.model.AgentBinding
import com.sebastian.android.data.model.CatalogModel
import com.sebastian.android.data.model.CatalogProvider
import com.sebastian.android.data.model.CustomModel
import com.sebastian.android.data.model.LlmAccount
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
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
import org.junit.Assert.assertTrue
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

    private fun makeVm(agentType: String, isMemoryComponent: Boolean = false) =
        AgentBindingEditorViewModel(agentType, isMemoryComponent, agentRepo, settingsRepo, appScope)

    private fun account(
        id: String = "acc-1",
        name: String = "Account 1",
        catalogProviderId: String = "anthropic",
        providerType: String = "anthropic",
    ) = LlmAccount(
        id = id,
        name = name,
        catalogProviderId = catalogProviderId,
        providerType = providerType,
        baseUrlOverride = null,
        hasApiKey = true,
    )

    private fun catalogProvider(
        id: String = "anthropic",
        models: List<CatalogModel> = listOf(
            CatalogModel("claude-3-5-sonnet", "Claude 3.5 Sonnet", 200_000L, ThinkingCapability.NONE, null),
        ),
    ) = CatalogProvider(id = id, displayName = id.uppercase(), providerType = "anthropic", baseUrl = "https://api.anthropic.com", models = models)

    private fun binding(
        agentType: String = "forge",
        accountId: String? = "acc-1",
        modelId: String? = "claude-3-5-sonnet",
        thinkingEffort: String? = null,
    ) = AgentBinding(agentType = agentType, accountId = accountId, modelId = modelId, thinkingEffort = thinkingEffort, resolved = null)

    @Test
    fun `load fetches agent binding without clearing`() = runTest(dispatcher) {
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(Result.success(binding()))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(listOf(catalogProvider())))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        verify(agentRepo).getAgentBinding("forge")
        verify(agentRepo, never()).setAgentBinding(any(), anyOrNull(), anyOrNull(), anyOrNull())
        assertEquals("acc-1", vm.uiState.value.selectedAccount?.id)
        assertEquals("claude-3-5-sonnet", vm.uiState.value.selectedModel?.id)
    }

    @Test
    fun `selectAccount resets model and does not persist partial binding`() = runTest(dispatcher) {
        val acc2 = account(id = "acc-2", name = "Account 2")
        val catalog = catalogProvider(models = listOf(
            CatalogModel("model-a", "Model A", 100_000L, ThinkingCapability.NONE, null),
        ))
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(Result.success(binding()))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account(), acc2)))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(listOf(catalog)))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        vm.selectAccount("acc-2")
        advanceUntilIdle()

        assertEquals("acc-2", vm.uiState.value.selectedAccount?.id)
        assertEquals(null, vm.uiState.value.selectedModel)
        verify(agentRepo, never()).setAgentBinding(any(), anyOrNull(), anyOrNull(), anyOrNull())
    }

    @Test
    fun `selectModel triggers debounced PUT after account and model are set`() = runTest(dispatcher) {
        val effortModel = CatalogModel("model-e", "Model E", 100_000L, ThinkingCapability.EFFORT, null)
        val catalog = catalogProvider(models = listOf(effortModel))
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(Result.success(binding(modelId = "model-e")))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(listOf(catalog)))
        wheneverBlocking {
            agentRepo.setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), anyOrNull())
        }.thenReturn(Result.success(binding(modelId = "model-e")))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        vm.selectModel("model-e")
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()

        verify(agentRepo).setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), anyOrNull())
    }

    @Test
    fun `setEffort debounces consecutive changes into single put`() = runTest(dispatcher) {
        val effortModel = CatalogModel("model-e", "Model E", 100_000L, ThinkingCapability.EFFORT, null)
        val catalog = catalogProvider(models = listOf(effortModel))
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(Result.success(binding(modelId = "model-e")))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(listOf(catalog)))
        wheneverBlocking {
            agentRepo.setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))
        }.thenReturn(Result.success(binding(modelId = "model-e", thinkingEffort = "high")))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        vm.setEffort(ThinkingEffort.LOW)
        dispatcher.scheduler.advanceTimeBy(100)
        vm.setEffort(ThinkingEffort.MEDIUM)
        dispatcher.scheduler.advanceTimeBy(100)
        vm.setEffort(ThinkingEffort.HIGH)
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()

        verify(agentRepo, times(1)).setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))
    }

    @Test
    fun `concurrent load calls dedupe into a single getAgentBinding`() = runTest(dispatcher) {
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(Result.success(binding()))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(listOf(catalogProvider())))

        val vm = makeVm("forge")
        vm.load()
        vm.load()
        advanceUntilIdle()

        verify(agentRepo, times(1)).getAgentBinding("forge")
        verify(settingsRepo, times(1)).getLlmAccounts()
    }

    @Test
    fun `NONE capability with OFF effort does not trigger PUT on load`() = runTest(dispatcher) {
        val noneModel = CatalogModel("model-n", "Model N", 100_000L, ThinkingCapability.NONE, null)
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(
            Result.success(binding(modelId = "model-n", thinkingEffort = null))
        )
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(
            Result.success(listOf(catalogProvider(models = listOf(noneModel))))
        )

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()
        dispatcher.scheduler.advanceTimeBy(400)
        advanceUntilIdle()

        assertEquals(ThinkingEffort.OFF, vm.uiState.value.thinkingEffort)
        verify(agentRepo, never()).setAgentBinding(eq("forge"), anyOrNull(), anyOrNull(), anyOrNull())
    }

    @Test
    fun `out-of-range effort is coerced to highest valid step on init`() = runTest(dispatcher) {
        val effortModel = CatalogModel("model-e", "Model E", 100_000L, ThinkingCapability.EFFORT, null)
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(
            Result.success(binding(modelId = "model-e", thinkingEffort = "max"))
        )
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(
            Result.success(listOf(catalogProvider(models = listOf(effortModel))))
        )
        wheneverBlocking {
            agentRepo.setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))
        }.thenReturn(Result.success(binding(modelId = "model-e", thinkingEffort = "high")))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        assertEquals(ThinkingEffort.HIGH, vm.uiState.value.thinkingEffort)
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()
        verify(agentRepo).setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))
    }

    @Test
    fun `pending debounced PUT is flushed via applicationScope on cleared`() = runTest(dispatcher) {
        val effortModel = CatalogModel("model-e", "Model E", 100_000L, ThinkingCapability.EFFORT, null)
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(Result.success(binding(modelId = "model-e")))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(
            Result.success(listOf(catalogProvider(models = listOf(effortModel))))
        )
        wheneverBlocking {
            agentRepo.setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))
        }.thenReturn(Result.success(binding(modelId = "model-e", thinkingEffort = "high")))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        val store = androidx.lifecycle.ViewModelStore()
        store.put("vm", vm)

        vm.setEffort(ThinkingEffort.HIGH)
        dispatcher.scheduler.advanceTimeBy(100)
        verify(agentRepo, never()).setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))

        store.clear()
        advanceUntilIdle()

        verify(agentRepo).setAgentBinding(eq("forge"), eq("acc-1"), eq("model-e"), eq("high"))
    }

    @Test
    fun `memory component load uses getMemoryBinding not getAgentBinding`() = runTest(dispatcher) {
        wheneverBlocking { agentRepo.getMemoryBinding("episodic") }.thenReturn(Result.success(binding(agentType = "episodic")))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(account())))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(listOf(catalogProvider())))

        val vm = makeVm("episodic", isMemoryComponent = true)
        vm.load()
        advanceUntilIdle()

        verify(agentRepo).getMemoryBinding("episodic")
        verify(agentRepo, never()).getAgentBinding(any())
    }

    @Test
    fun `selectAccount with custom provider fetches custom models`() = runTest(dispatcher) {
        val customAcc = account(id = "acc-custom", catalogProviderId = "custom", providerType = "openai")
        val customModel = CustomModel("cm-1", "acc-custom", "gpt-4o", "GPT-4o", 128_000L, ThinkingCapability.NONE, null)
        wheneverBlocking { agentRepo.getAgentBinding("forge") }.thenReturn(
            Result.success(binding(accountId = null, modelId = null))
        )
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(listOf(customAcc)))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(emptyList()))
        wheneverBlocking { settingsRepo.getCustomModels("acc-custom") }.thenReturn(Result.success(listOf(customModel)))

        val vm = makeVm("forge")
        vm.load()
        advanceUntilIdle()

        vm.selectAccount("acc-custom")
        advanceUntilIdle()

        val models = vm.uiState.value.availableModels
        assertEquals(1, models.size)
        assertEquals("gpt-4o", models.first().id)
        verify(agentRepo, never()).setAgentBinding(any(), anyOrNull(), anyOrNull(), anyOrNull())
    }

    @Test
    fun `default binding empty account skips PUT and emits snackbar`() = runTest(dispatcher) {
        wheneverBlocking { settingsRepo.getDefaultBinding() }.thenReturn(Result.success(null))
        wheneverBlocking { settingsRepo.getLlmAccounts() }.thenReturn(Result.success(emptyList()))
        wheneverBlocking { settingsRepo.getLlmCatalog() }.thenReturn(Result.success(emptyList()))

        val vm = makeVm("__default__")
        vm.load()
        advanceUntilIdle()

        vm.setEffort(ThinkingEffort.HIGH)
        dispatcher.scheduler.advanceTimeBy(350)
        advanceUntilIdle()

        verify(settingsRepo, never()).setDefaultBinding(anyOrNull(), anyOrNull(), anyOrNull())
    }
}

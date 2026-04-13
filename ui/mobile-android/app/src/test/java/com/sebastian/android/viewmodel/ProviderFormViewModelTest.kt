package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class ProviderFormViewModelTest {

    private lateinit var repository: SettingsRepository
    private lateinit var viewModel: ProviderFormViewModel
    private val providersFlow = MutableStateFlow<List<Provider>>(emptyList())
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        repository = mock()
        org.mockito.kotlin.whenever(repository.providersFlow()).thenReturn(providersFlow)
        viewModel = ProviderFormViewModel(repository, dispatcher)
    }

    @Test
    fun `initial state has anthropic type and empty fields`() = runTest(dispatcher) {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("anthropic", state.type)
            assertEquals("", state.name)
            assertEquals("", state.apiKey)
        }
    }

    @Test
    fun `onNameChange updates name in state`() = runTest(dispatcher) {
        viewModel.onNameChange("Claude API")
        assertEquals("Claude API", viewModel.uiState.value.name)
    }

    @Test
    fun `save with blank name sets error`() = runTest(dispatcher) {
        viewModel.save(null)
        assertEquals("名称不能为空", viewModel.uiState.value.error)
    }

    @Test
    fun `save create calls repository and sets isSaved`() = runTest(dispatcher) {
        wheneverBlocking {
            repository.createProvider(
                name = "TestProvider",
                type = "anthropic",
                baseUrl = "http://api.anthropic.com",
                apiKey = "sk-test",
                model = "claude-3-5-sonnet-20241022",
                thinkingCapability = "none",
                isDefault = false,
            )
        }.thenReturn(Result.success(Provider("id1", "TestProvider", "anthropic", "http://api.anthropic.com", "claude-3-5-sonnet-20241022", false, ThinkingCapability.NONE)))
        viewModel.onNameChange("TestProvider")
        viewModel.onApiKeyChange("sk-test")
        viewModel.onModelChange("claude-3-5-sonnet-20241022")
        viewModel.onBaseUrlChange("http://api.anthropic.com")
        viewModel.save(null)
        dispatcher.scheduler.advanceUntilIdle()
        assertTrue(viewModel.uiState.value.isSaved)
    }
}

package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.SettingsRepository
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class ProviderFormViewModelTest {

    private lateinit var repository: SettingsRepository
    private lateinit var viewModel: ProviderFormViewModel
    private val providersFlow = MutableStateFlow<List<Provider>>(emptyList())
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        repository = mock()
        whenever(repository.providersFlow()).thenReturn(providersFlow)
        viewModel = ProviderFormViewModel(repository, dispatcher)
        dispatcher.scheduler.advanceTimeBy(200)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun vmTest(testBody: suspend TestScope.() -> Unit) = runTest(dispatcher) {
        try {
            testBody()
        } finally {
            viewModel.viewModelScope.cancel()
        }
    }

    @Test
    fun `initial state has anthropic type and empty fields`() = vmTest {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("anthropic", state.type)
            assertEquals("", state.name)
            assertEquals("", state.apiKey)
        }
    }

    @Test
    fun `onNameChange updates name in state`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial
            viewModel.onNameChange("Claude API")
            dispatcher.scheduler.advanceTimeBy(200)
            val state = awaitItem()
            assertEquals("Claude API", state.name)
        }
    }

    @Test
    fun `save with blank name sets error`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial (starts stateIn subscription)
            viewModel.save(null)
            dispatcher.scheduler.advanceTimeBy(200)
            val state = awaitItem()
            assertEquals("名称不能为空", state.error)
        }
    }

    @Test
    fun `save with api key in base url sets error and does not create provider`() = vmTest {
        viewModel.uiState.test {
            awaitItem() // initial (starts stateIn subscription)

            viewModel.onNameChange("TestProvider")
            viewModel.onApiKeyChange("sk-test")
            viewModel.onModelChange("claude-3-5-sonnet-20241022")
            viewModel.onBaseUrlChange("sk-ant-key-in-wrong-field")
            viewModel.save(null)
            dispatcher.scheduler.advanceTimeBy(200)

            var state = awaitItem()
            while (state.error == null) {
                state = awaitItem()
            }
            assertEquals("Base URL 必须是 http(s) 地址", state.error)
            verify(repository, never()).createProvider(
                name = "TestProvider",
                type = "anthropic",
                baseUrl = "sk-ant-key-in-wrong-field",
                apiKey = "sk-test",
                model = "claude-3-5-sonnet-20241022",
                thinkingCapability = "none",
                isDefault = false,
            )
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `save create calls repository and sets isSaved`() = vmTest {
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

        viewModel.uiState.test {
            awaitItem() // initial (starts stateIn subscription)

            viewModel.onNameChange("TestProvider")
            viewModel.onApiKeyChange("sk-test")
            viewModel.onModelChange("claude-3-5-sonnet-20241022")
            viewModel.onBaseUrlChange("http://api.anthropic.com")
            viewModel.save(null)
            dispatcher.scheduler.advanceTimeBy(200)

            // Skip intermediate states until isSaved
            var found = false
            while (!found) {
                val state = awaitItem()
                if (state.isSaved) found = true
            }
            assertTrue(found)
            cancelAndIgnoreRemainingEvents()
        }
    }
}

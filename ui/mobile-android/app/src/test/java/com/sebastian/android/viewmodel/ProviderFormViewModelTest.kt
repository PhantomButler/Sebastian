package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.LlmAccount
import com.sebastian.android.data.repository.SettingsRepository
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
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
import org.mockito.kotlin.any
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.verify
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class ProviderFormViewModelTest {

    private lateinit var repository: SettingsRepository
    private lateinit var viewModel: ProviderFormViewModel
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        repository = mock()
        wheneverBlocking { repository.getLlmCatalog() }.thenReturn(Result.success(emptyList()))
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

    private fun sampleAccount(id: String = "acc-1") = LlmAccount(
        id = id,
        name = "TestProvider",
        catalogProviderId = "anthropic",
        providerType = "anthropic",
        baseUrlOverride = null,
        hasApiKey = true,
    )

    @Test
    fun `initial state has empty fields`() = vmTest {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("", state.name)
            assertEquals("", state.apiKey)
        }
    }

    @Test
    fun `onNameChange updates name in state`() = vmTest {
        viewModel.uiState.test {
            awaitItem()
            viewModel.onNameChange("Claude API")
            dispatcher.scheduler.advanceTimeBy(200)
            val state = awaitItem()
            assertEquals("Claude API", state.name)
        }
    }

    @Test
    fun `save with blank name sets error`() = vmTest {
        viewModel.uiState.test {
            awaitItem()
            viewModel.save(null)
            dispatcher.scheduler.advanceTimeBy(200)
            val state = awaitItem()
            assertEquals("名称不能为空", state.error)
        }
    }

    @Test
    fun `save with api key in base url sets error and does not create account`() = vmTest {
        viewModel.uiState.test {
            awaitItem()

            viewModel.onNameChange("TestProvider")
            viewModel.onApiKeyChange("sk-test")
            viewModel.onCatalogSelect("custom")
            viewModel.onBaseUrlChange("sk-ant-key-in-wrong-field")
            viewModel.save(null)
            dispatcher.scheduler.advanceTimeBy(200)

            var state = awaitItem()
            while (state.error == null) {
                state = awaitItem()
            }
            assertEquals("Base URL 必须是 http(s) 地址", state.error)
            verify(repository, never()).createLlmAccount(
                name = any(),
                catalogProviderId = any(),
                apiKey = any(),
                providerType = any(),
                baseUrlOverride = any(),
            )
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `save create calls repository and sets isSaved`() = vmTest {
        wheneverBlocking {
            repository.createLlmAccount(
                name = "TestProvider",
                catalogProviderId = "anthropic",
                apiKey = "sk-test",
                providerType = null,
                baseUrlOverride = null,
            )
        }.thenReturn(Result.success(sampleAccount()))

        viewModel.uiState.test {
            awaitItem()

            viewModel.onNameChange("TestProvider")
            viewModel.onApiKeyChange("sk-test")
            viewModel.onCatalogSelect("anthropic")
            viewModel.save(null)
            dispatcher.scheduler.advanceTimeBy(200)

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

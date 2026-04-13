package com.sebastian.android.viewmodel

import app.cash.turbine.test
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
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
import org.mockito.kotlin.whenever
import org.mockito.kotlin.wheneverBlocking

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    private lateinit var repository: SettingsRepository
    private lateinit var viewModel: SettingsViewModel
    private lateinit var serverUrlFlow: MutableStateFlow<String>
    private lateinit var themeFlow: MutableStateFlow<String>
    private lateinit var providersFlow: MutableStateFlow<List<Provider>>
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
        serverUrlFlow = MutableStateFlow("")
        themeFlow = MutableStateFlow("system")
        providersFlow = MutableStateFlow(emptyList())
        repository = mock()
        whenever(repository.serverUrl).thenReturn(serverUrlFlow)
        whenever(repository.theme).thenReturn(themeFlow)
        whenever(repository.providersFlow()).thenReturn(providersFlow)
        wheneverBlocking { repository.getProviders() }.thenReturn(Result.success(emptyList()))
        viewModel = SettingsViewModel(repository, dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `initial state has empty serverUrl`() = runTest(dispatcher) {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("", state.serverUrl)
        }
    }

    @Test
    fun `serverUrl updates when flow emits`() = runTest(dispatcher) {
        viewModel.uiState.test {
            awaitItem() // initial
            serverUrlFlow.emit("http://192.168.1.1:8823")
            val updated = awaitItem()
            assertEquals("http://192.168.1.1:8823", updated.serverUrl)
        }
    }

    @Test
    fun `saveServerUrl calls repository`() = runTest(dispatcher) {
        viewModel.saveServerUrl("http://10.0.2.2:8823")
        advanceUntilIdle()
        verify(repository).saveServerUrl("http://10.0.2.2:8823")
    }

    @Test
    fun `providers list reflects repository flow`() = runTest(dispatcher) {
        val provider = Provider("p1", "Claude", "anthropic", null, null, true, ThinkingCapability.EFFORT)
        viewModel.uiState.test {
            awaitItem() // initial empty
            providersFlow.emit(listOf(provider))
            val updated = awaitItem()
            assertEquals(1, updated.providers.size)
            assertEquals("Claude", updated.providers[0].name)
        }
    }

    @Test
    fun `deleteProvider removes from list on success`() = runTest(dispatcher) {
        val provider = Provider("p1", "Claude", "anthropic", null, null, true, ThinkingCapability.EFFORT)
        providersFlow.emit(listOf(provider))
        whenever(repository.deleteProvider("p1")).thenReturn(Result.success(Unit))
        viewModel.deleteProvider("p1")
        dispatcher.scheduler.advanceUntilIdle()
        verify(repository).deleteProvider("p1")
    }

    @Test
    fun `deleteProvider propagates error to uiState on failure`() = runTest(dispatcher) {
        whenever(repository.deleteProvider("p1")).thenReturn(Result.failure(Exception("删除失败")))
        viewModel.deleteProvider("p1")
        dispatcher.scheduler.advanceUntilIdle()
        assertEquals("删除失败", viewModel.uiState.value.error)
    }
}

package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val serverUrl: String = "",
    val theme: String = "system",
    val providers: List<Provider> = emptyList(),
    val currentProvider: Provider? = null,
    val isLoading: Boolean = false,
    val error: String? = null,
    val connectionTestResult: ConnectionTestResult? = null,
)

sealed class ConnectionTestResult {
    data object Success : ConnectionTestResult()
    data class Failure(val message: String) : ConnectionTestResult()
}

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repository: SettingsRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(
                repository.serverUrl,
                repository.theme,
                repository.providersFlow(),
                repository.currentProvider,
            ) { url, theme, providers, currentProvider ->
                _uiState.update {
                    it.copy(
                        serverUrl = url,
                        theme = theme,
                        providers = providers,
                        currentProvider = currentProvider,
                    )
                }
            }.collect {}
        }
        loadProviders()
    }

    fun saveServerUrl(url: String) {
        viewModelScope.launch(dispatcher) {
            repository.saveServerUrl(url.trim())
        }
    }

    fun saveTheme(theme: String) {
        viewModelScope.launch(dispatcher) {
            repository.saveTheme(theme)
        }
    }

    fun loadProviders() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            repository.getProviders()
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
                .onSuccess {
                    // 数据更新通过 providersFlow() 流式传递，此处只清除 loading 状态
                    _uiState.update { it.copy(isLoading = false) }
                }
        }
    }

    fun deleteProvider(id: String) {
        viewModelScope.launch(dispatcher) {
            repository.deleteProvider(id)
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message) }
                }
        }
    }

    fun setDefaultProvider(id: String) {
        viewModelScope.launch(dispatcher) {
            repository.setDefaultProvider(id)
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message) }
                }
        }
    }

    fun testConnection(url: String) {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, connectionTestResult = null) }
            repository.testConnection(url)
                .onSuccess {
                    _uiState.update { it.copy(isLoading = false, connectionTestResult = ConnectionTestResult.Success) }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            connectionTestResult = ConnectionTestResult.Failure(e.message ?: "连接失败"),
                        )
                    }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
    fun clearConnectionTestResult() = _uiState.update { it.copy(connectionTestResult = null) }
}

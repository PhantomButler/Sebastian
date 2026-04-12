package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ProviderFormUiState(
    val name: String = "",
    val type: String = "anthropic",
    val baseUrl: String = "",
    val apiKey: String = "",
    val isLoading: Boolean = false,
    val isSaved: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class ProviderFormViewModel @Inject constructor(
    private val repository: SettingsRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ProviderFormUiState())
    val uiState: StateFlow<ProviderFormUiState> = _uiState.asStateFlow()

    fun loadProvider(id: String) {
        viewModelScope.launch(dispatcher) {
            val provider = repository.providersFlow().first().find { it.id == id } ?: return@launch
            _uiState.update {
                it.copy(
                    name = provider.name,
                    type = provider.type,
                    baseUrl = provider.baseUrl ?: "",
                    // apiKey 不回填：编辑时要求重新输入（安全策略，避免明文展示已存储密钥）
                )
            }
        }
    }

    fun onNameChange(v: String) = _uiState.update { it.copy(name = v) }
    fun onTypeChange(v: String) = _uiState.update { it.copy(type = v) }
    fun onBaseUrlChange(v: String) = _uiState.update { it.copy(baseUrl = v) }
    fun onApiKeyChange(v: String) = _uiState.update { it.copy(apiKey = v) }

    fun save(existingId: String?) {
        val state = _uiState.value
        if (state.name.isBlank()) {
            _uiState.update { it.copy(error = "名称不能为空") }
            return
        }
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = if (existingId == null) {
                repository.createProvider(
                    name = state.name.trim(),
                    type = state.type,
                    baseUrl = state.baseUrl.trim().ifEmpty { null },
                    apiKey = state.apiKey.trim().ifEmpty { null },
                )
            } else {
                repository.updateProvider(
                    id = existingId,
                    name = state.name.trim(),
                    type = state.type,
                    baseUrl = state.baseUrl.trim().ifEmpty { null },
                    apiKey = state.apiKey.trim().ifEmpty { null },
                )
            }
            result
                .onSuccess { _uiState.update { it.copy(isLoading = false, isSaved = true) } }
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}

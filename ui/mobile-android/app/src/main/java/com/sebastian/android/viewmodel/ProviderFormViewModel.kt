package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.net.URI
import javax.inject.Inject

data class ProviderFormUiState(
    val name: String = "",
    val type: String = "anthropic",
    val baseUrl: String = "",
    val apiKey: String = "",
    val model: String = "",
    val thinkingCapability: ThinkingCapability = ThinkingCapability.NONE,
    val isDefault: Boolean = false,
    val isLoading: Boolean = false,
    val isSaved: Boolean = false,
    val isDirty: Boolean = false,
    val isNew: Boolean = true,
    val error: String? = null,
)

@HiltViewModel
class ProviderFormViewModel @Inject constructor(
    private val repository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _formState = MutableStateFlow(ProviderFormUiState())
    private val _initialSnapshot = MutableStateFlow<ProviderFormUiState?>(null)

    val uiState: StateFlow<ProviderFormUiState> = combine(
        _formState,
        _initialSnapshot,
    ) { current, initial ->
        val dirty = if (initial == null) {
            // 新建模式：任何字段有值即算 dirty
            current.name.isNotBlank() || current.apiKey.isNotBlank() ||
                current.model.isNotBlank() || current.baseUrl.isNotBlank()
        } else {
            current.name.trim() != initial.name.trim() ||
                current.type != initial.type ||
                current.apiKey.trim() != initial.apiKey.trim() ||
                current.model.trim() != initial.model.trim() ||
                current.baseUrl.trim() != initial.baseUrl.trim() ||
                current.thinkingCapability != initial.thinkingCapability ||
                current.isDefault != initial.isDefault
        }
        current.copy(isDirty = dirty, isNew = initial == null)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), ProviderFormUiState())

    fun loadProvider(id: String) {
        viewModelScope.launch(dispatcher) {
            val provider = repository.providersFlow().first().find { it.id == id } ?: return@launch
            val loaded = ProviderFormUiState(
                name = provider.name,
                type = provider.type,
                baseUrl = provider.baseUrl ?: "",
                model = provider.model ?: "",
                thinkingCapability = provider.thinkingCapability,
                isDefault = provider.isDefault,
            )
            _formState.value = loaded
            _initialSnapshot.value = loaded
        }
    }

    fun onNameChange(v: String) = _formState.update { it.copy(name = v) }
    fun onTypeChange(v: String) = _formState.update { it.copy(type = v) }
    fun onBaseUrlChange(v: String) = _formState.update { it.copy(baseUrl = v) }
    fun onApiKeyChange(v: String) = _formState.update { it.copy(apiKey = v) }
    fun onModelChange(v: String) = _formState.update { it.copy(model = v) }
    fun onThinkingCapabilityChange(v: ThinkingCapability) = _formState.update { it.copy(thinkingCapability = v) }
    fun onIsDefaultChange(v: Boolean) = _formState.update { it.copy(isDefault = v) }

    fun save(existingId: String?) {
        val state = _formState.value
        if (state.name.isBlank()) {
            _formState.update { it.copy(error = "名称不能为空") }
            return
        }
        if (state.apiKey.isBlank() && existingId == null) {
            _formState.update { it.copy(error = "API Key 不能为空") }
            return
        }
        if (state.model.isBlank()) {
            _formState.update { it.copy(error = "模型不能为空") }
            return
        }
        if (state.baseUrl.isBlank()) {
            _formState.update { it.copy(error = "Base URL 不能为空") }
            return
        }
        if (!isValidBaseUrl(state.baseUrl)) {
            _formState.update { it.copy(error = "Base URL 必须是 http(s) 地址") }
            return
        }
        viewModelScope.launch(dispatcher) {
            _formState.update { it.copy(isLoading = true, error = null) }
            val capabilityStr = when (state.thinkingCapability) {
                ThinkingCapability.NONE -> "none"
                ThinkingCapability.ALWAYS_ON -> "always_on"
                ThinkingCapability.TOGGLE -> "toggle"
                ThinkingCapability.EFFORT -> "effort"
                ThinkingCapability.ADAPTIVE -> "adaptive"
            }
            val result = if (existingId == null) {
                repository.createProvider(
                    name = state.name.trim(),
                    type = state.type,
                    baseUrl = state.baseUrl.trim().ifEmpty { null },
                    apiKey = state.apiKey.trim().ifEmpty { null },
                    model = state.model.trim().ifEmpty { null },
                    thinkingCapability = capabilityStr,
                    isDefault = state.isDefault,
                )
            } else {
                repository.updateProvider(
                    id = existingId,
                    name = state.name.trim(),
                    type = state.type,
                    baseUrl = state.baseUrl.trim().ifEmpty { null },
                    apiKey = state.apiKey.trim().ifEmpty { null },
                    model = state.model.trim().ifEmpty { null },
                    thinkingCapability = capabilityStr,
                    isDefault = state.isDefault,
                )
            }
            result
                .onSuccess { _formState.update { it.copy(isLoading = false, isSaved = true) } }
                .onFailure { e -> _formState.update { it.copy(isLoading = false, error = e.message) } }
        }
    }

    fun clearError() = _formState.update { it.copy(error = null) }

    private fun isValidBaseUrl(value: String): Boolean {
        val uri = runCatching { URI(value.trim()) }.getOrNull() ?: return false
        val scheme = uri.scheme ?: return false
        val hasHttpScheme = scheme.equals("http", ignoreCase = true) ||
            scheme.equals("https", ignoreCase = true)
        return hasHttpScheme && !uri.host.isNullOrBlank()
    }
}

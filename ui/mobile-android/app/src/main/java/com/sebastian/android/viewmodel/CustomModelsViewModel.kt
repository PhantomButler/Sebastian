package com.sebastian.android.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.CustomModel
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CustomModelsUiState(
    val models: List<CustomModel> = emptyList(),
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: String? = null,
    val editingModelId: String? = null,
    val showForm: Boolean = false,
    // Form fields
    val modelId: String = "",
    val displayName: String = "",
    val contextWindowTokens: String = "32000",
    val thinkingCapability: String = "none",
    val thinkingFormat: String = "",
)

@HiltViewModel
class CustomModelsViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val settingsRepository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val accountId: String = savedStateHandle["accountId"]!!

    private val _uiState = MutableStateFlow(CustomModelsUiState())
    val uiState: StateFlow<CustomModelsUiState> = _uiState.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true, error = null) }
            settingsRepository.getCustomModels(accountId)
                .onSuccess { models ->
                    _uiState.update { it.copy(models = models, isLoading = false) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun saveModel() {
        val state = _uiState.value
        if (state.modelId.isBlank()) {
            _uiState.update { it.copy(error = "Model ID 不能为空") }
            return
        }
        if (state.displayName.isBlank()) {
            _uiState.update { it.copy(error = "显示名称不能为空") }
            return
        }
        val tokens = state.contextWindowTokens.toLongOrNull()
        if (tokens == null || tokens < 1000 || tokens > 10_000_000) {
            _uiState.update { it.copy(error = "上下文窗口须在 1,000 – 10,000,000 之间") }
            return
        }

        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isSaving = true, error = null) }
            val capability = state.thinkingCapability.takeIf { it != "none" }
            val format = state.thinkingFormat.takeIf { it.isNotBlank() }

            val result = if (state.editingModelId != null) {
                settingsRepository.updateCustomModel(
                    accountId = accountId,
                    modelRecordId = state.editingModelId,
                    modelId = state.modelId.trim(),
                    displayName = state.displayName.trim(),
                    contextWindowTokens = tokens,
                    thinkingCapability = capability,
                    thinkingFormat = format,
                )
            } else {
                settingsRepository.createCustomModel(
                    accountId = accountId,
                    modelId = state.modelId.trim(),
                    displayName = state.displayName.trim(),
                    contextWindowTokens = tokens,
                    thinkingCapability = capability,
                    thinkingFormat = format,
                )
            }
            result
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            isSaving = false,
                            showForm = false,
                            editingModelId = null,
                            modelId = "",
                            displayName = "",
                            contextWindowTokens = "32000",
                            thinkingCapability = "none",
                            thinkingFormat = "",
                        )
                    }
                    load()
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isSaving = false, error = e.message) }
                }
        }
    }

    fun deleteModel(modelRecordId: String) {
        viewModelScope.launch(dispatcher) {
            settingsRepository.deleteCustomModel(accountId, modelRecordId)
                .onSuccess {
                    _uiState.update { it.copy(models = _uiState.value.models.filter { m -> m.id != modelRecordId }) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message ?: "删除失败") }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }

    fun updateModelId(v: String) = _uiState.update { it.copy(modelId = v) }
    fun updateDisplayName(v: String) = _uiState.update { it.copy(displayName = v) }
    fun updateContextWindow(v: String) = _uiState.update { it.copy(contextWindowTokens = v) }
    fun updateThinkingCapability(v: String) = _uiState.update { it.copy(thinkingCapability = v) }
    fun updateThinkingFormat(v: String) = _uiState.update { it.copy(thinkingFormat = v) }

    fun startEdit(model: CustomModel) {
        _uiState.update {
            it.copy(
                showForm = true,
                editingModelId = model.id,
                modelId = model.modelId,
                displayName = model.displayName,
                contextWindowTokens = model.contextWindowTokens.toString(),
                thinkingCapability = when (model.thinkingCapability) {
                    ThinkingCapability.NONE -> "none"
                    ThinkingCapability.TOGGLE -> "toggle"
                    ThinkingCapability.EFFORT -> "effort"
                    ThinkingCapability.ADAPTIVE -> "adaptive"
                    ThinkingCapability.OUTPUT_EFFORT -> "output_effort"
                    ThinkingCapability.ALWAYS_ON -> "always_on"
                },
                thinkingFormat = model.thinkingFormat ?: "",
            )
        }
    }

    fun startNew() {
        _uiState.update {
            it.copy(
                showForm = true,
                editingModelId = null,
                modelId = "",
                displayName = "",
                contextWindowTokens = "32000",
                thinkingCapability = "none",
                thinkingFormat = "",
            )
        }
    }

    fun dismissForm() {
        _uiState.update { it.copy(showForm = false, editingModelId = null) }
    }
}

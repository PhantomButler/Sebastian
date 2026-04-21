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
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class MemorySettingsUiState(
    val enabled: Boolean = false,
    val isLoading: Boolean = true,
    val error: String? = null,
    val errorSerial: Int = 0,
)

@HiltViewModel
class MemorySettingsViewModel @Inject constructor(
    private val repository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(MemorySettingsUiState())
    val uiState: StateFlow<MemorySettingsUiState> = _uiState.asStateFlow()

    init {
        loadSettings()
    }

    private fun loadSettings() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true) }
            repository.getMemorySettings()
                .onSuccess { dto ->
                    _uiState.update { it.copy(enabled = dto.enabled, isLoading = false) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message, errorSerial = it.errorSerial + 1) }
                }
        }
    }

    fun toggle(enabled: Boolean) {
        if (_uiState.value.isLoading) return   // prevent concurrent toggle calls
        val prev = _uiState.value.enabled
        _uiState.update { it.copy(enabled = enabled, isLoading = true) }
        viewModelScope.launch(dispatcher) {
            repository.setMemoryEnabled(enabled)
                .onSuccess { dto ->
                    _uiState.update { it.copy(enabled = dto.enabled, isLoading = false) }
                }
                .onFailure { _ ->
                    _uiState.update { it.copy(enabled = prev, isLoading = false, error = "更新失败，已回滚", errorSerial = it.errorSerial + 1) }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}

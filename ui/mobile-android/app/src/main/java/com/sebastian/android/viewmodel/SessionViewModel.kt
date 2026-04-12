package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Session
import com.sebastian.android.data.repository.SessionRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SessionUiState(
    val sessions: List<Session> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SessionViewModel @Inject constructor(
    private val repository: SessionRepository,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SessionUiState())
    val uiState: StateFlow<SessionUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            repository.sessionsFlow().collect { sessions ->
                _uiState.update { it.copy(sessions = sessions) }
            }
        }
        loadSessions()
    }

    fun loadSessions() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true) }
            repository.loadSessions()
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
                .onSuccess { _uiState.update { it.copy(isLoading = false) } }
        }
    }

    fun createSession() {
        viewModelScope.launch(dispatcher) {
            repository.createSession()
        }
    }
}

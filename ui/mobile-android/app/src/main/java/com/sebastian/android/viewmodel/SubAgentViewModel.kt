package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.Session
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SessionRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SubAgentUiState(
    val agents: List<AgentInfo> = emptyList(),
    val agentSessions: List<Session> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SubAgentViewModel @Inject constructor(
    private val agentRepository: AgentRepository,
    private val sessionRepository: SessionRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SubAgentUiState())
    val uiState: StateFlow<SubAgentUiState> = _uiState.asStateFlow()

    fun loadAgents() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            agentRepository.getAgents()
                .onSuccess { agents ->
                    _uiState.update { it.copy(isLoading = false, agents = agents) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun loadAgentSessions(agentType: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            sessionRepository.getAgentSessions(agentType)
                .onSuccess { sessions ->
                    _uiState.update { it.copy(isLoading = false, agentSessions = sessions) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}

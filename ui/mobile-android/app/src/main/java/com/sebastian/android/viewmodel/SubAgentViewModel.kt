// com/sebastian/android/viewmodel/SubAgentViewModel.kt
package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Session
import com.sebastian.android.data.remote.ApiService
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

data class AgentInfo(
    val agentType: String,
    val name: String,
    val description: String,
    val isActive: Boolean,
)

data class SubAgentUiState(
    val agents: List<AgentInfo> = emptyList(),
    val agentSessions: List<Session> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SubAgentViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val apiService: ApiService,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SubAgentUiState())
    val uiState: StateFlow<SubAgentUiState> = _uiState.asStateFlow()

    fun loadAgents() {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true) }
            runCatching { apiService.getAgents() }
                .onSuccess { raw ->
                    val agents = raw.map { map ->
                        AgentInfo(
                            agentType = map["agent_type"]?.toString() ?: "",
                            name = map["name"]?.toString() ?: "",
                            description = map["description"]?.toString() ?: "",
                            isActive = map["is_active"] as? Boolean ?: false,
                        )
                    }.filter { it.agentType.isNotEmpty() }
                    _uiState.update { it.copy(isLoading = false, agents = agents) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message) }
                }
        }
    }

    fun loadAgentSessions(agentType: String) {
        viewModelScope.launch(dispatcher) {
            _uiState.update { it.copy(isLoading = true) }
            sessionRepository.getAgentSessions(agentType)
                .onSuccess { sessions -> _uiState.update { it.copy(isLoading = false, agentSessions = sessions) } }
                .onFailure { e -> _uiState.update { it.copy(isLoading = false, error = e.message) } }
        }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }
}

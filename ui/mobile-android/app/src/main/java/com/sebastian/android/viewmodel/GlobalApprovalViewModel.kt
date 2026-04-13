package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException
import javax.inject.Inject

data class GlobalApproval(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val description: String,
)

data class GlobalApprovalUiState(
    val approvals: List<GlobalApproval> = emptyList(),
)

@HiltViewModel
class GlobalApprovalViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val settingsRepository: SettingsRepository,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(GlobalApprovalUiState())
    val uiState: StateFlow<GlobalApprovalUiState> = _uiState.asStateFlow()

    private var sseJob: Job? = null

    fun onAppStart() {
        if (sseJob?.isActive == true) return
        sseJob = viewModelScope.launch(dispatcher) {
            val baseUrl = settingsRepository.serverUrl.first()
            if (baseUrl.isEmpty()) return@launch
            try {
                chatRepository.globalStream(baseUrl).collect { event ->
                    handleEvent(event)
                }
            } catch (_: CancellationException) {
                throw CancellationException()
            } catch (_: Exception) {
                // Global SSE failure is non-fatal; will retry on next onAppStart
            }
        }
    }

    fun onAppStop() {
        sseJob?.cancel()
        sseJob = null
    }

    private fun handleEvent(event: StreamEvent) {
        when (event) {
            is StreamEvent.ApprovalRequested -> {
                val approval = GlobalApproval(
                    approvalId = event.approvalId,
                    sessionId = event.sessionId,
                    agentType = event.agentType,
                    description = event.description,
                )
                _uiState.update { it.copy(approvals = it.approvals + approval) }
            }
            is StreamEvent.ApprovalGranted -> {
                _uiState.update { state ->
                    state.copy(approvals = state.approvals.filter { it.approvalId != event.approvalId })
                }
            }
            is StreamEvent.ApprovalDenied -> {
                _uiState.update { state ->
                    state.copy(approvals = state.approvals.filter { it.approvalId != event.approvalId })
                }
            }
            else -> Unit
        }
    }

    fun grantApproval(approvalId: String) {
        _uiState.update { state ->
            state.copy(approvals = state.approvals.filter { it.approvalId != approvalId })
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.grantApproval(approvalId)
        }
    }

    fun denyApproval(approvalId: String) {
        _uiState.update { state ->
            state.copy(approvals = state.approvals.filter { it.approvalId != approvalId })
        }
        viewModelScope.launch(dispatcher) {
            chatRepository.denyApproval(approvalId)
        }
    }
}

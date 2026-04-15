package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.GlobalSseDispatcher
import com.sebastian.android.data.repository.ChatRepository
import com.sebastian.android.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class GlobalApproval(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val toolName: String,
    val toolInputJson: String,
    val reason: String,
)

data class ApprovalSnapshot(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,
    val toolName: String,
    val toolInputJson: String,
    val reason: String,
)

data class GlobalApprovalUiState(
    val approvals: List<GlobalApproval> = emptyList(),
)

@HiltViewModel
class GlobalApprovalViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val sseDispatcher: GlobalSseDispatcher,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(GlobalApprovalUiState())
    val uiState: StateFlow<GlobalApprovalUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch(dispatcher) {
            sseDispatcher.events.collect { handleEvent(it) }
        }
    }

    fun replaceAll(snapshot: List<ApprovalSnapshot>) {
        val next = snapshot.map {
            GlobalApproval(
                approvalId = it.approvalId,
                sessionId = it.sessionId,
                agentType = it.agentType,
                toolName = it.toolName,
                toolInputJson = it.toolInputJson,
                reason = it.reason,
            )
        }
        _uiState.update { it.copy(approvals = next) }
    }

    private fun handleEvent(event: StreamEvent) {
        when (event) {
            is StreamEvent.ApprovalRequested -> upsert(
                GlobalApproval(
                    approvalId = event.approvalId,
                    sessionId = event.sessionId,
                    agentType = event.agentType,
                    toolName = event.toolName,
                    toolInputJson = event.toolInputJson,
                    reason = event.reason,
                )
            )
            is StreamEvent.ApprovalGranted -> removeById(event.approvalId)
            is StreamEvent.ApprovalDenied -> removeById(event.approvalId)
            else -> Unit
        }
    }

    private fun upsert(approval: GlobalApproval) {
        _uiState.update { state ->
            val idx = state.approvals.indexOfFirst { it.approvalId == approval.approvalId }
            val next = if (idx >= 0) {
                state.approvals.toMutableList().apply { this[idx] = approval }
            } else {
                state.approvals + approval
            }
            state.copy(approvals = next)
        }
    }

    private fun removeById(approvalId: String) {
        _uiState.update { state ->
            state.copy(approvals = state.approvals.filter { it.approvalId != approvalId })
        }
    }

    fun grantApproval(approvalId: String) {
        removeById(approvalId)
        viewModelScope.launch(dispatcher) {
            chatRepository.grantApproval(approvalId)
        }
    }

    fun denyApproval(approvalId: String) {
        removeById(approvalId)
        viewModelScope.launch(dispatcher) {
            chatRepository.denyApproval(approvalId)
        }
    }
}

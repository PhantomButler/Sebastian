package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.toApiString
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.SetBindingRequest
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AgentRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : AgentRepository {

    override suspend fun getAgents(): Result<List<AgentInfo>> = runCatching {
        withContext(dispatcher) {
            apiService.getAgents().agents.map { it.toDomain() }
        }
    }

    override suspend fun getBinding(agentType: String): Result<AgentBindingDto> = runCatching {
        withContext(dispatcher) {
            apiService.getAgentBinding(agentType)
        }
    }

    override suspend fun setBinding(
        agentType: String,
        providerId: String?,
        thinkingEffort: ThinkingEffort,
    ): Result<Unit> = runCatching {
        withContext(dispatcher) {
            apiService.setAgentBinding(
                agentType,
                SetBindingRequest(
                    providerId = providerId,
                    thinkingEffort = thinkingEffort.toApiString(),
                ),
            )
            Unit
        }
    }

    override suspend fun clearBinding(agentType: String): Result<Unit> = runCatching {
        withContext(dispatcher) {
            apiService.clearAgentBinding(agentType)
        }
    }
}

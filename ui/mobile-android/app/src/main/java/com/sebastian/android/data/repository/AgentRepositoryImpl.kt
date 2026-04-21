package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.MemoryComponentInfo
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

    override suspend fun listMemoryComponents(): Result<List<MemoryComponentInfo>> = runCatching {
        withContext(dispatcher) {
            apiService.listMemoryComponents().components.map { it.toDomain() }
        }
    }

    override suspend fun getMemoryComponentBinding(
        componentType: String,
    ): Result<AgentBindingDto> = runCatching {
        withContext(dispatcher) {
            val dto = apiService.getMemoryComponentBinding(componentType)
            // agentType field carries componentType — AgentBindingEditorViewModel only reads providerId/thinkingEffort,
            // so we reuse AgentBindingDto as a binding carrier here.
            AgentBindingDto(
                agentType = dto.componentType,
                providerId = dto.providerId,
                thinkingEffort = dto.thinkingEffort,
            )
        }
    }

    override suspend fun setMemoryComponentBinding(
        componentType: String,
        providerId: String?,
        thinkingEffort: ThinkingEffort,
    ): Result<Unit> = runCatching {
        withContext(dispatcher) {
            apiService.setMemoryComponentBinding(
                componentType,
                SetBindingRequest(
                    providerId = providerId,
                    thinkingEffort = thinkingEffort.toApiString(),
                ),
            )
            Unit
        }
    }

    override suspend fun clearMemoryComponentBinding(
        componentType: String,
    ): Result<Unit> = runCatching {
        withContext(dispatcher) {
            apiService.clearMemoryComponentBinding(componentType)
        }
    }
}

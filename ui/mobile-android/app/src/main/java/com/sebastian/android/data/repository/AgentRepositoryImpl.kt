package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentBinding
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.MemoryComponentInfo
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.toApiString
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.AgentBindingDto
import com.sebastian.android.data.remote.dto.LegacyAgentBindingDto
import com.sebastian.android.data.remote.dto.LegacySetBindingRequest
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

    override suspend fun getBinding(agentType: String): Result<LegacyAgentBindingDto> = runCatching {
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
                LegacySetBindingRequest(
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

    override suspend fun setAgentBinding(
        agentType: String,
        accountId: String?,
        modelId: String?,
        thinkingEffort: String?,
    ): Result<AgentBinding> = runCatching {
        withContext(dispatcher) {
            apiService.setAgentBindingV2(
                agentType,
                SetBindingRequest(
                    accountId = accountId,
                    modelId = modelId,
                    thinkingEffort = thinkingEffort,
                ),
            ).toDomain()
        }
    }

    override suspend fun listMemoryComponents(): Result<List<MemoryComponentInfo>> = runCatching {
        withContext(dispatcher) {
            apiService.listMemoryComponents().components.map { it.toDomain() }
        }
    }

    override suspend fun getMemoryComponentBinding(
        componentType: String,
    ): Result<LegacyAgentBindingDto> = runCatching {
        withContext(dispatcher) {
            val dto = apiService.getMemoryComponentBinding(componentType)
            LegacyAgentBindingDto(
                agentType = dto.componentType ?: componentType,
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
                LegacySetBindingRequest(
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

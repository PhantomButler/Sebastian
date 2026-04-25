package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentBinding
import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.MemoryComponentInfo
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.dto.LegacyAgentBindingDto

interface AgentRepository {
    suspend fun getAgents(): Result<List<AgentInfo>>
    suspend fun getBinding(agentType: String): Result<LegacyAgentBindingDto>
    suspend fun setBinding(
        agentType: String,
        providerId: String?,
        thinkingEffort: ThinkingEffort,
    ): Result<Unit>
    suspend fun clearBinding(agentType: String): Result<Unit>
    suspend fun setAgentBinding(
        agentType: String,
        accountId: String?,
        modelId: String?,
        thinkingEffort: String?,
    ): Result<AgentBinding>
    suspend fun listMemoryComponents(): Result<List<MemoryComponentInfo>>
    suspend fun getMemoryComponentBinding(componentType: String): Result<LegacyAgentBindingDto>
    suspend fun setMemoryComponentBinding(
        componentType: String,
        providerId: String?,
        thinkingEffort: ThinkingEffort,
    ): Result<Unit>
    suspend fun clearMemoryComponentBinding(componentType: String): Result<Unit>
}

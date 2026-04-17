package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.dto.AgentBindingDto

interface AgentRepository {
    suspend fun getAgents(): Result<List<AgentInfo>>
    suspend fun getBinding(agentType: String): Result<AgentBindingDto>
    suspend fun setBinding(
        agentType: String,
        providerId: String?,
        thinkingEffort: ThinkingEffort,
    ): Result<Unit>
    suspend fun clearBinding(agentType: String): Result<Unit>
}

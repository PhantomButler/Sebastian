package com.sebastian.android.data.repository

import com.sebastian.android.data.model.AgentInfo

interface AgentRepository {
    suspend fun getAgents(): Result<List<AgentInfo>>
}

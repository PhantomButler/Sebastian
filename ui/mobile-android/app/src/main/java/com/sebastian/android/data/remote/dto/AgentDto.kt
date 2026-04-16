package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.AgentInfo
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AgentListResponse(
    @param:Json(name = "agents") val agents: List<AgentDto>,
)

@JsonClass(generateAdapter = true)
data class AgentDto(
    @param:Json(name ="agent_type") val agentType: String,
    @param:Json(name ="description") val description: String,
    @param:Json(name ="active_session_count") val activeSessionCount: Int = 0,
    @param:Json(name ="max_children") val maxChildren: Int = 0,
    @param:Json(name = "bound_provider_id") val boundProviderId: String? = null,
) {
    fun toDomain() = AgentInfo(
        agentType = agentType,
        description = description,
        activeSessionCount = activeSessionCount,
        maxChildren = maxChildren,
        boundProviderId = boundProviderId,
    )
}

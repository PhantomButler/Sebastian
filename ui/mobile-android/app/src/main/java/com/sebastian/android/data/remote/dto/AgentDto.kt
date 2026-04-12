package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.AgentInfo
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AgentListResponse(
    @Json(name = "agents") val agents: List<AgentDto>,
)

@JsonClass(generateAdapter = true)
data class AgentDto(
    @Json(name = "agent_type") val agentType: String,
    @Json(name = "name") val name: String,
    @Json(name = "description") val description: String,
    @Json(name = "active_session_count") val activeSessionCount: Int = 0,
    @Json(name = "max_children") val maxChildren: Int = 0,
) {
    fun toDomain() = AgentInfo(
        agentType = agentType,
        name = name.ifEmpty { agentType },
        description = description,
        activeSessionCount = activeSessionCount,
        maxChildren = maxChildren,
    )
}

package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.AgentInfo
import com.sebastian.android.data.model.toThinkingEffort
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
    @param:Json(name ="display_name") val displayName: String? = null,
    @param:Json(name ="is_orchestrator") val isOrchestrator: Boolean = false,
    @param:Json(name ="active_session_count") val activeSessionCount: Int = 0,
    @param:Json(name ="max_children") val maxChildren: Int? = null,
    @param:Json(name = "binding") val binding: AgentBindingDto? = null,
) {
    fun toDomain() = AgentInfo(
        agentType = agentType,
        displayName = displayName ?: agentType.replaceFirstChar { it.uppercase() },
        description = description,
        isOrchestrator = isOrchestrator,
        boundProviderId = binding?.providerId,
        thinkingEffort = binding?.thinkingEffort.toThinkingEffort(),
        activeSessionCount = activeSessionCount,
        maxChildren = maxChildren ?: 0,
    )
}

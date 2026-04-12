package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Session
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SessionDto(
    @Json(name = "id") val id: String,
    @Json(name = "title") val title: String?,
    @Json(name = "agent_type") val agentType: String,
    @Json(name = "last_message_at") val lastMessageAt: String?,
    @Json(name = "is_active") val isActive: Boolean = false,
) {
    fun toDomain() = Session(
        id = id,
        title = title ?: "新对话",
        agentType = agentType,
        lastMessageAt = lastMessageAt,
        isActive = isActive,
    )
}

@JsonClass(generateAdapter = true)
data class CreateSessionRequest(
    @Json(name = "title") val title: String? = null,
    @Json(name = "agent_type") val agentType: String = "sebastian",
)

@JsonClass(generateAdapter = true)
data class SessionListResponse(
    @Json(name = "sessions") val sessions: List<SessionDto>,
    @Json(name = "total") val total: Int = 0,
)

@JsonClass(generateAdapter = true)
data class AgentSessionListResponse(
    @Json(name = "agent_type") val agentType: String,
    @Json(name = "sessions") val sessions: List<SessionDto>,
)

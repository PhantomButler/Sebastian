package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Session
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SessionDto(
    @Json(name = "id") val id: String,
    @Json(name = "title") val title: String?,
    @Json(name = "agent_type") val agentType: String,
    @Json(name = "status") val status: String = "active",
    @Json(name = "depth") val depth: Int = 1,
    @Json(name = "parent_session_id") val parentSessionId: String? = null,
    @Json(name = "last_activity_at") val lastActivityAt: String? = null,
    @Json(name = "updated_at") val updatedAt: String? = null,
    @Json(name = "task_count") val taskCount: Int = 0,
    @Json(name = "active_task_count") val activeTaskCount: Int = 0,
) {
    fun toDomain() = Session(
        id = id,
        title = title ?: "新对话",
        agentType = agentType,
        status = status,
        lastActivityAt = lastActivityAt,
        updatedAt = updatedAt,
    )
}

@JsonClass(generateAdapter = true)
data class CreateSessionRequest(
    @Json(name = "content") val content: String,
    @Json(name = "thinking_effort") val thinkingEffort: String? = null,
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

@JsonClass(generateAdapter = true)
data class SessionDetailResponse(
    @Json(name = "session") val session: SessionDto,
    @Json(name = "messages") val messages: List<MessageDto>,
)

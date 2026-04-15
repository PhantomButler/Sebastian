package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Session
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SessionDto(
    @param:Json(name ="id") val id: String,
    @param:Json(name ="title") val title: String?,
    @param:Json(name ="agent_type") val agentType: String,
    @param:Json(name ="status") val status: String = "active",
    @param:Json(name ="depth") val depth: Int = 1,
    @param:Json(name ="parent_session_id") val parentSessionId: String? = null,
    @param:Json(name ="last_activity_at") val lastActivityAt: String? = null,
    @param:Json(name ="updated_at") val updatedAt: String? = null,
    @param:Json(name ="task_count") val taskCount: Int = 0,
    @param:Json(name ="active_task_count") val activeTaskCount: Int = 0,
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
    @param:Json(name ="content") val content: String,
    @param:Json(name ="thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class SessionListResponse(
    @param:Json(name ="sessions") val sessions: List<SessionDto>,
    @param:Json(name ="total") val total: Int = 0,
)

@JsonClass(generateAdapter = true)
data class AgentSessionListResponse(
    @param:Json(name ="agent_type") val agentType: String,
    @param:Json(name ="sessions") val sessions: List<SessionDto>,
)

@JsonClass(generateAdapter = true)
data class SessionDetailResponse(
    @param:Json(name ="session") val session: SessionDto,
    @param:Json(name ="messages") val messages: List<MessageDto>,
)

@JsonClass(generateAdapter = true)
data class SessionRecentResponse(
    @param:Json(name ="session_id") val sessionId: String,
    @param:Json(name ="status") val status: String,
    @param:Json(name ="messages") val messages: List<MessageDto>,
)

@JsonClass(generateAdapter = true)
data class PendingApprovalsResponse(
    @param:Json(name ="approvals") val approvals: List<PendingApprovalDto>,
)

@JsonClass(generateAdapter = true)
data class PendingApprovalDto(
    @param:Json(name ="id") val id: String,
    @param:Json(name ="session_id") val sessionId: String,
    @param:Json(name ="tool_name") val toolName: String,
    @param:Json(name ="tool_input") val toolInput: Map<String, Any>?,
    @param:Json(name ="reason") val reason: String?,
    @param:Json(name ="agent_type") val agentType: String? = null,
)

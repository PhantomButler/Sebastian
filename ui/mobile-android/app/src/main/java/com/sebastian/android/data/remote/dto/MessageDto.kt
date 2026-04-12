package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MessageDto(
    @Json(name = "id") val id: String,
    @Json(name = "session_id") val sessionId: String,
    @Json(name = "role") val role: String,
    @Json(name = "content") val content: String = "",
    @Json(name = "created_at") val createdAt: String = "",
) {
    fun toDomain() = Message(
        id = id,
        sessionId = sessionId,
        role = if (role == "user") MessageRole.USER else MessageRole.ASSISTANT,
        text = if (role == "user") content else "",
        createdAt = createdAt,
    )
}

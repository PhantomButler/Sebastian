package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class TimelineItemDto(
    @param:Json(name = "id") val id: String,
    @param:Json(name = "session_id") val sessionId: String,
    @param:Json(name = "agent_type") val agentType: String? = null,
    @param:Json(name = "seq") val seq: Long,
    @param:Json(name = "kind") val kind: String,
    @param:Json(name = "role") val role: String? = null,
    @param:Json(name = "content") val content: String? = null,
    @param:Json(name = "payload") val payload: Map<String, Any?>? = null,
    @param:Json(name = "archived") val archived: Boolean = false,
    @param:Json(name = "assistant_turn_id") val assistantTurnId: String? = null,
    @param:Json(name = "provider_call_index") val providerCallIndex: Int? = null,
    @param:Json(name = "block_index") val blockIndex: Int? = null,
    @param:Json(name = "created_at") val createdAt: String? = null,
) {
    fun payloadString(key: String): String? = payload?.get(key) as? String

    fun payloadBoolean(key: String): Boolean? = payload?.get(key) as? Boolean

    fun payloadLong(key: String): Long? {
        val value = payload?.get(key) ?: return null
        return when (value) {
            is Long -> value
            is Int -> value.toLong()
            is Double -> value.toLong()
            is Float -> value.toLong()
            else -> null
        }
    }
}

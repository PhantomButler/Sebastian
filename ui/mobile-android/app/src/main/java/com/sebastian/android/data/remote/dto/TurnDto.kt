package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SendTurnRequest(
    @param:Json(name ="content") val content: String,
    @param:Json(name ="session_id") val sessionId: String? = null,
    @param:Json(name ="thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class TurnDto(
    @param:Json(name ="session_id") val sessionId: String,
    @param:Json(name ="ts") val ts: String,
)

@JsonClass(generateAdapter = true)
data class CancelResponse(
    @param:Json(name ="ok") val ok: Boolean,
)

package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SendTurnRequest(
    @Json(name = "content") val content: String,
    @Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class TurnDto(
    @Json(name = "session_id") val sessionId: String,
    @Json(name = "ts") val ts: String,
)

@JsonClass(generateAdapter = true)
data class CancelResponse(
    @Json(name = "ok") val ok: Boolean,
)

package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class LogStateDto(
    @Json(name = "llm_stream_enabled") val llmStreamEnabled: Boolean,
    @Json(name = "sse_enabled") val sseEnabled: Boolean,
)

@JsonClass(generateAdapter = true)
data class LogConfigPatchDto(
    @Json(name = "llm_stream_enabled") val llmStreamEnabled: Boolean? = null,
    @Json(name = "sse_enabled") val sseEnabled: Boolean? = null,
)

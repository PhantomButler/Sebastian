package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class LogStateDto(
    @param:Json(name ="llm_stream_enabled") val llmStreamEnabled: Boolean,
    @param:Json(name ="sse_enabled") val sseEnabled: Boolean,
)

@JsonClass(generateAdapter = true)
data class LogConfigPatchDto(
    @param:Json(name ="llm_stream_enabled") val llmStreamEnabled: Boolean? = null,
    @param:Json(name ="sse_enabled") val sseEnabled: Boolean? = null,
)

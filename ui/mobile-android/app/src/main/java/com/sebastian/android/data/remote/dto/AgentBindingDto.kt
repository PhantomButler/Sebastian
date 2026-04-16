package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SetBindingRequest(
    @param:Json(name = "provider_id") val providerId: String?,
)

@JsonClass(generateAdapter = true)
data class AgentBindingDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "provider_id") val providerId: String?,
)

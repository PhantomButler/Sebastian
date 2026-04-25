package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.*
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

// ── Legacy binding DTOs (used by old agent + memory binding endpoints) ──

@JsonClass(generateAdapter = true)
data class LegacySetBindingRequest(
    @param:Json(name = "provider_id") val providerId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class LegacyAgentBindingDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "provider_id") val providerId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

// ── New account-based binding DTOs ─────────────────────────────────────

@JsonClass(generateAdapter = true)
data class SetBindingRequest(
    @param:Json(name = "account_id") val accountId: String? = null,
    @param:Json(name = "model_id") val modelId: String? = null,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class AgentBindingDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "account_id") val accountId: String?,
    @param:Json(name = "model_id") val modelId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
    val resolved: ResolvedBindingDto? = null,
) {
    fun toDomain() = AgentBinding(
        agentType = agentType,
        accountId = accountId,
        modelId = modelId,
        thinkingEffort = thinkingEffort,
        resolved = resolved?.toDomain(),
    )
}

@JsonClass(generateAdapter = true)
data class ResolvedBindingDto(
    @param:Json(name = "account_name") val accountName: String?,
    @param:Json(name = "provider_display_name") val providerDisplayName: String?,
    @param:Json(name = "model_display_name") val modelDisplayName: String?,
    @param:Json(name = "context_window_tokens") val contextWindowTokens: Long?,
    @param:Json(name = "thinking_capability") val thinkingCapability: String?,
) {
    fun toDomain() = ResolvedBinding(
        accountName = accountName,
        providerDisplayName = providerDisplayName,
        modelDisplayName = modelDisplayName,
        contextWindowTokens = contextWindowTokens,
        thinkingCapability = thinkingCapability?.let { ThinkingCapability.fromString(it) },
    )
}

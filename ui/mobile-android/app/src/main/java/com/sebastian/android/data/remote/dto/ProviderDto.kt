package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.*
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class OkResponse(
    @param:Json(name = "ok") val ok: Boolean,
)

// ── Catalog DTOs ───────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class LlmCatalogResponseDto(
    val providers: List<CatalogProviderDto>,
)

@JsonClass(generateAdapter = true)
data class CatalogProviderDto(
    val id: String,
    @param:Json(name = "display_name") val displayName: String,
    @param:Json(name = "provider_type") val providerType: String,
    @param:Json(name = "base_url") val baseUrl: String,
    val models: List<CatalogModelDto>,
) {
    fun toDomain() = CatalogProvider(
        id = id,
        displayName = displayName,
        providerType = providerType,
        baseUrl = baseUrl,
        models = models.map { it.toDomain() },
    )
}

@JsonClass(generateAdapter = true)
data class CatalogModelDto(
    val id: String,
    @param:Json(name = "display_name") val displayName: String,
    @param:Json(name = "context_window_tokens") val contextWindowTokens: Long,
    @param:Json(name = "thinking_capability") val thinkingCapability: String?,
    @param:Json(name = "thinking_format") val thinkingFormat: String?,
) {
    fun toDomain() = CatalogModel(
        id = id,
        displayName = displayName,
        contextWindowTokens = contextWindowTokens,
        thinkingCapability = ThinkingCapability.fromString(thinkingCapability),
        thinkingFormat = thinkingFormat,
    )
}

// ── Account DTOs ───────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class LlmAccountListResponseDto(
    val accounts: List<LlmAccountDto>,
)

@JsonClass(generateAdapter = true)
data class LlmAccountDto(
    val id: String,
    val name: String,
    @param:Json(name = "catalog_provider_id") val catalogProviderId: String,
    @param:Json(name = "provider_type") val providerType: String,
    @param:Json(name = "has_api_key") val hasApiKey: Boolean,
    @param:Json(name = "base_url_override") val baseUrlOverride: String?,
) {
    fun toDomain() = LlmAccount(
        id = id,
        name = name,
        catalogProviderId = catalogProviderId,
        providerType = providerType,
        baseUrlOverride = baseUrlOverride,
        hasApiKey = hasApiKey,
    )
}

@JsonClass(generateAdapter = true)
data class LlmAccountCreateRequest(
    val name: String,
    @param:Json(name = "catalog_provider_id") val catalogProviderId: String,
    @param:Json(name = "api_key") val apiKey: String,
    @param:Json(name = "provider_type") val providerType: String? = null,
    @param:Json(name = "base_url_override") val baseUrlOverride: String? = null,
)

@JsonClass(generateAdapter = true)
data class LlmAccountUpdateRequest(
    val name: String? = null,
    @param:Json(name = "api_key") val apiKey: String? = null,
    @param:Json(name = "base_url_override") val baseUrlOverride: String? = null,
)

// ── Custom Model DTOs ──────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class CustomModelListResponseDto(
    val models: List<CustomModelDto>,
)

@JsonClass(generateAdapter = true)
data class CustomModelDto(
    val id: String,
    @param:Json(name = "account_id") val accountId: String,
    @param:Json(name = "model_id") val modelId: String,
    @param:Json(name = "display_name") val displayName: String,
    @param:Json(name = "context_window_tokens") val contextWindowTokens: Long,
    @param:Json(name = "thinking_capability") val thinkingCapability: String?,
    @param:Json(name = "thinking_format") val thinkingFormat: String?,
) {
    fun toDomain() = CustomModel(
        id = id,
        accountId = accountId,
        modelId = modelId,
        displayName = displayName,
        contextWindowTokens = contextWindowTokens,
        thinkingCapability = ThinkingCapability.fromString(thinkingCapability),
        thinkingFormat = thinkingFormat,
    )
}

@JsonClass(generateAdapter = true)
data class CustomModelCreateRequest(
    @param:Json(name = "model_id") val modelId: String,
    @param:Json(name = "display_name") val displayName: String,
    @param:Json(name = "context_window_tokens") val contextWindowTokens: Long,
    @param:Json(name = "thinking_capability") val thinkingCapability: String? = null,
    @param:Json(name = "thinking_format") val thinkingFormat: String? = null,
)

@JsonClass(generateAdapter = true)
data class CustomModelUpdateRequest(
    @param:Json(name = "model_id") val modelId: String? = null,
    @param:Json(name = "display_name") val displayName: String? = null,
    @param:Json(name = "context_window_tokens") val contextWindowTokens: Long? = null,
    @param:Json(name = "thinking_capability") val thinkingCapability: String? = null,
    @param:Json(name = "thinking_format") val thinkingFormat: String? = null,
)

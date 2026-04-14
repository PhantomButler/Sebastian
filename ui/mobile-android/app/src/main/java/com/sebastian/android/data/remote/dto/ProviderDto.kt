package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ProviderListResponse(
    @param:Json(name ="providers") val providers: List<ProviderDto>,
)

@JsonClass(generateAdapter = true)
data class ProviderDto(
    @param:Json(name ="id") val id: String = "",
    @param:Json(name ="name") val name: String = "",
    @param:Json(name ="provider_type") val providerType: String = "",
    @param:Json(name ="base_url") val baseUrl: String? = null,
    @param:Json(name ="api_key") val apiKey: String? = null,
    @param:Json(name ="model") val model: String? = null,
    @param:Json(name ="is_default") val isDefault: Boolean = false,
    @param:Json(name ="thinking_format") val thinkingFormat: String? = null,
    @param:Json(name ="thinking_capability") val thinkingCapability: String? = null,
) {
    fun toDomain() = Provider(
        id = id,
        name = name,
        type = providerType,
        baseUrl = baseUrl,
        model = model,
        isDefault = isDefault,
        thinkingCapability = ThinkingCapability.fromString(thinkingCapability),
    )
}

@JsonClass(generateAdapter = true)
data class OkResponse(
    @param:Json(name ="ok") val ok: Boolean,
)

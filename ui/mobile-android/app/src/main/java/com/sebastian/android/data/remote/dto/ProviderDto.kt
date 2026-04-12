package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ProviderDto(
    @Json(name = "id") val id: String = "",
    @Json(name = "name") val name: String,
    @Json(name = "type") val type: String,
    @Json(name = "base_url") val baseUrl: String? = null,
    @Json(name = "api_key") val apiKey: String? = null,
    @Json(name = "is_default") val isDefault: Boolean = false,
    @Json(name = "thinking_capability") val thinkingCapability: String? = null,
) {
    fun toDomain() = Provider(
        id = id,
        name = name,
        type = type,
        baseUrl = baseUrl,
        isDefault = isDefault,
        thinkingCapability = ThinkingCapability.fromString(thinkingCapability),
    )
}

@JsonClass(generateAdapter = true)
data class OkResponse(
    @Json(name = "ok") val ok: Boolean,
)

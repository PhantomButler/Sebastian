package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.MemoryComponentInfo
import com.sebastian.android.data.model.toThinkingEffort
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MemoryComponentBindingDto(
    @param:Json(name = "component_type") val componentType: String,
    @param:Json(name = "provider_id") val providerId: String?,
    @param:Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class MemoryComponentDto(
    @param:Json(name = "component_type") val componentType: String,
    @param:Json(name = "display_name") val displayName: String,
    val description: String,
    val binding: MemoryComponentBindingDto?,
) {
    fun toDomain() = MemoryComponentInfo(
        componentType = componentType,
        displayName = displayName,
        description = description,
        boundProviderId = binding?.providerId,
        thinkingEffort = binding?.thinkingEffort.toThinkingEffort(),
    )
}

@JsonClass(generateAdapter = true)
data class MemoryComponentsResponse(
    val components: List<MemoryComponentDto>,
)

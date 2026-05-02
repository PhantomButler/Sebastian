package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SoulCurrentDto(
    @param:Json(name = "active_soul") val activeSoul: String,
)

package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AttachmentUploadResponseDto(
    @param:Json(name = "attachment_id") val attachmentId: String,
    @param:Json(name = "kind") val kind: String,
    @param:Json(name = "filename") val filename: String,
    @param:Json(name = "mime_type") val mimeType: String,
    @param:Json(name = "size_bytes") val sizeBytes: Long,
    @param:Json(name = "sha256") val sha256: String,
    @param:Json(name = "text_excerpt") val textExcerpt: String? = null,
    @param:Json(name = "status") val status: String,
)

package com.sebastian.android.data.model

enum class AttachmentKind { IMAGE, TEXT_FILE }

data class ModelInputCapabilities(
    val supportsImageInput: Boolean = false,
    val supportsTextFileInput: Boolean = true,
)

sealed class AttachmentUploadState {
    object Local : AttachmentUploadState()
    data class Uploading(val progress: Float = 0f) : AttachmentUploadState()
    data class Uploaded(val attachmentId: String) : AttachmentUploadState()
    data class Failed(val reason: String) : AttachmentUploadState()
}

data class PendingAttachment(
    val localId: String,
    val kind: AttachmentKind,
    val uri: android.net.Uri,
    val filename: String,
    val mimeType: String,
    val sizeBytes: Long,
    val uploadState: AttachmentUploadState = AttachmentUploadState.Local,
) {
    val attachmentId: String? get() = (uploadState as? AttachmentUploadState.Uploaded)?.attachmentId
}

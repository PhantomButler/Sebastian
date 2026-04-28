package com.sebastian.android.viewmodel

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import com.sebastian.android.data.model.AttachmentKind
import com.sebastian.android.data.model.AttachmentUploadState
import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.ModelInputCapabilities
import com.sebastian.android.data.model.PendingAttachment
import com.sebastian.android.data.repository.ChatRepository
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

internal class ChatAttachmentManager(
    private val context: Context,
    private val chatRepository: ChatRepository,
    private val dispatcher: CoroutineDispatcher,
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val uiEffects: MutableSharedFlow<ChatUiEffect>,
) {

    fun onAttachmentMenuImageSelected() {
        if (!uiState.value.inputCapabilities.supportsImageInput) {
            scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("当前模型不支持图片输入")) }
            return
        }
        scope.launch { uiEffects.emit(ChatUiEffect.RequestImagePicker) }
    }

    fun onAttachmentImagePicked(uri: Uri, filename: String, mimeType: String, sizeBytes: Long) {
        val current = uiState.value.pendingAttachments
        if (current.size >= 5) {
            scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("最多添加 5 个附件")) }
            return
        }
        val att = PendingAttachment(
            localId = UUID.randomUUID().toString(),
            kind = AttachmentKind.IMAGE,
            uri = uri,
            filename = filename,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
            uploadState = AttachmentUploadState.Uploading(),
        )
        uiState.update { it.copy(pendingAttachments = it.pendingAttachments + att) }
        scope.launch(dispatcher) { uploadSingleAttachment(att) }
    }

    fun onAttachmentFilePicked(uri: Uri, filename: String, mimeType: String, sizeBytes: Long) {
        val supportedExtensions = setOf(".txt", ".md", ".csv", ".json", ".log")
        val ext = filename.substringAfterLast('.', "").let { if (it.isEmpty()) "" else ".$it" }.lowercase()
        if (ext !in supportedExtensions) {
            scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("不支持的文件格式")) }
            return
        }
        val current = uiState.value.pendingAttachments
        if (current.size >= 5) {
            scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("最多添加 5 个附件")) }
            return
        }
        if (!uiState.value.inputCapabilities.supportsTextFileInput) {
            scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("当前模型不支持文本文件输入")) }
            return
        }
        val att = PendingAttachment(
            localId = UUID.randomUUID().toString(),
            kind = AttachmentKind.TEXT_FILE,
            uri = uri,
            filename = filename,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
            uploadState = AttachmentUploadState.Uploading(),
        )
        uiState.update { it.copy(pendingAttachments = it.pendingAttachments + att) }
        scope.launch(dispatcher) { uploadSingleAttachment(att) }
    }

    fun onRemoveAttachment(localId: String) {
        uiState.update { it.copy(pendingAttachments = it.pendingAttachments.filter { a -> a.localId != localId }) }
    }

    fun onRetryAttachment(localId: String) {
        val att = uiState.value.pendingAttachments.find { it.localId == localId } ?: return
        val uploading = att.copy(uploadState = AttachmentUploadState.Uploading())
        uiState.update {
            it.copy(
                pendingAttachments = it.pendingAttachments.map { a ->
                    if (a.localId == localId) uploading else a
                },
            )
        }
        scope.launch(dispatcher) { uploadSingleAttachment(uploading) }
    }

    private suspend fun uploadSingleAttachment(att: PendingAttachment) {
        val result = chatRepository.uploadAttachment(att, context.contentResolver)
        result.onSuccess { uploaded ->
            uiState.update { state ->
                state.copy(
                    pendingAttachments = state.pendingAttachments.map { a ->
                        if (a.localId == att.localId) uploaded else a
                    },
                )
            }
        }
        result.onFailure {
            val failed = att.copy(uploadState = AttachmentUploadState.Failed("上传失败"))
            uiState.update { state ->
                state.copy(
                    pendingAttachments = state.pendingAttachments.map { a ->
                        if (a.localId == att.localId) failed else a
                    },
                )
            }
            scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("附件上传失败，请重试")) }
        }
    }

    /**
     * Uploads all attachments not yet in [AttachmentUploadState.Uploaded] state.
     * Returns the final list (all Uploaded) on success, or null if any upload failed.
     */
    internal suspend fun uploadPendingAttachments(
        attachments: List<PendingAttachment>,
        contentResolver: ContentResolver,
    ): List<PendingAttachment>? {
        var current = attachments
        for (att in current) {
            if (att.uploadState is AttachmentUploadState.Uploaded) continue
            val result = chatRepository.uploadAttachment(att, contentResolver)
            result.onSuccess { uploaded ->
                current = current.map { if (it.localId == att.localId) uploaded else it }
                uiState.update { state ->
                    state.copy(
                        pendingAttachments = state.pendingAttachments.map { a ->
                            if (a.localId == att.localId) uploaded else a
                        },
                    )
                }
            }
            result.onFailure { _ ->
                val failed = att.copy(uploadState = AttachmentUploadState.Failed("上传失败"))
                uiState.update { state ->
                    state.copy(
                        pendingAttachments = state.pendingAttachments.map { a ->
                            if (a.localId == att.localId) failed else a
                        },
                        composerState = ComposerState.IDLE_READY,
                        agentAnimState = AgentAnimState.IDLE,
                    )
                }
                scope.launch { uiEffects.emit(ChatUiEffect.ShowToast("附件上传失败，请重试")) }
                return null
            }
        }
        return current
    }
}

internal fun PendingAttachment.toContentBlock(baseUrl: String): ContentBlock = when (kind) {
    AttachmentKind.IMAGE -> ContentBlock.ImageBlock(
        blockId = localId,
        attachmentId = attachmentId ?: localId,
        filename = filename,
        mimeType = mimeType,
        sizeBytes = sizeBytes,
        downloadUrl = attachmentId?.let { "$baseUrl/api/v1/attachments/$it" } ?: uri.toString(),
        thumbnailUrl = attachmentId?.let { "$baseUrl/api/v1/attachments/$it/thumbnail" },
    )
    AttachmentKind.TEXT_FILE -> ContentBlock.FileBlock(
        blockId = localId,
        attachmentId = attachmentId ?: localId,
        filename = filename,
        mimeType = mimeType,
        sizeBytes = sizeBytes,
        downloadUrl = attachmentId?.let { "$baseUrl/api/v1/attachments/$it" } ?: uri.toString(),
    )
}

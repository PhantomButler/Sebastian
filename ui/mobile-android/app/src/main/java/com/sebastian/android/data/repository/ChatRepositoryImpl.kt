package com.sebastian.android.data.repository

import com.sebastian.android.data.model.ApprovalSnapshot
import com.sebastian.android.data.model.AttachmentKind
import com.sebastian.android.data.model.AttachmentUploadState
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.PendingAttachment
import com.sebastian.android.data.model.TodoItem
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.SseClient
import com.sebastian.android.data.remote.SseEnvelope
import com.sebastian.android.data.remote.dto.SendTurnRequest
import com.sebastian.android.data.remote.dto.toMessagesFromTimeline
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    private val sseClient: SseClient,
    private val settingsRepository: SettingsRepository,
) : ChatRepository {

    override fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String?): Flow<SseEnvelope> =
        sseClient.sessionStream(baseUrl, sessionId, lastEventId)

    override fun globalStream(baseUrl: String, lastEventId: String?): Flow<SseEnvelope> =
        sseClient.globalStream(baseUrl, lastEventId)

    override suspend fun getMessages(sessionId: String): Result<List<Message>> = runCatching {
        val response = apiService.getSession(sessionId, includeArchived = true)
        val baseUrl = settingsRepository.serverUrl.first()
        if (response.timelineItems.isNotEmpty()) {
            response.timelineItems.toMessagesFromTimeline(baseUrl = baseUrl)
        } else {
            response.messages.mapIndexed { index, dto -> dto.toDomain(sessionId, index) }
        }
    }

    override suspend fun sendTurn(sessionId: String?, content: String, attachmentIds: List<String>): Result<String> = runCatching {
        val response = apiService.sendTurn(
            SendTurnRequest(
                content = content,
                sessionId = sessionId,
                attachmentIds = attachmentIds,
            )
        )
        response.sessionId
    }

    override suspend fun sendSessionTurn(sessionId: String, content: String, attachmentIds: List<String>): Result<Unit> = runCatching {
        apiService.sendSessionTurn(sessionId, SendTurnRequest(content = content, attachmentIds = attachmentIds))
        Unit
    }

    override suspend fun cancelTurn(sessionId: String): Result<Unit> = runCatching {
        apiService.cancelSession(sessionId)
        Unit
    }

    override suspend fun grantApproval(approvalId: String): Result<Unit> = runCatching {
        apiService.grantApproval(approvalId)
        Unit
    }

    override suspend fun denyApproval(approvalId: String): Result<Unit> = runCatching {
        apiService.denyApproval(approvalId)
        Unit
    }

    override suspend fun getPendingApprovals(): Result<List<ApprovalSnapshot>> = runCatching {
        apiService.getPendingApprovals().approvals.map { dto ->
            ApprovalSnapshot(
                approvalId = dto.id,
                sessionId = dto.sessionId,
                agentType = dto.agentType ?: "sebastian",
                toolName = dto.toolName,
                // 注意：Moshi 把 JSON 数字全解码为 Double，JSONObject 再 toString 时整数会保留小数点；
                // 这里只作为 UI 展示用的原始 JSON，不做类型敏感操作。
                toolInputJson = org.json.JSONObject(dto.toolInput ?: emptyMap<String, Any>()).toString(),
                reason = dto.reason.orEmpty(),
            )
        }
    }

    override suspend fun getTodos(sessionId: String): Result<List<TodoItem>> = runCatching {
        apiService.getTodos(sessionId).todos.map { it.toDomain() }
    }

    override suspend fun uploadAttachment(
        pending: PendingAttachment,
        contentResolver: android.content.ContentResolver,
    ): Result<PendingAttachment> = runCatching {
        val bytes = withContext(Dispatchers.IO) {
            contentResolver.openInputStream(pending.uri)?.use { it.readBytes() }
                ?: error("Cannot open attachment: file not accessible")
        }
        val mediaType = pending.mimeType.toMediaTypeOrNull()
        val requestBody = bytes.toRequestBody(mediaType)
        val filePart = MultipartBody.Part.createFormData("file", pending.filename, requestBody)
        val kindValue = when (pending.kind) {
            AttachmentKind.IMAGE -> "image"
            AttachmentKind.TEXT_FILE -> "text_file"
        }
        val kindBody = kindValue.toRequestBody("text/plain".toMediaTypeOrNull())
        val response = apiService.uploadAttachment(kind = kindBody, file = filePart)
        pending.copy(uploadState = AttachmentUploadState.Uploaded(attachmentId = response.id))
    }
}

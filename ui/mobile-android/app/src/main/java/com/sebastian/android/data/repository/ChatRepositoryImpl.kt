package com.sebastian.android.data.repository

import com.sebastian.android.data.model.ApprovalSnapshot
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.TodoItem
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.SseClient
import com.sebastian.android.data.remote.SseEnvelope
import com.sebastian.android.data.remote.dto.SendTurnRequest
import com.sebastian.android.data.remote.dto.toMessagesFromTimeline
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    private val sseClient: SseClient,
) : ChatRepository {

    override fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String?): Flow<SseEnvelope> =
        sseClient.sessionStream(baseUrl, sessionId, lastEventId)

    override fun globalStream(baseUrl: String, lastEventId: String?): Flow<SseEnvelope> =
        sseClient.globalStream(baseUrl, lastEventId)

    override suspend fun getMessages(sessionId: String): Result<List<Message>> = runCatching {
        val response = apiService.getSession(sessionId, includeArchived = true)
        if (response.timelineItems.isNotEmpty()) {
            response.timelineItems.toMessagesFromTimeline()
        } else {
            response.messages.mapIndexed { index, dto -> dto.toDomain(sessionId, index) }
        }
    }

    override suspend fun sendTurn(sessionId: String?, content: String): Result<String> = runCatching {
        val response = apiService.sendTurn(
            SendTurnRequest(
                content = content,
                sessionId = sessionId,
            )
        )
        response.sessionId
    }

    override suspend fun sendSessionTurn(sessionId: String, content: String): Result<Unit> = runCatching {
        apiService.sendSessionTurn(sessionId, SendTurnRequest(content = content))
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
}

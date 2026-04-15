package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.SseClient
import com.sebastian.android.data.remote.dto.SendTurnRequest
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    private val sseClient: SseClient,
) : ChatRepository {

    override fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String?): Flow<StreamEvent> =
        sseClient.sessionStream(baseUrl, sessionId, lastEventId)

    override fun globalStream(baseUrl: String, lastEventId: String?): Flow<StreamEvent> =
        sseClient.globalStream(baseUrl, lastEventId)

    override suspend fun getMessages(sessionId: String): Result<List<Message>> = runCatching {
        apiService.getSession(sessionId).messages.mapIndexed { index, dto -> dto.toDomain(sessionId, index) }
    }

    override suspend fun sendTurn(sessionId: String?, content: String, effort: ThinkingEffort): Result<String> = runCatching {
        val response = apiService.sendTurn(
            SendTurnRequest(
                content = content,
                sessionId = sessionId,
                thinkingEffort = effort.toApiString(),
            )
        )
        response.sessionId
    }

    override suspend fun sendSessionTurn(sessionId: String, content: String, effort: ThinkingEffort): Result<Unit> = runCatching {
        apiService.sendSessionTurn(sessionId, SendTurnRequest(content = content, thinkingEffort = effort.toApiString()))
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

    override suspend fun getPendingApprovals(): Result<List<com.sebastian.android.viewmodel.ApprovalSnapshot>> = runCatching {
        apiService.getPendingApprovals().approvals.map { dto ->
            com.sebastian.android.viewmodel.ApprovalSnapshot(
                approvalId = dto.id,
                sessionId = dto.sessionId,
                agentType = dto.agentType ?: "sebastian",
                toolName = dto.toolName,
                toolInputJson = org.json.JSONObject(dto.toolInput ?: emptyMap<String, Any>()).toString(),
                reason = dto.reason.orEmpty(),
            )
        }
    }

    override suspend fun getSessionRecent(sessionId: String, limit: Int): Result<List<Message>> = runCatching {
        apiService.getSessionRecent(sessionId, limit).messages
            .mapIndexed { index, dto -> dto.toDomain(sessionId, index) }
    }

    private fun ThinkingEffort.toApiString(): String? = when (this) {
        ThinkingEffort.OFF -> null
        ThinkingEffort.ON -> "on"
        ThinkingEffort.LOW -> "low"
        ThinkingEffort.MEDIUM -> "medium"
        ThinkingEffort.HIGH -> "high"
        ThinkingEffort.MAX -> "max"
    }
}

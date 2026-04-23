package com.sebastian.android.data.repository

import com.sebastian.android.data.model.ApprovalSnapshot
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.remote.SseEnvelope
import kotlinx.coroutines.flow.Flow

interface ChatRepository {
    fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<SseEnvelope>
    fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<SseEnvelope>
    suspend fun getMessages(sessionId: String): Result<List<Message>>
    /** Returns the session_id assigned by the backend. */
    suspend fun sendTurn(sessionId: String?, content: String): Result<String>
    suspend fun sendSessionTurn(sessionId: String, content: String): Result<Unit>
    suspend fun cancelTurn(sessionId: String): Result<Unit>
    suspend fun grantApproval(approvalId: String): Result<Unit>
    suspend fun denyApproval(approvalId: String): Result<Unit>
    suspend fun getPendingApprovals(): Result<List<ApprovalSnapshot>>
}

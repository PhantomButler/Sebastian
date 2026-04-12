package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import kotlinx.coroutines.flow.Flow

interface ChatRepository {
    fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<StreamEvent>
    fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<StreamEvent>
    suspend fun getMessages(sessionId: String): Result<List<Message>>
    suspend fun sendTurn(content: String, effort: ThinkingEffort): Result<Unit>
    suspend fun sendSessionTurn(sessionId: String, content: String, effort: ThinkingEffort): Result<Unit>
    suspend fun cancelTurn(sessionId: String): Result<Unit>
    suspend fun grantApproval(approvalId: String): Result<Unit>
    suspend fun denyApproval(approvalId: String): Result<Unit>
}

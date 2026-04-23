package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Session
import kotlinx.coroutines.flow.Flow

interface SessionRepository {
    fun sessionsFlow(): Flow<List<Session>>
    suspend fun loadSessions(): Result<List<Session>>
    suspend fun createSession(title: String? = null): Result<Session>
    suspend fun deleteSession(sessionId: String): Result<Unit>
    suspend fun getAgentSessions(agentType: String): Result<List<Session>>
    suspend fun loadAgentSessions(agentType: String): Result<List<Session>>
    suspend fun createAgentSession(agentType: String, title: String? = null, sessionId: String? = null): Result<Session>
}

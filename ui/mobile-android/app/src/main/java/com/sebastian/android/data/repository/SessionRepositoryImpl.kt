package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Session
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.CreateSessionRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SessionRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
) : SessionRepository {

    private val _sessions = MutableStateFlow<List<Session>>(emptyList())

    override fun sessionsFlow(): Flow<List<Session>> = _sessions.asStateFlow()

    override suspend fun loadSessions(): Result<List<Session>> = runCatching {
        val sessions = apiService.getSessions().map { it.toDomain() }
        _sessions.value = sessions
        sessions
    }

    override suspend fun createSession(title: String?): Result<Session> = runCatching {
        val session = apiService.createAgentSession("sebastian", CreateSessionRequest(title = title)).toDomain()
        _sessions.value = listOf(session) + _sessions.value
        session
    }

    override suspend fun deleteSession(sessionId: String): Result<Unit> = runCatching {
        _sessions.value = _sessions.value.filter { it.id != sessionId }
        // 后端暂无 delete session API，本地移除即可
    }

    override suspend fun getAgentSessions(agentType: String): Result<List<Session>> = runCatching {
        apiService.getAgentSessions(agentType).map { it.toDomain() }
    }

    override suspend fun createAgentSession(agentType: String, title: String?): Result<Session> = runCatching {
        apiService.createAgentSession(agentType, CreateSessionRequest(title = title)).toDomain()
    }
}

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
        val sessions = apiService.getSessions().sessions.map { it.toDomain() }
        _sessions.value = sessions
        sessions
    }

    override suspend fun createSession(title: String?): Result<Session> = runCatching {
        val response = apiService.createAgentSession(
            "sebastian",
            CreateSessionRequest(content = title ?: "新对话"),
        )
        val domain = Session(
            id = response.sessionId,
            title = title ?: "新对话",
            agentType = "sebastian",
        )
        _sessions.value = listOf(domain) + _sessions.value
        domain
    }

    override suspend fun deleteSession(sessionId: String): Result<Unit> = runCatching {
        apiService.deleteSession(sessionId)
        _sessions.value = _sessions.value.filter { it.id != sessionId }
    }

    override suspend fun getAgentSessions(agentType: String): Result<List<Session>> = runCatching {
        apiService.getAgentSessions(agentType).sessions.map { it.toDomain() }
    }

    override suspend fun createAgentSession(agentType: String, title: String?): Result<Session> = runCatching {
        val response = apiService.createAgentSession(
            agentType,
            CreateSessionRequest(content = title ?: "新对话"),
        )
        Session(
            id = response.sessionId,
            title = title ?: "新对话",
            agentType = agentType,
        )
    }
}

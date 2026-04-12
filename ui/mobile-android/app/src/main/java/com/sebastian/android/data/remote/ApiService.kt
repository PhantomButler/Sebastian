package com.sebastian.android.data.remote

import com.sebastian.android.data.remote.dto.*
import retrofit2.http.*

interface ApiService {
    // 认证
    @POST("api/v1/auth/login")
    suspend fun login(@Body body: Map<String, String>): Map<String, String>

    // 主对话 turn
    @POST("api/v1/turns")
    suspend fun sendTurn(@Body body: SendTurnRequest): TurnDto

    // SubAgent session turn
    @POST("api/v1/sessions/{sessionId}/turns")
    suspend fun sendSessionTurn(
        @Path("sessionId") sessionId: String,
        @Body body: SendTurnRequest,
    ): TurnDto

    // Sessions
    @GET("api/v1/sessions")
    suspend fun getSessions(): SessionListResponse

    @GET("api/v1/sessions/{sessionId}")
    suspend fun getSession(@Path("sessionId") sessionId: String): SessionDto

    @DELETE("api/v1/sessions/{sessionId}")
    suspend fun deleteSession(@Path("sessionId") sessionId: String): OkResponse

    @POST("api/v1/sessions/{sessionId}/cancel")
    suspend fun cancelSession(@Path("sessionId") sessionId: String): OkResponse

    @GET("api/v1/messages")
    suspend fun getMessages(@Query("session_id") sessionId: String): List<MessageDto>

    // SubAgent sessions
    @GET("api/v1/agents/{agentType}/sessions")
    suspend fun getAgentSessions(@Path("agentType") agentType: String): AgentSessionListResponse

    @POST("api/v1/agents/{agentType}/sessions")
    suspend fun createAgentSession(
        @Path("agentType") agentType: String,
        @Body body: CreateSessionRequest,
    ): SessionDto

    // Agents
    @GET("api/v1/agents")
    suspend fun getAgents(): List<Map<String, Any>>

    // Providers
    @GET("api/v1/llm/providers")
    suspend fun getProviders(): List<ProviderDto>

    @POST("api/v1/llm/providers")
    suspend fun createProvider(@Body body: ProviderDto): ProviderDto

    @PUT("api/v1/llm/providers/{id}")
    suspend fun updateProvider(@Path("id") id: String, @Body body: ProviderDto): ProviderDto

    @DELETE("api/v1/llm/providers/{id}")
    suspend fun deleteProvider(@Path("id") id: String): OkResponse

    @POST("api/v1/llm/providers/{id}/set-default")
    suspend fun setDefaultProvider(@Path("id") id: String): OkResponse

    // Approvals
    @GET("api/v1/approvals")
    suspend fun getPendingApprovals(): List<Map<String, Any>>

    @POST("api/v1/approvals/{approvalId}/grant")
    suspend fun grantApproval(@Path("approvalId") approvalId: String): OkResponse

    @POST("api/v1/approvals/{approvalId}/deny")
    suspend fun denyApproval(@Path("approvalId") approvalId: String): OkResponse

    // Health
    @GET("api/v1/health")
    suspend fun health(): Map<String, Any>
}

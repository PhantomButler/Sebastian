package com.sebastian.android.data.remote

import com.sebastian.android.data.remote.dto.*
import retrofit2.http.*

interface ApiService {
    // 认证
    @POST("api/v1/auth/login")
    suspend fun login(@Body body: Map<String, String>): Map<String, String>

    @POST("api/v1/auth/logout")
    suspend fun logout(): Map<String, Any>

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
    suspend fun getSession(@Path("sessionId") sessionId: String): SessionDetailResponse

    @GET("api/v1/sessions/{sessionId}/recent")
    suspend fun getSessionRecent(
        @Path("sessionId") sessionId: String,
        @Query("limit") limit: Int = 50,
    ): SessionRecentResponse

    @DELETE("api/v1/sessions/{sessionId}")
    suspend fun deleteSession(@Path("sessionId") sessionId: String)

    @POST("api/v1/sessions/{sessionId}/cancel")
    suspend fun cancelSession(@Path("sessionId") sessionId: String): OkResponse

    // SubAgent sessions
    @GET("api/v1/agents/{agentType}/sessions")
    suspend fun getAgentSessions(@Path("agentType") agentType: String): AgentSessionListResponse

    @POST("api/v1/agents/{agentType}/sessions")
    suspend fun createAgentSession(
        @Path("agentType") agentType: String,
        @Body body: CreateSessionRequest,
    ): TurnDto  // Backend returns {"session_id": "...", "ts": "..."}

    // Agents
    @GET("api/v1/agents")
    suspend fun getAgents(): AgentListResponse

    // Providers
    @GET("api/v1/llm-providers")
    suspend fun getProviders(): ProviderListResponse

    @POST("api/v1/llm-providers")
    suspend fun createProvider(@Body body: ProviderDto): ProviderDto

    @PUT("api/v1/llm-providers/{id}")
    suspend fun updateProvider(@Path("id") id: String, @Body body: Map<String, @JvmSuppressWildcards Any>): ProviderDto

    @DELETE("api/v1/llm-providers/{id}")
    suspend fun deleteProvider(@Path("id") id: String)

    // Approvals
    @GET("api/v1/approvals")
    suspend fun getPendingApprovals(): PendingApprovalsResponse

    @POST("api/v1/approvals/{approvalId}/grant")
    suspend fun grantApproval(@Path("approvalId") approvalId: String): OkResponse

    @POST("api/v1/approvals/{approvalId}/deny")
    suspend fun denyApproval(@Path("approvalId") approvalId: String): OkResponse

    // Debug
    @GET("api/v1/debug/logging")
    suspend fun getLogState(): LogStateDto

    @PATCH("api/v1/debug/logging")
    suspend fun patchLogState(@Body body: LogConfigPatchDto): LogStateDto

    // Health
    @GET("api/v1/health")
    suspend fun health(): Map<String, Any>
}

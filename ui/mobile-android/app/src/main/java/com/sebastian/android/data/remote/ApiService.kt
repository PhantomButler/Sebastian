package com.sebastian.android.data.remote

import com.sebastian.android.data.remote.dto.*
import okhttp3.MultipartBody
import okhttp3.RequestBody
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
    suspend fun getSession(
        @Path("sessionId") sessionId: String,
        @Query("include_archived") includeArchived: Boolean = true,
    ): SessionDetailResponse

    @DELETE("api/v1/sessions/{sessionId}")
    suspend fun deleteSession(@Path("sessionId") sessionId: String)

    @GET("api/v1/sessions/{sessionId}/todos")
    suspend fun getTodos(@Path("sessionId") sessionId: String): TodoListResponse

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

    @GET("api/v1/agents/{agentType}/llm-binding")
    suspend fun getAgentBinding(@Path("agentType") agentType: String): AgentBindingDto

    @PUT("api/v1/agents/{agentType}/llm-binding")
    suspend fun setAgentBinding(
        @Path("agentType") agentType: String,
        @Body body: SetBindingRequest,
    ): AgentBindingDto

    @DELETE("api/v1/agents/{agentType}/llm-binding")
    suspend fun clearAgentBinding(@Path("agentType") agentType: String)

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

    // Memory Settings
    @GET("api/v1/memory/settings")
    suspend fun getMemorySettings(): MemorySettingsDto

    @PUT("api/v1/memory/settings")
    suspend fun putMemorySettings(@Body body: MemorySettingsDto): MemorySettingsDto

    // Memory Components
    @GET("api/v1/memory/components")
    suspend fun listMemoryComponents(): MemoryComponentsResponse

    @GET("api/v1/memory/components/{componentType}/llm-binding")
    suspend fun getMemoryComponentBinding(
        @Path("componentType") componentType: String,
    ): MemoryComponentBindingDto

    @PUT("api/v1/memory/components/{componentType}/llm-binding")
    suspend fun setMemoryComponentBinding(
        @Path("componentType") componentType: String,
        @Body body: SetBindingRequest,
    ): MemoryComponentBindingDto

    @DELETE("api/v1/memory/components/{componentType}/llm-binding")
    suspend fun clearMemoryComponentBinding(@Path("componentType") componentType: String)

    // ── LLM Catalog / Account / Binding endpoints ────────────────────────

    @GET("api/v1/llm-catalog")
    suspend fun getLlmCatalog(): LlmCatalogResponseDto

    @GET("api/v1/llm-accounts")
    suspend fun getLlmAccounts(): LlmAccountListResponseDto

    @POST("api/v1/llm-accounts")
    suspend fun createLlmAccount(@Body body: LlmAccountCreateRequest): LlmAccountDto

    @PUT("api/v1/llm-accounts/{accountId}")
    suspend fun updateLlmAccount(
        @Path("accountId") accountId: String,
        @Body body: LlmAccountUpdateRequest,
    ): LlmAccountDto

    @DELETE("api/v1/llm-accounts/{accountId}")
    suspend fun deleteLlmAccount(@Path("accountId") accountId: String)

    @GET("api/v1/llm-accounts/{accountId}/models")
    suspend fun getCustomModels(@Path("accountId") accountId: String): CustomModelListResponseDto

    @POST("api/v1/llm-accounts/{accountId}/models")
    suspend fun createCustomModel(
        @Path("accountId") accountId: String,
        @Body body: CustomModelCreateRequest,
    ): CustomModelDto

    @PUT("api/v1/llm-accounts/{accountId}/models/{modelRecordId}")
    suspend fun updateCustomModel(
        @Path("accountId") accountId: String,
        @Path("modelRecordId") modelRecordId: String,
        @Body body: CustomModelUpdateRequest,
    ): CustomModelDto

    @DELETE("api/v1/llm-accounts/{accountId}/models/{modelRecordId}")
    suspend fun deleteCustomModel(
        @Path("accountId") accountId: String,
        @Path("modelRecordId") modelRecordId: String,
    )

    @GET("api/v1/llm-bindings/default")
    suspend fun getDefaultBinding(): AgentBindingDto

    @PUT("api/v1/llm-bindings/default")
    suspend fun setDefaultBinding(@Body body: SetBindingRequest): AgentBindingDto

    // Attachments
    @Multipart
    @POST("api/v1/attachments")
    suspend fun uploadAttachment(
        @Part("kind") kind: RequestBody,
        @Part file: MultipartBody.Part,
    ): AttachmentUploadResponseDto

    // Soul
    @GET("api/v1/soul/current")
    suspend fun getCurrentSoul(): SoulCurrentDto

    // Health
    @GET("api/v1/health")
    suspend fun health(): Map<String, Any>
}

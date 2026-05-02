package com.sebastian.android.data.repository

import com.sebastian.android.data.local.SecureTokenStore
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.model.*
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.*
import com.sebastian.android.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SettingsRepositoryImpl @Inject constructor(
    private val dataStore: SettingsDataStore,
    private val apiService: ApiService,
    private val tokenStore: SecureTokenStore,
    private val okHttpClient: OkHttpClient,
    @param:IoDispatcher private val dispatcher: CoroutineDispatcher,
) : SettingsRepository {

    override val serverUrl: Flow<String> = dataStore.serverUrl
    override val theme: Flow<String> = dataStore.theme
    override val activeSoul: Flow<String> = dataStore.activeSoul

    private val _isLoggedIn = MutableStateFlow(tokenStore.getToken() != null)
    override val isLoggedIn: Flow<Boolean> = _isLoggedIn.asStateFlow()

    override suspend fun saveServerUrl(url: String) = dataStore.saveServerUrl(url)
    override suspend fun saveTheme(theme: String) = dataStore.saveTheme(theme)
    override suspend fun saveActiveSoul(name: String) = dataStore.saveActiveSoul(name)
    override suspend fun fetchActiveSoul(): Result<String> = runCatching {
        apiService.getCurrentSoul().activeSoul
    }

    override suspend fun login(password: String): Result<Unit> = runCatching {
        val response = apiService.login(mapOf("password" to password))
        val token = response["access_token"] ?: throw Exception("未返回 token")
        tokenStore.saveToken(token)
        _isLoggedIn.value = true
    }

    override suspend fun logout(): Result<Unit> = runCatching {
        try {
            apiService.logout()
        } catch (_: Exception) {
        }
        tokenStore.clearToken()
        _isLoggedIn.value = false
    }

    override suspend fun testConnection(url: String): Result<Unit> = runCatching {
        withContext(dispatcher) {
            val trimmed = url.trimEnd('/')
            val response = okHttpClient.newCall(
                Request.Builder().url("$trimmed/api/v1/health").build()
            ).execute()
            response.use {
                if (!it.isSuccessful) throw Exception("HTTP ${it.code}")
            }
        }
    }

    override suspend fun getLogState(): Result<LogStateDto> = runCatching {
        apiService.getLogState()
    }

    override suspend fun patchLogState(llmStreamEnabled: Boolean?, sseEnabled: Boolean?): Result<LogStateDto> = runCatching {
        apiService.patchLogState(LogConfigPatchDto(llmStreamEnabled = llmStreamEnabled, sseEnabled = sseEnabled))
    }

    override suspend fun getMemorySettings(): Result<MemorySettingsDto> = runCatching {
        apiService.getMemorySettings()
    }

    override suspend fun setMemoryEnabled(enabled: Boolean): Result<MemorySettingsDto> = runCatching {
        apiService.putMemorySettings(MemorySettingsDto(enabled = enabled))
    }

    override suspend fun getLlmCatalog(): Result<List<CatalogProvider>> = runCatching {
        apiService.getLlmCatalog().providers.map { it.toDomain() }
    }

    override suspend fun getLlmAccounts(): Result<List<LlmAccount>> = runCatching {
        apiService.getLlmAccounts().accounts.map { it.toDomain() }
    }

    override suspend fun createLlmAccount(
        name: String,
        catalogProviderId: String,
        apiKey: String,
        providerType: String?,
        baseUrlOverride: String?,
    ): Result<LlmAccount> = runCatching {
        apiService.createLlmAccount(
            LlmAccountCreateRequest(
                name = name,
                catalogProviderId = catalogProviderId,
                apiKey = apiKey,
                providerType = providerType,
                baseUrlOverride = baseUrlOverride,
            )
        ).toDomain()
    }

    override suspend fun updateLlmAccount(
        accountId: String,
        name: String?,
        apiKey: String?,
        baseUrlOverride: String?,
    ): Result<LlmAccount> = runCatching {
        apiService.updateLlmAccount(
            accountId,
            LlmAccountUpdateRequest(name = name, apiKey = apiKey, baseUrlOverride = baseUrlOverride),
        ).toDomain()
    }

    override suspend fun deleteLlmAccount(accountId: String): Result<Unit> = runCatching {
        apiService.deleteLlmAccount(accountId)
    }

    override suspend fun getCustomModels(accountId: String): Result<List<CustomModel>> = runCatching {
        apiService.getCustomModels(accountId).models.map { it.toDomain() }
    }

    override suspend fun createCustomModel(
        accountId: String,
        modelId: String,
        displayName: String,
        contextWindowTokens: Long,
        thinkingCapability: String?,
        thinkingFormat: String?,
    ): Result<CustomModel> = runCatching {
        apiService.createCustomModel(
            accountId,
            CustomModelCreateRequest(
                modelId = modelId,
                displayName = displayName,
                contextWindowTokens = contextWindowTokens,
                thinkingCapability = thinkingCapability,
                thinkingFormat = thinkingFormat,
            ),
        ).toDomain()
    }

    override suspend fun updateCustomModel(
        accountId: String,
        modelRecordId: String,
        modelId: String?,
        displayName: String?,
        contextWindowTokens: Long?,
        thinkingCapability: String?,
        thinkingFormat: String?,
    ): Result<CustomModel> = runCatching {
        apiService.updateCustomModel(
            accountId,
            modelRecordId,
            CustomModelUpdateRequest(
                modelId = modelId,
                displayName = displayName,
                contextWindowTokens = contextWindowTokens,
                thinkingCapability = thinkingCapability,
                thinkingFormat = thinkingFormat,
            ),
        ).toDomain()
    }

    override suspend fun deleteCustomModel(accountId: String, modelRecordId: String): Result<Unit> = runCatching {
        apiService.deleteCustomModel(accountId, modelRecordId)
    }

    override suspend fun getDefaultBinding(): Result<AgentBinding?> = runCatching {
        apiService.getDefaultBinding().toDomain()
    }

    override suspend fun setDefaultBinding(
        accountId: String,
        modelId: String,
        thinkingEffort: String?,
    ): Result<AgentBinding> = runCatching {
        apiService.setDefaultBinding(
            SetBindingRequest(accountId = accountId, modelId = modelId, thinkingEffort = thinkingEffort),
        ).toDomain()
    }
}

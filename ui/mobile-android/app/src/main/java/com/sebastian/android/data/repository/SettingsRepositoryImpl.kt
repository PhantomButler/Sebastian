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
import kotlinx.coroutines.flow.map
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

    private val _isLoggedIn = MutableStateFlow(tokenStore.getToken() != null)
    override val isLoggedIn: Flow<Boolean> = _isLoggedIn.asStateFlow()

    private val _providers = MutableStateFlow<List<Provider>>(emptyList())

    override val currentProvider: Flow<Provider?> = _providers.map { list ->
        list.firstOrNull { it.isDefault }
    }

    override fun providersFlow(): Flow<List<Provider>> = _providers.asStateFlow()

    override suspend fun saveServerUrl(url: String) = dataStore.saveServerUrl(url)
    override suspend fun saveTheme(theme: String) = dataStore.saveTheme(theme)

    override suspend fun getProviders(): Result<List<Provider>> = runCatching {
        val providers = apiService.getProviders().providers.map { it.toDomain() }
        _providers.value = providers
        providers
    }

    override suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?, model: String?, thinkingCapability: String?, isDefault: Boolean): Result<Provider> = runCatching {
        val dto = apiService.createProvider(ProviderDto(name = name, providerType = type, baseUrl = baseUrl, apiKey = apiKey, model = model, thinkingCapability = thinkingCapability, isDefault = isDefault))
        val provider = dto.toDomain()
        if (isDefault) {
            _providers.value = _providers.value.map { it.copy(isDefault = false) } + provider
        } else {
            _providers.value = _providers.value + provider
        }
        provider
    }

    override suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?, model: String?, thinkingCapability: String?, isDefault: Boolean): Result<Provider> = runCatching {
        val body = buildMap<String, Any> {
            put("name", name)
            put("provider_type", type)
            put("is_default", isDefault)
            baseUrl?.let { put("base_url", it) }
            apiKey?.let { put("api_key", it) }
            model?.let { put("model", it) }
            thinkingCapability?.let { put("thinking_capability", it) }
        }
        val dto = apiService.updateProvider(id, body)
        val provider = dto.toDomain()
        _providers.value = _providers.value.map {
            when {
                it.id == id -> provider
                isDefault -> it.copy(isDefault = false)
                else -> it
            }
        }
        provider
    }

    override suspend fun deleteProvider(id: String): Result<Unit> = runCatching {
        apiService.deleteProvider(id)
        _providers.value = _providers.value.filter { it.id != id }
    }

    override suspend fun setDefaultProvider(id: String): Result<Unit> = runCatching {
        val current = _providers.value.firstOrNull { it.id == id }
            ?: throw Exception("Provider not found")
        val body = buildMap<String, Any> {
            put("name", current.name)
            put("provider_type", current.type)
            put("is_default", true)
            current.baseUrl?.let { put("base_url", it) }
        }
        apiService.updateProvider(id, body)
        _providers.value = _providers.value.map { it.copy(isDefault = it.id == id) }
        dataStore.saveActiveProviderId(id)
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

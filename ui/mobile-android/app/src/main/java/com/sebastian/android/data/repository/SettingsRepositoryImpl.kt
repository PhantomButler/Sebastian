package com.sebastian.android.data.repository

import com.sebastian.android.data.local.SecureTokenStore
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.LogConfigPatchDto
import com.sebastian.android.data.remote.dto.LogStateDto
import com.sebastian.android.data.remote.dto.ProviderDto
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
        // 只发送有值的字段，避免用 null 覆盖服务端已有数据（如 api_key）
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
            // 忽略 logout 网络错误，确保本地能清除
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
}

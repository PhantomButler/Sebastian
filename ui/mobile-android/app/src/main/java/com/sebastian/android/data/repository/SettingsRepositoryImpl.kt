package com.sebastian.android.data.repository

import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.ProviderDto
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
    private val okHttpClient: OkHttpClient,
) : SettingsRepository {

    override val serverUrl: Flow<String> = dataStore.serverUrl
    override val theme: Flow<String> = dataStore.theme

    private val _providers = MutableStateFlow<List<Provider>>(emptyList())

    override fun providersFlow(): Flow<List<Provider>> = _providers.asStateFlow()

    override suspend fun saveServerUrl(url: String) = dataStore.saveServerUrl(url)
    override suspend fun saveTheme(theme: String) = dataStore.saveTheme(theme)

    override suspend fun getProviders(): Result<List<Provider>> = runCatching {
        val dtos = apiService.getProviders()
        val providers = dtos.map { it.toDomain() }
        _providers.value = providers
        providers
    }

    override suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider> = runCatching {
        val dto = apiService.createProvider(ProviderDto(name = name, type = type, baseUrl = baseUrl, apiKey = apiKey))
        val provider = dto.toDomain()
        _providers.value = _providers.value + provider
        provider
    }

    override suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider> = runCatching {
        val dto = apiService.updateProvider(id, ProviderDto(name = name, type = type, baseUrl = baseUrl, apiKey = apiKey))
        val provider = dto.toDomain()
        _providers.value = _providers.value.map { if (it.id == id) provider else it }
        provider
    }

    override suspend fun deleteProvider(id: String): Result<Unit> = runCatching {
        apiService.deleteProvider(id)
        _providers.value = _providers.value.filter { it.id != id }
    }

    override suspend fun setDefaultProvider(id: String): Result<Unit> = runCatching {
        apiService.setDefaultProvider(id)
        _providers.value = _providers.value.map { it.copy(isDefault = it.id == id) }
        dataStore.saveActiveProviderId(id)
    }

    override suspend fun testConnection(url: String): Result<Unit> = runCatching {
        withContext(kotlinx.coroutines.Dispatchers.IO) {
            val trimmed = url.trimEnd('/')
            val response = okHttpClient.newCall(
                Request.Builder().url("$trimmed/api/v1/health").build()
            ).execute()
            response.use {
                if (!it.isSuccessful) throw Exception("HTTP ${it.code}")
            }
        }
    }
}

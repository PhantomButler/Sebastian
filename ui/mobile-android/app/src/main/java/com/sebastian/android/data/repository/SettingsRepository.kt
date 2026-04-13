package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.remote.dto.LogStateDto
import kotlinx.coroutines.flow.Flow

interface SettingsRepository {
    val serverUrl: Flow<String>
    val theme: Flow<String>
    val currentProvider: Flow<Provider?>          // 当前激活 Provider
    val isLoggedIn: Flow<Boolean>
    suspend fun saveServerUrl(url: String)
    suspend fun saveTheme(theme: String)
    suspend fun login(password: String): Result<Unit>
    suspend fun logout(): Result<Unit>
    fun providersFlow(): Flow<List<Provider>>
    suspend fun getProviders(): Result<List<Provider>>
    suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?, model: String?, thinkingCapability: String?, isDefault: Boolean): Result<Provider>
    suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?, model: String?, thinkingCapability: String?, isDefault: Boolean): Result<Provider>
    suspend fun deleteProvider(id: String): Result<Unit>
    suspend fun setDefaultProvider(id: String): Result<Unit>
    suspend fun testConnection(url: String): Result<Unit>
    suspend fun getLogState(): Result<LogStateDto>
    suspend fun patchLogState(llmStreamEnabled: Boolean? = null, sseEnabled: Boolean? = null): Result<LogStateDto>
}

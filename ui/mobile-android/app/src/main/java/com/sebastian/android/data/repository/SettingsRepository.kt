package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Provider
import kotlinx.coroutines.flow.Flow

interface SettingsRepository {
    val serverUrl: Flow<String>
    val theme: Flow<String>
    suspend fun saveServerUrl(url: String)
    suspend fun saveTheme(theme: String)
    fun providersFlow(): Flow<List<Provider>>
    suspend fun getProviders(): Result<List<Provider>>
    suspend fun createProvider(name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider>
    suspend fun updateProvider(id: String, name: String, type: String, baseUrl: String?, apiKey: String?): Result<Provider>
    suspend fun deleteProvider(id: String): Result<Unit>
    suspend fun setDefaultProvider(id: String): Result<Unit>
    suspend fun testConnection(url: String): Result<Unit>
}

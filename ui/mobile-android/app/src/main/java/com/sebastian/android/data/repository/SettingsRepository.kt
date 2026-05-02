package com.sebastian.android.data.repository

import com.sebastian.android.data.model.*
import com.sebastian.android.data.remote.dto.LogStateDto
import com.sebastian.android.data.remote.dto.MemorySettingsDto
import kotlinx.coroutines.flow.Flow

interface SettingsRepository {
    val serverUrl: Flow<String>
    val theme: Flow<String>
    val isLoggedIn: Flow<Boolean>
    suspend fun saveServerUrl(url: String)
    suspend fun saveTheme(theme: String)
    suspend fun login(password: String): Result<Unit>
    suspend fun logout(): Result<Unit>
    suspend fun testConnection(url: String): Result<Unit>
    suspend fun getLogState(): Result<LogStateDto>
    suspend fun patchLogState(llmStreamEnabled: Boolean? = null, sseEnabled: Boolean? = null): Result<LogStateDto>
    suspend fun getMemorySettings(): Result<MemorySettingsDto>
    suspend fun setMemoryEnabled(enabled: Boolean): Result<MemorySettingsDto>

    val activeSoul: Flow<String>
    suspend fun saveActiveSoul(name: String)
    suspend fun fetchActiveSoul(): Result<String>

    suspend fun getLlmCatalog(): Result<List<CatalogProvider>>
    suspend fun getLlmAccounts(): Result<List<LlmAccount>>
    suspend fun createLlmAccount(name: String, catalogProviderId: String, apiKey: String, providerType: String?, baseUrlOverride: String?): Result<LlmAccount>
    suspend fun updateLlmAccount(accountId: String, name: String?, apiKey: String?, baseUrlOverride: String?): Result<LlmAccount>
    suspend fun deleteLlmAccount(accountId: String): Result<Unit>
    suspend fun getCustomModels(accountId: String): Result<List<CustomModel>>
    suspend fun createCustomModel(accountId: String, modelId: String, displayName: String, contextWindowTokens: Long, thinkingCapability: String?, thinkingFormat: String?): Result<CustomModel>
    suspend fun updateCustomModel(accountId: String, modelRecordId: String, modelId: String?, displayName: String?, contextWindowTokens: Long?, thinkingCapability: String?, thinkingFormat: String?): Result<CustomModel>
    suspend fun deleteCustomModel(accountId: String, modelRecordId: String): Result<Unit>
    suspend fun getDefaultBinding(): Result<AgentBinding?>
    suspend fun setDefaultBinding(accountId: String, modelId: String, thinkingEffort: String?): Result<AgentBinding>
}

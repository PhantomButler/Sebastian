package com.sebastian.android.data.local

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "sebastian_settings")

@Singleton
class SettingsDataStore @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    companion object {
        val SERVER_URL = stringPreferencesKey("server_url")
        val ACTIVE_PROVIDER_ID = stringPreferencesKey("active_provider_id")
        val THEME = stringPreferencesKey("theme")
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    val serverUrl: StateFlow<String> = context.dataStore.data
        .map { prefs -> prefs[SERVER_URL] ?: "" }
        .stateIn(scope, SharingStarted.Eagerly, "")

    val activeProviderId: Flow<String?> = context.dataStore.data.map { prefs ->
        prefs[ACTIVE_PROVIDER_ID]
    }

    val theme: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[THEME] ?: "system"
    }

    suspend fun saveServerUrl(url: String) {
        context.dataStore.edit { it[SERVER_URL] = url }
    }

    suspend fun saveActiveProviderId(id: String) {
        context.dataStore.edit { it[ACTIVE_PROVIDER_ID] = id }
    }

    suspend fun saveTheme(theme: String) {
        context.dataStore.edit { it[THEME] = theme }
    }
}

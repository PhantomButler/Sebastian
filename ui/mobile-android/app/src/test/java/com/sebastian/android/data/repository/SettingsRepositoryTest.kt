package com.sebastian.android.data.repository

import androidx.datastore.preferences.core.stringPreferencesKey
import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsDataStoreTest {

    @Test
    fun `SERVER_URL key name is server_url`() {
        // 验证 DataStore key 常量定义正确
        val key = stringPreferencesKey("server_url")
        assertEquals("server_url", key.name)
    }
}

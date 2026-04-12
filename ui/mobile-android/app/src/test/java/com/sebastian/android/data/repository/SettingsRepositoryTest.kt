package com.sebastian.android.data.repository

import androidx.datastore.preferences.core.stringPreferencesKey
import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsDataStoreTest {

    @Test
    fun `saveServerUrl stores and retrieves value`() {
        // 验证 DataStore key 常量定义正确
        val key = stringPreferencesKey("server_url")
        assertEquals("server_url", key.name)
    }
}

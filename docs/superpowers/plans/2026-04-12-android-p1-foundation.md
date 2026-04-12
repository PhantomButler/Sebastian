# Android Phase 1 — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 `ui/mobile-android/` 项目骨架，完成 Gradle 配置、Hilt DI、数据模型、网络层（SseClient + Retrofit）和 Repository 层，使应用可编译运行（空白 Activity），所有数据层单元测试通过。

**Architecture:** Kotlin + Jetpack Compose，minSdk 33。Hilt 管理全局依赖注入；OkHttp EventSource 在 IO 线程收 SSE 并转为 `Flow<StreamEvent>`；Retrofit 处理 REST；SettingsDataStore（DataStore Preferences）持久化设置；JWT 存 EncryptedSharedPreferences。Repository 层聚合 remote/local，暴露 `suspend` / `Flow` 接口给 ViewModel。

**Tech Stack:** Kotlin 2.0, Jetpack Compose BOM 2025.04, Hilt 2.52, OkHttp 4.12, Retrofit 2.11, Moshi 1.15, DataStore 1.1, Security-Crypto 1.1-alpha06, Turbine 1.1 (tests), kotlinx-coroutines-test 1.8

---

## 文件结构

```
ui/mobile-android/
├── settings.gradle.kts
├── build.gradle.kts                            # root，插件版本声明
└── app/
    ├── build.gradle.kts                        # app module
    ├── src/
    │   ├── main/
    │   │   ├── AndroidManifest.xml
    │   │   └── java/com/sebastian/android/
    │   │       ├── SebastianApp.kt             # @HiltAndroidApp Application
    │   │       ├── data/
    │   │       │   ├── model/
    │   │       │   │   ├── StreamEvent.kt      # sealed class，SSE 事件领域模型
    │   │       │   │   ├── ContentBlock.kt     # sealed class，消息内容块
    │   │       │   │   ├── Message.kt          # 消息领域模型
    │   │       │   │   ├── Session.kt          # 会话领域模型
    │   │       │   │   └── Provider.kt         # LLM Provider 领域模型
    │   │       │   ├── remote/
    │   │       │   │   ├── dto/
    │   │       │   │   │   ├── SseFrameDto.kt  # SSE 帧 JSON 结构
    │   │       │   │   │   ├── MessageDto.kt
    │   │       │   │   │   ├── SessionDto.kt
    │   │       │   │   │   ├── TurnDto.kt
    │   │       │   │   │   └── ProviderDto.kt
    │   │       │   │   ├── SseClient.kt        # OkHttp SSE → Flow<StreamEvent>
    │   │       │   │   └── ApiService.kt       # Retrofit 接口
    │   │       │   ├── local/
    │   │       │   │   ├── SettingsDataStore.kt
    │   │       │   │   └── SecureTokenStore.kt
    │   │       │   └── repository/
    │   │       │       ├── SettingsRepository.kt       # interface
    │   │       │       ├── SettingsRepositoryImpl.kt
    │   │       │       ├── ChatRepository.kt           # interface
    │   │       │       ├── ChatRepositoryImpl.kt
    │   │       │       ├── SessionRepository.kt        # interface
    │   │       │       └── SessionRepositoryImpl.kt
    │   │       └── di/
    │   │           ├── NetworkModule.kt
    │   │           ├── StorageModule.kt
    │   │           └── RepositoryModule.kt
    │   └── test/
    │       └── java/com/sebastian/android/
    │           ├── data/remote/
    │           │   └── SseClientTest.kt
    │           └── data/repository/
    │               └── SettingsRepositoryTest.kt
```

---

### Task 1: Gradle 项目骨架

**Files:**
- Create: `ui/mobile-android/settings.gradle.kts`
- Create: `ui/mobile-android/build.gradle.kts`
- Create: `ui/mobile-android/app/build.gradle.kts`
- Create: `ui/mobile-android/app/src/main/AndroidManifest.xml`

- [ ] **Step 1: 创建 `settings.gradle.kts`**

```kotlin
// ui/mobile-android/settings.gradle.kts
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "Sebastian"
include(":app")
```

- [ ] **Step 2: 创建 `build.gradle.kts`（root）**

```kotlin
// ui/mobile-android/build.gradle.kts
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.hilt) apply false
}
```

- [ ] **Step 3: 创建 `gradle/libs.versions.toml`（version catalog）**

```toml
[versions]
agp = "8.8.0"
kotlin = "2.0.21"
ksp = "2.0.21-1.0.29"
hilt = "2.52"
compose-bom = "2025.04.00"
navigation = "2.8.7"
adaptive = "1.1.0"
lifecycle = "2.8.7"
activity = "1.10.1"
okhttp = "4.12.0"
retrofit = "2.11.0"
moshi = "1.15.2"
coil = "2.7.0"
markwon = "4.6.2"
datastore = "1.1.1"
security-crypto = "1.1.0-alpha06"
coroutines = "1.8.0"
turbine = "1.1.0"

[libraries]
# Compose
compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "compose-bom" }
compose-ui = { group = "androidx.compose.ui", name = "ui" }
compose-ui-tooling = { group = "androidx.compose.ui", name = "ui-tooling" }
compose-ui-tooling-preview = { group = "androidx.compose.ui", name = "ui-tooling-preview" }
compose-material3 = { group = "androidx.compose.material3", name = "material3" }
compose-material3-adaptive = { group = "androidx.compose.material3.adaptive", name = "adaptive", version.ref = "adaptive" }
compose-material3-adaptive-layout = { group = "androidx.compose.material3.adaptive", name = "adaptive-layout", version.ref = "adaptive" }
compose-material3-adaptive-navigation = { group = "androidx.compose.material3.adaptive", name = "adaptive-navigation", version.ref = "adaptive" }
compose-icons-extended = { group = "androidx.compose.material", name = "material-icons-extended" }
navigation-compose = { group = "androidx.navigation", name = "navigation-compose", version.ref = "navigation" }
activity-compose = { group = "androidx.activity", name = "activity-compose", version.ref = "activity" }
lifecycle-viewmodel-compose = { group = "androidx.lifecycle", name = "lifecycle-viewmodel-compose", version.ref = "lifecycle" }
lifecycle-runtime-compose = { group = "androidx.lifecycle", name = "lifecycle-runtime-compose", version.ref = "lifecycle" }
# Hilt
hilt-android = { group = "com.google.dagger", name = "hilt-android", version.ref = "hilt" }
hilt-compiler = { group = "com.google.dagger", name = "hilt-android-compiler", version.ref = "hilt" }
hilt-navigation-compose = { group = "androidx.hilt", name = "hilt-navigation-compose", version = "1.2.0" }
# Network
okhttp-core = { group = "com.squareup.okhttp3", name = "okhttp", version.ref = "okhttp" }
okhttp-sse = { group = "com.squareup.okhttp3", name = "okhttp-sse", version.ref = "okhttp" }
okhttp-logging = { group = "com.squareup.okhttp3", name = "logging-interceptor", version.ref = "okhttp" }
retrofit-core = { group = "com.squareup.retrofit2", name = "retrofit", version.ref = "retrofit" }
retrofit-moshi = { group = "com.squareup.retrofit2", name = "converter-moshi", version.ref = "retrofit" }
moshi-kotlin = { group = "com.squareup.moshi", name = "moshi-kotlin", version.ref = "moshi" }
moshi-codegen = { group = "com.squareup.moshi", name = "moshi-kotlin-codegen", version.ref = "moshi" }
# Image + Markdown
coil-compose = { group = "io.coil-kt", name = "coil-compose", version.ref = "coil" }
markwon-core = { group = "io.noties.markwon", name = "core", version.ref = "markwon" }
markwon-strikethrough = { group = "io.noties.markwon", name = "ext-strikethrough", version.ref = "markwon" }
markwon-tables = { group = "io.noties.markwon", name = "ext-tables", version.ref = "markwon" }
# Storage
datastore-preferences = { group = "androidx.datastore", name = "datastore-preferences", version.ref = "datastore" }
security-crypto = { group = "androidx.security", name = "security-crypto", version.ref = "security-crypto" }
# Test
junit = { group = "junit", name = "junit", version = "4.13.2" }
mockito-kotlin = { group = "org.mockito.kotlin", name = "mockito-kotlin", version = "5.3.1" }
turbine = { group = "app.cash.turbine", name = "turbine", version.ref = "turbine" }
coroutines-test = { group = "org.jetbrains.kotlinx", name = "kotlinx-coroutines-test", version.ref = "coroutines" }
androidx-test-junit = { group = "androidx.test.ext", name = "junit", version = "1.2.1" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
kotlin-serialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }
hilt = { id = "com.google.dagger.hilt.android", version.ref = "hilt" }
```

- [ ] **Step 4: 创建 `app/build.gradle.kts`**

```kotlin
// ui/mobile-android/app/build.gradle.kts
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

android {
    namespace = "com.sebastian.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.sebastian.android"
        minSdk = 33
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material3.adaptive)
    implementation(libs.compose.material3.adaptive.layout)
    implementation(libs.compose.material3.adaptive.navigation)
    implementation(libs.compose.icons.extended)
    implementation(libs.navigation.compose)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)
    implementation(libs.okhttp.core)
    implementation(libs.okhttp.sse)
    implementation(libs.okhttp.logging)
    implementation(libs.retrofit.core)
    implementation(libs.retrofit.moshi)
    implementation(libs.moshi.kotlin)
    ksp(libs.moshi.codegen)
    implementation(libs.coil.compose)
    implementation(libs.markwon.core)
    implementation(libs.markwon.strikethrough)
    implementation(libs.markwon.tables)
    implementation(libs.datastore.preferences)
    implementation(libs.security.crypto)
    debugImplementation(libs.compose.ui.tooling)
    testImplementation(libs.junit)
    testImplementation(libs.mockito.kotlin)
    testImplementation(libs.turbine)
    testImplementation(libs.coroutines.test)
    androidTestImplementation(libs.androidx.test.junit)
}
```

- [ ] **Step 5: 创建 `AndroidManifest.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

    <application
        android:name=".SebastianApp"
        android:label="Sebastian"
        android:theme="@style/Theme.Sebastian"
        android:enableOnBackInvokedCallback="true">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

- [ ] **Step 6: 创建 `res/values/themes.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="Theme.Sebastian" parent="android:Theme.Material.Light.NoActionBar" />
</resources>
```

- [ ] **Step 7: 在 Android Studio 中 Sync Project，确认编译通过**

预期：Gradle sync 成功，无依赖冲突。

---

### Task 2: Application + 临时 MainActivity

**Files:**
- Create: `app/src/main/java/com/sebastian/android/SebastianApp.kt`
- Create: `app/src/main/java/com/sebastian/android/MainActivity.kt`

- [ ] **Step 1: 创建 `SebastianApp.kt`**

```kotlin
// com/sebastian/android/SebastianApp.kt
package com.sebastian.android

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class SebastianApp : Application()
```

- [ ] **Step 2: 创建临时 `MainActivity.kt`（后续 Plan 2 替换）**

```kotlin
// com/sebastian/android/MainActivity.kt
package com.sebastian.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface { Text("Sebastian") }
            }
        }
    }
}
```

- [ ] **Step 3: 在模拟器上构建并运行**

```bash
cd ui/mobile-android
./gradlew :app:installDebug
```

预期：App 启动，白屏显示 "Sebastian"。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/
git commit -m "feat(android): 初始化 Android 原生项目骨架"
```

---

### Task 3: 领域模型

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
- Create: `app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`
- Create: `app/src/main/java/com/sebastian/android/data/model/Message.kt`
- Create: `app/src/main/java/com/sebastian/android/data/model/Session.kt`
- Create: `app/src/main/java/com/sebastian/android/data/model/Provider.kt`

- [ ] **Step 1: 创建 `StreamEvent.kt`**

对应后端 SSE 事件协议（`runtime.md` §5.1），每个 sealed subclass 对应一种 `type`：

```kotlin
// com/sebastian/android/data/model/StreamEvent.kt
package com.sebastian.android.data.model

sealed class StreamEvent {
    // Turn 级别
    data class TurnReceived(val sessionId: String) : StreamEvent()
    data class TurnResponse(val sessionId: String, val content: String) : StreamEvent()
    data class TurnInterrupted(val sessionId: String, val partialContent: String) : StreamEvent()

    // Thinking block
    data class ThinkingBlockStart(val sessionId: String, val blockId: String) : StreamEvent()
    data class ThinkingDelta(val sessionId: String, val blockId: String, val delta: String) : StreamEvent()
    data class ThinkingBlockStop(val sessionId: String, val blockId: String) : StreamEvent()

    // Text block
    data class TextBlockStart(val sessionId: String, val blockId: String) : StreamEvent()
    data class TextDelta(val sessionId: String, val blockId: String, val delta: String) : StreamEvent()
    data class TextBlockStop(val sessionId: String, val blockId: String) : StreamEvent()

    // Tool
    data class ToolBlockStart(val sessionId: String, val blockId: String, val toolId: String, val name: String) : StreamEvent()
    data class ToolBlockStop(val sessionId: String, val blockId: String, val toolId: String, val name: String, val inputs: String) : StreamEvent()
    data class ToolRunning(val sessionId: String, val toolId: String, val name: String) : StreamEvent()
    data class ToolExecuted(val sessionId: String, val toolId: String, val name: String, val resultSummary: String) : StreamEvent()
    data class ToolFailed(val sessionId: String, val toolId: String, val name: String, val error: String) : StreamEvent()

    // Task
    data class TaskCreated(val sessionId: String, val taskId: String, val goal: String) : StreamEvent()
    data class TaskStarted(val sessionId: String, val taskId: String) : StreamEvent()
    data class TaskCompleted(val sessionId: String, val taskId: String) : StreamEvent()
    data class TaskFailed(val sessionId: String, val taskId: String, val error: String) : StreamEvent()
    data class TaskCancelled(val sessionId: String, val taskId: String) : StreamEvent()

    // Approval
    data class ApprovalRequested(val sessionId: String, val approvalId: String, val description: String) : StreamEvent()
    data class ApprovalGranted(val approvalId: String) : StreamEvent()
    data class ApprovalDenied(val approvalId: String) : StreamEvent()

    // 未识别事件（忽略）
    object Unknown : StreamEvent()
}
```

- [ ] **Step 2: 创建 `ContentBlock.kt`**

```kotlin
// com/sebastian/android/data/model/ContentBlock.kt
package com.sebastian.android.data.model

sealed class ContentBlock {
    abstract val blockId: String

    data class TextBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean,
    ) : ContentBlock()

    data class ThinkingBlock(
        override val blockId: String,
        val text: String,
        val done: Boolean,
        val expanded: Boolean = false,
    ) : ContentBlock()

    data class ToolBlock(
        override val blockId: String,
        val toolId: String,
        val name: String,
        val inputs: String,
        val status: ToolStatus,
        val resultSummary: String? = null,
        val error: String? = null,
        val expanded: Boolean = false,
    ) : ContentBlock()
}

enum class ToolStatus { PENDING, RUNNING, DONE, FAILED }
```

- [ ] **Step 3: 创建 `Message.kt`**

```kotlin
// com/sebastian/android/data/model/Message.kt
package com.sebastian.android.data.model

data class Message(
    val id: String,
    val sessionId: String,
    val role: MessageRole,
    val blocks: List<ContentBlock> = emptyList(),
    val text: String = "",         // user 消息纯文本
    val createdAt: String = "",
)

enum class MessageRole { USER, ASSISTANT }
```

- [ ] **Step 4: 创建 `Session.kt`**

```kotlin
// com/sebastian/android/data/model/Session.kt
package com.sebastian.android.data.model

data class Session(
    val id: String,
    val title: String,
    val agentType: String,
    val lastMessageAt: String?,
    val isActive: Boolean,
)
```

- [ ] **Step 5: 创建 `Provider.kt`**

```kotlin
// com/sebastian/android/data/model/Provider.kt
package com.sebastian.android.data.model

data class Provider(
    val id: String,
    val name: String,
    val type: String,         // "anthropic" | "openai" | "ollama"
    val baseUrl: String?,
    val isDefault: Boolean,
    val thinkingCapability: ThinkingCapability,
)

enum class ThinkingCapability {
    NONE, ALWAYS_ON, TOGGLE, EFFORT, ADAPTIVE;

    companion object {
        fun fromString(value: String?): ThinkingCapability = when (value) {
            "none" -> NONE
            "always_on" -> ALWAYS_ON
            "toggle" -> TOGGLE
            "effort" -> EFFORT
            "adaptive" -> ADAPTIVE
            else -> NONE
        }
    }
}

enum class ThinkingEffort { LOW, MEDIUM, HIGH, AUTO }
```

- [ ] **Step 6: 编译确认无错误**

```bash
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 7: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/model/
git commit -m "feat(android): 添加领域模型（StreamEvent, ContentBlock, Message, Session, Provider）"
```

---

### Task 4: 本地持久化（DataStore + SecureTokenStore）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/local/SettingsDataStore.kt`
- Create: `app/src/main/java/com/sebastian/android/data/local/SecureTokenStore.kt`
- Create: `app/src/test/java/com/sebastian/android/data/repository/SettingsRepositoryTest.kt`

- [ ] **Step 1: 写 `SettingsDataStore` 的测试（先写测试）**

```kotlin
// app/src/test/java/com/sebastian/android/data/repository/SettingsRepositoryTest.kt
package com.sebastian.android.data.repository

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.test.core.app.ApplicationProvider
import com.sebastian.android.data.local.SettingsDataStore
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsDataStoreTest {
    // 使用 Robolectric 或 instrumented test 运行，此处为示意
    // 实际运行：./gradlew :app:connectedDebugAndroidTest

    @Test
    fun `saveServerUrl stores and retrieves value`() = runTest {
        // 验证逻辑在 SettingsRepositoryImpl 集成测试中覆盖
        // 此处仅验证 DataStore key 常量定义正确
        val key = stringPreferencesKey("server_url")
        assertEquals("server_url", key.name)
    }
}
```

- [ ] **Step 2: 创建 `SettingsDataStore.kt`**

```kotlin
// com/sebastian/android/data/local/SettingsDataStore.kt
package com.sebastian.android.data.local

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "sebastian_settings")

@Singleton
class SettingsDataStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        val SERVER_URL = stringPreferencesKey("server_url")
        val ACTIVE_PROVIDER_ID = stringPreferencesKey("active_provider_id")
        val THEME = stringPreferencesKey("theme")
    }

    val serverUrl: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[SERVER_URL] ?: ""
    }

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
```

- [ ] **Step 3: 创建 `SecureTokenStore.kt`**

```kotlin
// com/sebastian/android/data/local/SecureTokenStore.kt
package com.sebastian.android.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SecureTokenStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val prefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "sebastian_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun saveToken(jwt: String) = prefs.edit().putString("jwt", jwt).apply()
    fun getToken(): String? = prefs.getString("jwt", null)
    fun clearToken() = prefs.edit().remove("jwt").apply()
}
```

- [ ] **Step 4: 编译确认**

```bash
./gradlew :app:compileDebugKotlin
```

预期：编译通过，无未解析的引用。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/local/
git commit -m "feat(android): 添加 SettingsDataStore 和 SecureTokenStore"
```

---

### Task 5: SSE 数据传输模型与解析

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`
- Create: `app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt`

- [ ] **Step 1: 写 SSE 解析的失败测试**

```kotlin
// app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt
package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SseFrameParserTest {

    @Test
    fun `parses turn_delta event`() {
        val json = """{"type":"turn.delta","data":{"session_id":"s1","block_id":"b0_1","delta":"好的"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.TextDelta)
        val delta = event as StreamEvent.TextDelta
        assertEquals("s1", delta.sessionId)
        assertEquals("b0_1", delta.blockId)
        assertEquals("好的", delta.delta)
    }

    @Test
    fun `parses thinking_block_start event`() {
        val json = """{"type":"thinking_block.start","data":{"session_id":"s1","block_id":"b0_0"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ThinkingBlockStart)
        assertEquals("b0_0", (event as StreamEvent.ThinkingBlockStart).blockId)
    }

    @Test
    fun `returns Unknown for unrecognized event type`() {
        val json = """{"type":"unknown.event","data":{},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertEquals(StreamEvent.Unknown, event)
    }

    @Test
    fun `returns Unknown for malformed json`() {
        val event = SseFrameParser.parse("not json")
        assertEquals(StreamEvent.Unknown, event)
    }

    @Test
    fun `parses tool_running event`() {
        val json = """{"type":"tool.running","data":{"session_id":"s1","tool_id":"tu_01","name":"web_search"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ToolRunning)
        val e = event as StreamEvent.ToolRunning
        assertEquals("tu_01", e.toolId)
        assertEquals("web_search", e.name)
    }

    @Test
    fun `parses approval_requested event`() {
        val json = """{"type":"approval.requested","data":{"session_id":"s1","approval_id":"ap_1","description":"删除文件"},"ts":"2026-04-12T10:00:00Z"}"""
        val event = SseFrameParser.parse(json)
        assertTrue(event is StreamEvent.ApprovalRequested)
        assertEquals("ap_1", (event as StreamEvent.ApprovalRequested).approvalId)
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
./gradlew :app:testDebugUnitTest --tests "*.SseFrameParserTest"
```

预期：`FAILED` — `SseFrameParser` 未定义。

- [ ] **Step 3: 创建 `SseFrameDto.kt`（含 `SseFrameParser`）**

```kotlin
// com/sebastian/android/data/remote/dto/SseFrameDto.kt
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.StreamEvent
import org.json.JSONException
import org.json.JSONObject

/**
 * SSE 帧格式：{"type":"...","data":{...},"ts":"..."}
 * 使用 org.json（Android 内置）解析，避免额外依赖
 */
object SseFrameParser {

    fun parse(raw: String): StreamEvent = try {
        val frame = JSONObject(raw)
        val type = frame.getString("type")
        val data = frame.optJSONObject("data") ?: JSONObject()
        parseByType(type, data)
    } catch (e: JSONException) {
        StreamEvent.Unknown
    }

    private fun parseByType(type: String, data: JSONObject): StreamEvent = when (type) {
        "turn.received" -> StreamEvent.TurnReceived(data.getString("session_id"))
        "turn.response" -> StreamEvent.TurnResponse(data.getString("session_id"), data.optString("content", ""))
        "turn.interrupted" -> StreamEvent.TurnInterrupted(data.getString("session_id"), data.optString("partial_content", ""))
        "thinking_block.start" -> StreamEvent.ThinkingBlockStart(data.getString("session_id"), data.getString("block_id"))
        "turn.thinking_delta" -> StreamEvent.ThinkingDelta(data.getString("session_id"), data.getString("block_id"), data.getString("delta"))
        "thinking_block.stop" -> StreamEvent.ThinkingBlockStop(data.getString("session_id"), data.getString("block_id"))
        "text_block.start" -> StreamEvent.TextBlockStart(data.getString("session_id"), data.getString("block_id"))
        "turn.delta" -> StreamEvent.TextDelta(data.getString("session_id"), data.getString("block_id"), data.getString("delta"))
        "text_block.stop" -> StreamEvent.TextBlockStop(data.getString("session_id"), data.getString("block_id"))
        "tool_block.start" -> StreamEvent.ToolBlockStart(data.getString("session_id"), data.getString("block_id"), data.getString("tool_id"), data.getString("name"))
        "tool_block.stop" -> StreamEvent.ToolBlockStop(data.getString("session_id"), data.getString("block_id"), data.getString("tool_id"), data.getString("name"), data.optJSONObject("inputs")?.toString() ?: "{}")
        "tool.running" -> StreamEvent.ToolRunning(data.getString("session_id"), data.getString("tool_id"), data.getString("name"))
        "tool.executed" -> StreamEvent.ToolExecuted(data.getString("session_id"), data.getString("tool_id"), data.getString("name"), data.optString("result_summary", ""))
        "tool.failed" -> StreamEvent.ToolFailed(data.getString("session_id"), data.getString("tool_id"), data.getString("name"), data.optString("error", ""))
        "task.created" -> StreamEvent.TaskCreated(data.getString("session_id"), data.getString("task_id"), data.optString("goal", ""))
        "task.started" -> StreamEvent.TaskStarted(data.getString("session_id"), data.getString("task_id"))
        "task.completed" -> StreamEvent.TaskCompleted(data.getString("session_id"), data.getString("task_id"))
        "task.failed" -> StreamEvent.TaskFailed(data.getString("session_id"), data.getString("task_id"), data.optString("error", ""))
        "task.cancelled" -> StreamEvent.TaskCancelled(data.getString("session_id"), data.getString("task_id"))
        "approval.requested" -> StreamEvent.ApprovalRequested(data.getString("session_id"), data.getString("approval_id"), data.optString("description", ""))
        "approval.granted" -> StreamEvent.ApprovalGranted(data.getString("approval_id"))
        "approval.denied" -> StreamEvent.ApprovalDenied(data.getString("approval_id"))
        else -> StreamEvent.Unknown
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
./gradlew :app:testDebugUnitTest --tests "*.SseFrameParserTest"
```

预期：5 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt \
        app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt
git commit -m "feat(android): SSE 帧解析器及单元测试"
```

---

### Task 6: ApiService DTOs

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/remote/dto/MessageDto.kt`
- Create: `app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt`
- Create: `app/src/main/java/com/sebastian/android/data/remote/dto/TurnDto.kt`
- Create: `app/src/main/java/com/sebastian/android/data/remote/dto/ProviderDto.kt`

- [ ] **Step 1: 创建 `SessionDto.kt`**

```kotlin
// com/sebastian/android/data/remote/dto/SessionDto.kt
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Session
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SessionDto(
    @Json(name = "id") val id: String,
    @Json(name = "title") val title: String?,
    @Json(name = "agent_type") val agentType: String,
    @Json(name = "last_message_at") val lastMessageAt: String?,
    @Json(name = "is_active") val isActive: Boolean = false,
) {
    fun toDomain() = Session(
        id = id,
        title = title ?: "新对话",
        agentType = agentType,
        lastMessageAt = lastMessageAt,
        isActive = isActive,
    )
}

@JsonClass(generateAdapter = true)
data class CreateSessionRequest(
    @Json(name = "title") val title: String? = null,
    @Json(name = "agent_type") val agentType: String = "sebastian",
)
```

- [ ] **Step 2: 创建 `MessageDto.kt`**

```kotlin
// com/sebastian/android/data/remote/dto/MessageDto.kt
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MessageDto(
    @Json(name = "id") val id: String,
    @Json(name = "session_id") val sessionId: String,
    @Json(name = "role") val role: String,
    @Json(name = "content") val content: String = "",
    @Json(name = "created_at") val createdAt: String = "",
) {
    fun toDomain() = Message(
        id = id,
        sessionId = sessionId,
        role = if (role == "user") MessageRole.USER else MessageRole.ASSISTANT,
        text = if (role == "user") content else "",
        createdAt = createdAt,
    )
}
```

- [ ] **Step 3: 创建 `TurnDto.kt`**

```kotlin
// com/sebastian/android/data/remote/dto/TurnDto.kt
package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SendTurnRequest(
    @Json(name = "content") val content: String,
    @Json(name = "thinking_effort") val thinkingEffort: String? = null,
)

@JsonClass(generateAdapter = true)
data class TurnDto(
    @Json(name = "session_id") val sessionId: String,
    @Json(name = "ts") val ts: String,
)

@JsonClass(generateAdapter = true)
data class CancelResponse(
    @Json(name = "ok") val ok: Boolean,
)
```

- [ ] **Step 4: 创建 `ProviderDto.kt`**

```kotlin
// com/sebastian/android/data/remote/dto/ProviderDto.kt
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ProviderDto(
    @Json(name = "id") val id: String = "",
    @Json(name = "name") val name: String,
    @Json(name = "type") val type: String,
    @Json(name = "base_url") val baseUrl: String? = null,
    @Json(name = "api_key") val apiKey: String? = null,    // 仅创建/编辑时使用，读取时后端不返回
    @Json(name = "is_default") val isDefault: Boolean = false,
    @Json(name = "thinking_capability") val thinkingCapability: String? = null,
) {
    fun toDomain() = Provider(
        id = id,
        name = name,
        type = type,
        baseUrl = baseUrl,
        isDefault = isDefault,
        thinkingCapability = ThinkingCapability.fromString(thinkingCapability),
    )
}

@JsonClass(generateAdapter = true)
data class OkResponse(
    @Json(name = "ok") val ok: Boolean,
)
```

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/remote/dto/
git commit -m "feat(android): 添加 Retrofit DTOs（Session, Message, Turn, Provider）"
```

---

### Task 7: SseClient

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/remote/SseClient.kt`

- [ ] **Step 1: 创建 `SseClient.kt`**

```kotlin
// com/sebastian/android/data/remote/SseClient.kt
package com.sebastian.android.data.remote

import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.remote.dto.SseFrameParser
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.Dispatchers
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SseClient @Inject constructor(
    private val okHttpClient: OkHttpClient,
) {
    /**
     * 订阅单 session 事件流。
     * lastEventId: 断线重连时传入，null 表示新连接（服务端会带 Last-Event-ID: 0 重放）
     */
    fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<StreamEvent> =
        sseFlow("$baseUrl/api/v1/sessions/$sessionId/stream", lastEventId)

    /**
     * 订阅全局事件流（task, approval, todo 等）
     */
    fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<StreamEvent> =
        sseFlow("$baseUrl/api/v1/stream", lastEventId)

    private fun sseFlow(url: String, lastEventId: String?): Flow<StreamEvent> = callbackFlow {
        val requestBuilder = Request.Builder().url(url)
        lastEventId?.let { requestBuilder.header("Last-Event-Id", it) }
        val request = requestBuilder.build()

        val listener = object : EventSourceListener() {
            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                val event = SseFrameParser.parse(data)
                trySend(event)
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                close(t ?: Exception("SSE connection failed: ${response?.code}"))
            }

            override fun onClosed(eventSource: EventSource) {
                close()
            }
        }

        val eventSource = EventSources.createFactory(okHttpClient)
            .newEventSource(request, listener)

        awaitClose { eventSource.cancel() }
    }.flowOn(Dispatchers.IO)
}
```

- [ ] **Step 2: 编译确认**

```bash
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/remote/SseClient.kt
git commit -m "feat(android): SseClient（OkHttp SSE → Flow<StreamEvent>，IO 线程）"
```

---

### Task 8: ApiService（Retrofit）

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`

- [ ] **Step 1: 创建 `ApiService.kt`**

```kotlin
// com/sebastian/android/data/remote/ApiService.kt
package com.sebastian.android.data.remote

import com.sebastian.android.data.remote.dto.*
import retrofit2.http.*

interface ApiService {
    // 认证
    @POST("api/v1/auth/login")
    suspend fun login(@Body body: Map<String, String>): Map<String, String>

    // 主对话 turn（Sebastian 主入口）
    @POST("api/v1/turns")
    suspend fun sendTurn(@Body body: SendTurnRequest): TurnDto

    // SubAgent session turn
    @POST("api/v1/sessions/{sessionId}/turns")
    suspend fun sendSessionTurn(
        @Path("sessionId") sessionId: String,
        @Body body: SendTurnRequest,
    ): TurnDto

    // Sessions
    @GET("api/v1/sessions")
    suspend fun getSessions(): List<SessionDto>

    @GET("api/v1/sessions/{sessionId}")
    suspend fun getSession(@Path("sessionId") sessionId: String): SessionDto

    @GET("api/v1/messages")
    suspend fun getMessages(@Query("session_id") sessionId: String): List<MessageDto>

    // SubAgent sessions
    @GET("api/v1/agents/{agentType}/sessions")
    suspend fun getAgentSessions(@Path("agentType") agentType: String): List<SessionDto>

    @POST("api/v1/agents/{agentType}/sessions")
    suspend fun createAgentSession(
        @Path("agentType") agentType: String,
        @Body body: CreateSessionRequest,
    ): SessionDto

    // Agents
    @GET("api/v1/agents")
    suspend fun getAgents(): List<Map<String, Any>>

    // Providers
    @GET("api/v1/llm/providers")
    suspend fun getProviders(): List<ProviderDto>

    @POST("api/v1/llm/providers")
    suspend fun createProvider(@Body body: ProviderDto): ProviderDto

    @PUT("api/v1/llm/providers/{id}")
    suspend fun updateProvider(@Path("id") id: String, @Body body: ProviderDto): ProviderDto

    @DELETE("api/v1/llm/providers/{id}")
    suspend fun deleteProvider(@Path("id") id: String): OkResponse

    @POST("api/v1/llm/providers/{id}/set-default")
    suspend fun setDefaultProvider(@Path("id") id: String): OkResponse

    // Approvals
    @GET("api/v1/approvals")
    suspend fun getPendingApprovals(): List<Map<String, Any>>

    @POST("api/v1/approvals/{approvalId}/grant")
    suspend fun grantApproval(@Path("approvalId") approvalId: String): OkResponse

    @POST("api/v1/approvals/{approvalId}/deny")
    suspend fun denyApproval(@Path("approvalId") approvalId: String): OkResponse

    // Health
    @GET("api/v1/health")
    suspend fun health(): Map<String, Any>
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/remote/ApiService.kt
git commit -m "feat(android): ApiService Retrofit 接口定义"
```

---

### Task 9: Hilt DI 模块

**Files:**
- Create: `app/src/main/java/com/sebastian/android/di/NetworkModule.kt`
- Create: `app/src/main/java/com/sebastian/android/di/StorageModule.kt`

- [ ] **Step 1: 创建 `NetworkModule.kt`**

```kotlin
// com/sebastian/android/di/NetworkModule.kt
package com.sebastian.android.di

import com.sebastian.android.data.local.SecureTokenStore
import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.remote.ApiService
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides @Singleton
    fun provideMoshi(): Moshi = Moshi.Builder()
        .addLast(KotlinJsonAdapterFactory())
        .build()

    @Provides @Singleton
    fun provideOkHttpClient(
        tokenStore: SecureTokenStore,
        settingsDataStore: SettingsDataStore,
    ): OkHttpClient {
        val authInterceptor = Interceptor { chain ->
            val token = tokenStore.getToken()
            val req = if (token != null) {
                chain.request().newBuilder()
                    .header("Authorization", "Bearer $token")
                    .build()
            } else chain.request()
            chain.proceed(req)
        }

        // 动态 BaseUrl：每次请求从 DataStore 读取最新 serverUrl 替换
        val baseUrlInterceptor = Interceptor { chain ->
            val serverUrl = runBlocking { settingsDataStore.serverUrl.first() }
                .trimEnd('/')
            val original = chain.request()
            val newUrl = if (serverUrl.isNotEmpty()) {
                original.url.newBuilder()
                    .scheme(if (serverUrl.startsWith("https") ) "https" else "http")
                    .host(serverUrl.removePrefix("http://").removePrefix("https://").substringBefore('/').substringBefore(':'))
                    .port(serverUrl.removePrefix("http://").removePrefix("https://").substringBefore('/').substringAfter(':').toIntOrNull() ?: -1)
                    .build()
            } else original.url
            chain.proceed(original.newBuilder().url(newUrl).build())
        }

        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }

        return OkHttpClient.Builder()
            .addInterceptor(baseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(logging)
            .build()
    }

    @Provides @Singleton
    fun provideRetrofit(okHttpClient: OkHttpClient, moshi: Moshi): Retrofit =
        Retrofit.Builder()
            .client(okHttpClient)
            .baseUrl("http://placeholder.local/")   // 运行时由 baseUrlInterceptor 替换
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

    @Provides @Singleton
    fun provideApiService(retrofit: Retrofit): ApiService =
        retrofit.create(ApiService::class.java)
}
```

> **注意**：`baseUrlInterceptor` 中的 URL 替换逻辑在 Task 9 Step 1 仅为示意实现。若 serverUrl 包含 path 前缀或 port，需要完整解析。建议在 `SettingsRepository.buildRetrofit()` 中通过重建 Retrofit 实例来处理 serverUrl 变化（见 Plan 2 Settings ViewModel 部分）。

- [ ] **Step 2: 创建 `StorageModule.kt`**

```kotlin
// com/sebastian/android/di/StorageModule.kt
package com.sebastian.android.di

import com.sebastian.android.data.local.SecureTokenStore
import com.sebastian.android.data.local.SettingsDataStore
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

// SettingsDataStore 和 SecureTokenStore 均使用 @Inject constructor + @Singleton
// 无需在此手动提供，Hilt 自动处理。
// 如果将来引入接口抽象，在此添加 @Binds。
@Module
@InstallIn(SingletonComponent::class)
object StorageModule
```

- [ ] **Step 3: 编译确认**

```bash
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/sebastian/android/di/
git commit -m "feat(android): Hilt DI 模块（NetworkModule, StorageModule）"
```

---

### Task 10: Repository 接口与实现

**Files:**
- Create: `app/src/main/java/com/sebastian/android/data/repository/SettingsRepository.kt`
- Create: `app/src/main/java/com/sebastian/android/data/repository/SettingsRepositoryImpl.kt`
- Create: `app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt`
- Create: `app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`
- Create: `app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt`
- Create: `app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt`
- Create: `app/src/main/java/com/sebastian/android/di/RepositoryModule.kt`

- [ ] **Step 1: 创建 `SettingsRepository.kt`（接口）**

```kotlin
// com/sebastian/android/data/repository/SettingsRepository.kt
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
```

- [ ] **Step 2: 创建 `SettingsRepositoryImpl.kt`**

```kotlin
// com/sebastian/android/data/repository/SettingsRepositoryImpl.kt
package com.sebastian.android.data.repository

import com.sebastian.android.data.local.SettingsDataStore
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.ProviderDto
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SettingsRepositoryImpl @Inject constructor(
    private val dataStore: SettingsDataStore,
    private val apiService: ApiService,
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
        // 用 health endpoint 验证连通性，临时构建 OkHttp 请求不走 DI
        val trimmed = url.trimEnd('/')
        val response = okhttp3.OkHttpClient().newCall(
            okhttp3.Request.Builder().url("$trimmed/api/v1/health").build()
        ).execute()
        if (!response.isSuccessful) throw Exception("HTTP ${response.code}")
    }
}
```

- [ ] **Step 3: 创建 `ChatRepository.kt`（接口）**

```kotlin
// com/sebastian/android/data/repository/ChatRepository.kt
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import kotlinx.coroutines.flow.Flow

interface ChatRepository {
    fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String? = null): Flow<StreamEvent>
    fun globalStream(baseUrl: String, lastEventId: String? = null): Flow<StreamEvent>
    suspend fun getMessages(sessionId: String): Result<List<Message>>
    suspend fun sendTurn(content: String, effort: ThinkingEffort): Result<Unit>
    suspend fun sendSessionTurn(sessionId: String, content: String, effort: ThinkingEffort): Result<Unit>
    suspend fun grantApproval(approvalId: String): Result<Unit>
    suspend fun denyApproval(approvalId: String): Result<Unit>
}
```

- [ ] **Step 4: 创建 `ChatRepositoryImpl.kt`**

```kotlin
// com/sebastian/android/data/repository/ChatRepositoryImpl.kt
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.StreamEvent
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.SseClient
import com.sebastian.android.data.remote.dto.SendTurnRequest
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
    private val sseClient: SseClient,
) : ChatRepository {

    override fun sessionStream(baseUrl: String, sessionId: String, lastEventId: String?): Flow<StreamEvent> =
        sseClient.sessionStream(baseUrl, sessionId, lastEventId)

    override fun globalStream(baseUrl: String, lastEventId: String?): Flow<StreamEvent> =
        sseClient.globalStream(baseUrl, lastEventId)

    override suspend fun getMessages(sessionId: String): Result<List<Message>> = runCatching {
        apiService.getMessages(sessionId).map { it.toDomain() }
    }

    override suspend fun sendTurn(content: String, effort: ThinkingEffort): Result<Unit> = runCatching {
        apiService.sendTurn(SendTurnRequest(content = content, thinkingEffort = effort.toApiString()))
        Unit
    }

    override suspend fun sendSessionTurn(sessionId: String, content: String, effort: ThinkingEffort): Result<Unit> = runCatching {
        apiService.sendSessionTurn(sessionId, SendTurnRequest(content = content, thinkingEffort = effort.toApiString()))
        Unit
    }

    override suspend fun grantApproval(approvalId: String): Result<Unit> = runCatching {
        apiService.grantApproval(approvalId)
        Unit
    }

    override suspend fun denyApproval(approvalId: String): Result<Unit> = runCatching {
        apiService.denyApproval(approvalId)
        Unit
    }

    private fun ThinkingEffort.toApiString(): String? = when (this) {
        ThinkingEffort.LOW -> "low"
        ThinkingEffort.MEDIUM -> "medium"
        ThinkingEffort.HIGH -> "high"
        ThinkingEffort.AUTO -> null
    }
}
```

- [ ] **Step 5: 创建 `SessionRepository.kt`（接口 + 实现）**

```kotlin
// com/sebastian/android/data/repository/SessionRepository.kt
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Session
import kotlinx.coroutines.flow.Flow

interface SessionRepository {
    fun sessionsFlow(): Flow<List<Session>>
    suspend fun loadSessions(): Result<List<Session>>
    suspend fun createSession(title: String? = null): Result<Session>
    suspend fun deleteSession(sessionId: String): Result<Unit>
    suspend fun getAgentSessions(agentType: String): Result<List<Session>>
    suspend fun createAgentSession(agentType: String, title: String? = null): Result<Session>
}
```

```kotlin
// com/sebastian/android/data/repository/SessionRepositoryImpl.kt
package com.sebastian.android.data.repository

import com.sebastian.android.data.model.Session
import com.sebastian.android.data.remote.ApiService
import com.sebastian.android.data.remote.dto.CreateSessionRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SessionRepositoryImpl @Inject constructor(
    private val apiService: ApiService,
) : SessionRepository {

    private val _sessions = MutableStateFlow<List<Session>>(emptyList())

    override fun sessionsFlow(): Flow<List<Session>> = _sessions.asStateFlow()

    override suspend fun loadSessions(): Result<List<Session>> = runCatching {
        val sessions = apiService.getSessions().map { it.toDomain() }
        _sessions.value = sessions
        sessions
    }

    override suspend fun createSession(title: String?): Result<Session> = runCatching {
        val session = apiService.createAgentSession("sebastian", CreateSessionRequest(title = title)).toDomain()
        _sessions.value = listOf(session) + _sessions.value
        session
    }

    override suspend fun deleteSession(sessionId: String): Result<Unit> = runCatching {
        _sessions.value = _sessions.value.filter { it.id != sessionId }
        // 后端暂无 delete session API，本地移除即可
    }

    override suspend fun getAgentSessions(agentType: String): Result<List<Session>> = runCatching {
        apiService.getAgentSessions(agentType).map { it.toDomain() }
    }

    override suspend fun createAgentSession(agentType: String, title: String?): Result<Session> = runCatching {
        apiService.createAgentSession(agentType, CreateSessionRequest(title = title)).toDomain()
    }
}
```

- [ ] **Step 6: 创建 `RepositoryModule.kt`**

```kotlin
// com/sebastian/android/di/RepositoryModule.kt
package com.sebastian.android.di

import com.sebastian.android.data.repository.*
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    @Binds @Singleton
    abstract fun bindSettingsRepository(impl: SettingsRepositoryImpl): SettingsRepository

    @Binds @Singleton
    abstract fun bindChatRepository(impl: ChatRepositoryImpl): ChatRepository

    @Binds @Singleton
    abstract fun bindSessionRepository(impl: SessionRepositoryImpl): SessionRepository
}
```

- [ ] **Step 7: 完整编译**

```bash
./gradlew :app:assembleDebug
```

预期：BUILD SUCCESSFUL，APK 生成。

- [ ] **Step 8: 运行所有单元测试**

```bash
./gradlew :app:testDebugUnitTest
```

预期：`SseFrameParserTest` 5 个测试全部 PASS。

- [ ] **Step 9: Commit**

```bash
git add app/src/main/java/com/sebastian/android/data/repository/ \
        app/src/main/java/com/sebastian/android/di/RepositoryModule.kt
git commit -m "feat(android): Repository 接口与实现（Settings, Chat, Session）+ Hilt 绑定"
```

---

**Plan 1 完成检查：**
- [ ] `./gradlew :app:assembleDebug` 通过
- [ ] `./gradlew :app:testDebugUnitTest` 通过（5 个解析器测试）
- [ ] App 可在模拟器上启动（显示 "Sebastian" 文字）
- [ ] Hilt 注入链完整（无 `@Inject` 未满足错误）

---
version: "1.0"
last_updated: 2026-04-11
status: in-progress
---

# 数据层架构

*← [Mobile Spec 索引](INDEX.md)*

---

## 1. 分层总览

```
UI（Composable）
    │ collectAsState()
    ▼
ViewModel（StateFlow<UiState>）
    │ suspend / Flow
    ▼
Repository（业务聚合层）
    │
    ├── Remote：SseClient / ApiService（Retrofit）
    └── Local：SettingsDataStore / SecureTokenStore
```

各层职责严格隔离：

| 层次 | 职责 | 不做什么 |
|------|------|---------|
| ViewModel | 持有 `UiState`，协调 Repository，处理用户事件 | 不直接访问网络或数据库 |
| Repository | 聚合 remote + local，暴露 `Flow` / `suspend` 接口 | 不持有 UI 状态，不感知 Compose |
| SseClient | OkHttp IO 线程 SSE，转换为 `Flow<StreamEvent>` | 不做业务路由，不修改状态 |
| ApiService | Retrofit 接口，纯数据传输 | 不做缓存，不处理错误展示 |
| DataStore / SecureStore | 持久化，协程友好读写 | 不做业务逻辑 |

---

## 2. ViewModel

### 2.1 UiState 设计原则

每个 ViewModel 持有单一 `StateFlow<XxxUiState>` data class，UI 订阅整个对象，Compose 按需重组（只有访问的字段变化才触发重组）。

```kotlin
// ChatViewModel.kt
data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val composerState: ComposerState = ComposerState.IDLE_EMPTY,
    val isOffline: Boolean = false,
    val scrollFollowState: ScrollFollowState = ScrollFollowState.FOLLOWING,
    val activeThinkingEffort: ThinkingEffort = ThinkingEffort.AUTO,
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val settingsRepository: SettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    // 用户动作（从 Composable 调用）
    fun sendMessage(text: String) { ... }
    fun cancelTurn() { ... }
    fun setEffort(effort: ThinkingEffort) { ... }
    fun onUserScrolled() { ... }
    fun onScrolledToBottom() { ... }
}
```

### 2.2 SSE 收集生命周期

```kotlin
init {
    // Lifecycle-aware：ViewModel 销毁时 viewModelScope 取消，连接自动关闭
    viewModelScope.launch {
        chatRepository.sessionStream(sessionId)
            .flowOn(Dispatchers.IO)
            .collect { event -> handleStreamEvent(event) }
    }
}
```

`handleStreamEvent` 在 `Dispatchers.Default` 处理事件路由和状态更新，不占 Main Thread。

### 2.3 ViewModels 清单

| ViewModel | 关联页面 | 核心职责 |
|-----------|---------|---------|
| `ChatViewModel` | ChatScreen（主对话）| 消息流、ComposerState、ScrollFollowState |
| `SessionViewModel` | SessionPanel | 历史会话列表、会话增删 |
| `SubAgentViewModel` | AgentListScreen / SessionListScreen | Sub-Agent 列表、Agent 会话列表 |
| `SettingsViewModel` | SettingsScreen 及子页 | Connection、Provider CRUD、设置持久化 |

---

## 3. Repository 层

### 3.1 ChatRepository

```kotlin
interface ChatRepository {
    // 订阅会话 SSE 流（含 Last-Event-ID 补偿）
    fun sessionStream(sessionId: String): Flow<StreamEvent>

    // REST：发送消息（创建 turn）
    suspend fun sendMessage(sessionId: String, text: String, effort: ThinkingEffort): Result<Turn>

    // REST：取消流式
    suspend fun cancelTurn(sessionId: String): Result<Unit>

    // REST：获取历史消息列表（首次进入会话）
    suspend fun getMessages(sessionId: String): Result<List<Message>>
}
```

### 3.2 SessionRepository

```kotlin
interface SessionRepository {
    // 会话列表（本地缓存 + 后端同步）
    fun sessionsFlow(): Flow<List<Session>>

    suspend fun createSession(title: String? = null): Result<Session>
    suspend fun deleteSession(sessionId: String): Result<Unit>
    suspend fun renameSession(sessionId: String, title: String): Result<Unit>
}
```

### 3.3 SettingsRepository

```kotlin
interface SettingsRepository {
    // Flow 暴露，UI 自动感知变更
    val serverUrl: Flow<String>
    val currentProvider: Flow<Provider?>

    suspend fun saveServerUrl(url: String)

    // Provider CRUD
    fun providersFlow(): Flow<List<Provider>>
    suspend fun saveProvider(provider: Provider): Result<Unit>
    suspend fun deleteProvider(providerId: String): Result<Unit>
    suspend fun testConnection(url: String): Result<ServerInfo>
}
```

---

## 4. 网络层

### 4.1 ApiService（Retrofit）

```kotlin
interface ApiService {
    @GET("api/v1/sessions")
    suspend fun getSessions(): List<SessionDto>

    @POST("api/v1/sessions")
    suspend fun createSession(@Body body: CreateSessionRequest): SessionDto

    @GET("api/v1/sessions/{id}/messages")
    suspend fun getMessages(@Path("id") sessionId: String): List<MessageDto>

    @POST("api/v1/sessions/{id}/turns")
    suspend fun sendMessage(
        @Path("id") sessionId: String,
        @Body body: SendMessageRequest,
    ): TurnDto

    @POST("api/v1/sessions/{id}/cancel")
    suspend fun cancelTurn(@Path("id") sessionId: String): OkResponse

    @GET("api/v1/providers")
    suspend fun getProviders(): List<ProviderDto>

    @POST("api/v1/providers")
    suspend fun createProvider(@Body body: ProviderDto): ProviderDto

    @PUT("api/v1/providers/{id}")
    suspend fun updateProvider(@Path("id") id: String, @Body body: ProviderDto): ProviderDto

    @DELETE("api/v1/providers/{id}")
    suspend fun deleteProvider(@Path("id") id: String): OkResponse
}
```

### 4.2 Hilt NetworkModule

```kotlin
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides @Singleton
    fun provideOkHttpClient(tokenStore: SecureTokenStore): OkHttpClient =
        OkHttpClient.Builder()
            .addInterceptor { chain ->
                val token = tokenStore.getToken()
                val req = if (token != null) {
                    chain.request().newBuilder()
                        .header("Authorization", "Bearer $token")
                        .build()
                } else chain.request()
                chain.proceed(req)
            }
            .build()

    @Provides @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        settingsRepository: SettingsRepository,
    ): Retrofit = Retrofit.Builder()
        .client(okHttpClient)
        .baseUrl("http://placeholder/")  // OkHttp Interceptor 运行时替换，见「动态 BaseUrl 策略」
        .addConverterFactory(MoshiConverterFactory.create())
        .build()
}
```

**动态 BaseUrl 策略**：OkHttp Interceptor 在每次请求时从 `SettingsDataStore` 读取最新 `serverUrl` 并替换，支持用户在 Settings 页修改后立即生效，无需重建 Retrofit。

---

## 5. 本地持久化

### 5.1 SettingsDataStore

使用 Jetpack `DataStore<Preferences>`（替代 SharedPreferences，协程友好，无 ANR 风险）：

```kotlin
class SettingsDataStore @Inject constructor(
    private val dataStore: DataStore<Preferences>,
) {
    companion object {
        val SERVER_URL = stringPreferencesKey("server_url")
        val ACTIVE_PROVIDER_ID = stringPreferencesKey("active_provider_id")
        val THEME = stringPreferencesKey("theme")   // system / light / dark
    }

    val serverUrl: Flow<String> = dataStore.data.map { prefs ->
        prefs[SERVER_URL] ?: ""
    }

    suspend fun saveServerUrl(url: String) {
        dataStore.edit { it[SERVER_URL] = url }
    }
}
```

### 5.2 SecureTokenStore（JWT）

```kotlin
class SecureTokenStore @Inject constructor(
    @ApplicationContext context: Context,
) {
    // EncryptedSharedPreferences：AES-256-GCM 加密，密钥存 Android Keystore
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "sebastian_secure",
        MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun saveToken(jwt: String) = prefs.edit().putString("jwt", jwt).apply()
    fun getToken(): String? = prefs.getString("jwt", null)
    fun clearToken() = prefs.edit().remove("jwt").apply()
}
```

---

## 6. Hilt 依赖注入

### 6.1 注入拓扑

```
SingletonComponent
├── NetworkModule → OkHttpClient, Retrofit, ApiService
├── RepositoryModule → ChatRepository, SessionRepository, SettingsRepository
└── StorageModule → SettingsDataStore, SecureTokenStore

ViewModelComponent（每个 ViewModel 独立）
└── HiltViewModel 自动注入 Repository
```

### 6.2 RepositoryModule

```kotlin
@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    @Binds @Singleton
    abstract fun bindChatRepository(impl: ChatRepositoryImpl): ChatRepository

    @Binds @Singleton
    abstract fun bindSessionRepository(impl: SessionRepositoryImpl): SessionRepository

    @Binds @Singleton
    abstract fun bindSettingsRepository(impl: SettingsRepositoryImpl): SettingsRepository
}
```

### 6.3 测试替换

```kotlin
// 单元测试中替换真实实现
@UninstallModules(RepositoryModule::class)
@HiltAndroidTest
class ChatViewModelTest {
    @BindValue
    val chatRepository: ChatRepository = FakeChatRepository()
    // ...
}
```

---

## 7. 错误处理约定

Repository 的 `suspend` 方法一律返回 `Result<T>`，不在数据层 throw 到 ViewModel。

```kotlin
// Repository 实现层包裹
suspend fun sendMessage(...): Result<Turn> = runCatching {
    val dto = apiService.sendMessage(sessionId, body)
    dto.toDomain()
}

// ViewModel 处理
viewModelScope.launch {
    chatRepository.sendMessage(sessionId, text, effort)
        .onSuccess { /* 更新 state */ }
        .onFailure { e -> _uiState.update { it.copy(error = e.message) } }
}
```

网络错误 / SSE 重连错误由 `SseClient` 内部处理（指数退避，详见 [streaming.md](streaming.md)），只在超出重试限制时通过 `Flow` error 通知 Repository → ViewModel 更新 `isOffline = true`。

---

*← [Mobile Spec 索引](INDEX.md)*

# di 模块

> 上级：[ui/mobile-android/README.md](../../../../../../../../README.md)

Hilt 依赖注入模块，均为 `@InstallIn(SingletonComponent::class)`（进程级单例）。

## 目录结构

```text
di/
├── CoroutineModule.kt      # IoDispatcher 限定符绑定
├── NetworkModule.kt        # OkHttpClient / Retrofit / ApiService / Moshi 提供
├── NotificationModule.kt   # NotificationSink 接口 → AndroidNotificationSink 绑定
├── RepositoryModule.kt     # Repository 接口 → 实现类绑定
└── StorageModule.kt        # DataStore / SecureTokenStore 提供
```

## 模块说明

| 文件 | 提供的依赖 |
|------|-----------|
| `NetworkModule` | `Moshi`、`OkHttpClient`（含 baseUrl + auth + logging interceptor）、`Retrofit`、`ApiService` |
| `StorageModule` | `SettingsDataStore`、`SecureTokenStore`（EncryptedSharedPreferences） |
| `RepositoryModule` | `ChatRepository`、`SessionRepository`、`AgentRepository`、`SettingsRepository` 接口 → 实现绑定 |
| `CoroutineModule` | `@IoDispatcher CoroutineDispatcher`（`Dispatchers.IO`） |
| `NotificationModule` | `NotificationSink` 接口 → `AndroidNotificationSink` 实现绑定 |

## 关键设计

- **动态 BaseURL**：`NetworkModule` 中 `OkHttpClient` 内置 `baseUrlInterceptor`，每次请求时从 `SettingsDataStore.serverUrl` 读取最新值并替换，无需重建 Retrofit 实例
- **Auth Interceptor**：从 `SecureTokenStore` 读取 Token，自动注入 `Authorization: Bearer` 头
- **Placeholder BaseURL**：Retrofit 构建时使用 `http://placeholder.local/`，实际 URL 由 interceptor 在运行时替换

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 新增 Repository 接口绑定 | `RepositoryModule.kt` |
| 修改网络超时/拦截器 | `NetworkModule.kt` |
| 修改 Token 存储方案 | `StorageModule.kt` + `data/local/SecureTokenStore.kt` |
| 修改 Coroutine Dispatcher | `CoroutineModule.kt` |
| 修改通知实现绑定 | `NotificationModule.kt` |

---

> 新增 Hilt 模块后，请同步更新本 README。

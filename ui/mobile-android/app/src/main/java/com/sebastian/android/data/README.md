# data 层

> 上级：[ui/mobile-android/README.md](../../../../../../../../README.md)

数据层，遵循 Clean Architecture 的 Repository 模式，屏蔽 UI 和 ViewModel 对数据来源的感知。

## 目录结构

```text
data/
├── local/
│   ├── MarkdownParser.kt           # Markwon 渲染接口（抽象）
│   ├── MarkwonMarkdownParser.kt    # Markwon 实现（DI 注入）
│   ├── NetworkMonitor.kt           # 网络状态监听（Flow<Boolean>）
│   ├── SecureTokenStore.kt         # JWT Token 加密存储（EncryptedSharedPreferences）
│   └── SettingsDataStore.kt        # Server URL 等偏好配置（DataStore<Preferences>）
├── model/
│   ├── AgentInfo.kt                # Sub-Agent 信息模型
│   ├── ContentBlock.kt             # 消息内容块（TextBlock / ThinkingBlock / ToolBlock）
│   ├── Message.kt                  # 消息模型（含 blocks 列表）
│   ├── Provider.kt                 # LLM Provider 模型
│   ├── Session.kt                  # Session 模型
│   └── StreamEvent.kt              # SSE 事件模型（sealed class）
├── remote/
│   ├── ApiService.kt               # Retrofit 接口声明（REST 端点）
│   ├── SseClient.kt                # OkHttp SSE 客户端（含指数退避重连）
│   └── dto/
│       ├── MessageDto.kt           # 消息 DTO + 映射函数
│       ├── ProviderDto.kt          # Provider DTO
│       ├── SessionDto.kt           # Session DTO
│       ├── SseFrameDto.kt          # SSE 帧解析（JSON → StreamEvent）
│       └── TurnDto.kt              # Turn 请求/响应 DTO
└── repository/
    ├── AgentRepository.kt          # Agent 数据接口
    ├── AgentRepositoryImpl.kt      # Agent 数据实现
    ├── ChatRepository.kt           # 主对话接口（发送/取消/审批/消息历史/SSE）
    ├── ChatRepositoryImpl.kt       # 主对话实现
    ├── SessionRepository.kt        # Session 列表接口
    ├── SessionRepositoryImpl.kt    # Session 列表实现
    ├── SettingsRepository.kt       # 设置接口（serverUrl / credentials）
    └── SettingsRepositoryImpl.kt   # 设置实现
```

## 模块说明

### `local/`

本地存储与系统服务封装。

- **`SecureTokenStore`**：使用 `EncryptedSharedPreferences` 存储 JWT Token，支持 `getToken()` / `saveToken()` / `clearToken()`
- **`SettingsDataStore`**：使用 `DataStore<Preferences>` 持久化 serverUrl，暴露 `serverUrl: Flow<String>` 和 `StateFlow`
- **`NetworkMonitor`**：通过 `ConnectivityManager.NetworkCallback` 监听网络状态，暴露 `isOnline: Flow<Boolean>`
- **`MarkdownParser`** / **`MarkwonMarkdownParser`**：异步 Markdown 渲染接口，TextBlockStop 事件触发时渲染

### `model/`

领域模型（UI 层直接使用，不含网络字段）。

- **`ContentBlock`**：sealed class，三种子类型：
  - `TextBlock`：文本块，含 `renderedMarkdown: CharSequence?`（渲染后供 AndroidView 显示）
  - `ThinkingBlock`：思考块，支持展开/折叠（`expanded`）
  - `ToolBlock`：工具调用块，含 `status: ToolStatus`（PENDING / RUNNING / DONE / FAILED）
- **`StreamEvent`**：sealed class，映射 SSE 帧的所有事件类型（TurnReceived / TextDelta / ToolRunning / ApprovalRequested 等）
- **`Message`**：包含 `blocks: List<ContentBlock>`，支持多块混合内容

### `remote/`

网络通信层。

- **`ApiService`**：Retrofit 接口，涵盖认证、主对话 turn、session CRUD、agent、provider、审批、health 等端点
- **`SseClient`**：OkHttp SSE 实现，提供：
  - `sessionStream(baseUrl, sessionId, lastEventId)`：单 session 事件流
  - `globalStream(baseUrl, lastEventId)`：全局事件流
  - 内置指数退避重连（1s / 2s / 4s，最多 3 次），Last-Event-ID 跨连接持久化
- **`dto/`**：DTO + 解析逻辑，`SseFrameDto.kt` 中的 `SseFrameParser.parse()` 将 JSON 字符串解析为 `StreamEvent`

### `repository/`

Repository 接口与实现（均通过 Hilt 在 `di/RepositoryModule.kt` 绑定）。

- **`ChatRepository`**：核心接口，包含 `sendTurn()` / `sendSessionTurn()` / `cancelTurn()` / `getMessages()` / `sessionStream()` / `grantApproval()` / `denyApproval()`
- **`SettingsRepository`**：提供 `serverUrl: Flow<String>` / `saveServerUrl()` / `token` 读写
- **`SessionRepository`**：session 列表加载、新建、删除
- **`AgentRepository`**：agent 列表加载、agent session 加载/创建

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 新增 REST 端点 | `remote/ApiService.kt` + 对应 DTO |
| 修改 SSE 帧解析 | `remote/dto/SseFrameDto.kt` |
| 修改 SSE 重连策略 | `remote/SseClient.kt` |
| 修改本地 Token 存储 | `local/SecureTokenStore.kt` |
| 修改设置持久化字段 | `local/SettingsDataStore.kt` + `repository/SettingsRepositoryImpl.kt` |
| 新增消息内容块类型 | `model/ContentBlock.kt` + `model/StreamEvent.kt` + `remote/dto/SseFrameDto.kt` |
| 修改 Repository 接口 | 对应 `repository/XxxRepository.kt` + `XxxRepositoryImpl.kt` + `di/RepositoryModule.kt` |
| 修改 Markdown 渲染 | `local/MarkwonMarkdownParser.kt` + `di/MarkdownModule.kt` |

---

> 修改 data 层结构后，请同步更新本 README 与上级 `ui/mobile-android/README.md`。

# data 层

> 上级：[ui/mobile-android/README.md](../../../../../../../../README.md)

数据层，遵循 Clean Architecture 的 Repository 模式，屏蔽 UI 和 ViewModel 对数据来源的感知。

## 目录结构

```text
data/
├── local/
│   ├── NetworkMonitor.kt           # 网络状态监听（Flow<Boolean>）
│   ├── SecureTokenStore.kt         # JWT Token 加密存储（EncryptedSharedPreferences）
│   └── SettingsDataStore.kt        # Server URL 等偏好配置（DataStore<Preferences>）
├── model/
│   ├── AgentInfo.kt                # Sub-Agent 信息模型（含 boundProviderId）
│   ├── ApprovalSnapshot.kt         # 待审批条目快照（GET /approvals 响应领域模型）
│   ├── ContentBlock.kt             # 消息内容块（TextBlock / ThinkingBlock / ToolBlock）
│   ├── MemoryComponentInfo.kt      # 记忆组件信息模型（componentType / displayName / boundProviderId / thinkingEffort）
│   ├── Message.kt                  # 消息模型（含 blocks 列表）
│   ├── Provider.kt                 # LLM Provider 模型
│   ├── Session.kt                  # Session 模型
│   ├── StreamEvent.kt              # SSE 事件模型（sealed class）
│   └── ThinkingEffort.kt           # ThinkingEffort 枚举序列化扩展（toApiString / toThinkingEffort / displayLabel）
├── remote/
│   ├── ApiService.kt               # Retrofit 接口声明（REST 端点）
│   ├── GlobalSseDispatcher.kt      # 全局 SSE 单例（事件广播 + 连接状态）
│   ├── SseClient.kt                # OkHttp SSE 客户端（含指数退避重连）
│   └── dto/
│       ├── AgentBindingDto.kt      # Agent LLM 绑定 DTO（SetBindingRequest / AgentBindingDto）
│       ├── AgentDto.kt             # Agent 列表 DTO（AgentListResponse / AgentDto）
│       ├── LogStateDto.kt          # 日志状态 DTO（LogStateDto / LogConfigPatchDto）
│       ├── MemoryComponentDto.kt   # 记忆组件 DTO（MemoryComponentDto / MemoryComponentsResponse，含 toDomain()）
│       ├── MemorySettingsDto.kt    # 记忆设置 DTO（MemorySettingsDto，含 enabled 字段）
│       ├── MessageDto.kt           # 消息 DTO + 映射函数
│       ├── ProviderDto.kt          # Provider DTO
│       ├── SessionDto.kt           # Session DTO
│       ├── SseFrameDto.kt          # SSE 帧解析（JSON → StreamEvent）
│       ├── TimelineItemDto.kt      # timeline 行 DTO（镜像后端 session timeline，seq / role / block_type 等字段）
│       ├── TimelineMapper.kt       # TimelineItemDto 列表 → List<Message> 转换，context_summary → SummaryBlock
│       └── TurnDto.kt              # Turn 请求/响应 DTO
├── sync/
│   └── AppStateReconciler.kt       # App 前台恢复时的状态对账（审批队列 REST 同步）
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

### `model/`

领域模型（UI 层直接使用，不含网络字段）。

- **`ContentBlock`**：sealed class，四种子类型：
  - `TextBlock`：文本块，含原始 `text: String`，由 `MarkdownView` 负责渲染
  - `ThinkingBlock`：思考块，支持展开/折叠（`expanded`）
  - `ToolBlock`：工具调用块，含 `status: ToolStatus`（PENDING / RUNNING / DONE / FAILED）
  - `SummaryBlock`：上下文压缩摘要块，对应 timeline 中的 `context_summary` 行，渲染为折叠卡片"Compressed summary"
- **`MemoryComponentInfo`**：记忆组件领域模型，含 `componentType`、`displayName`、`description`、`boundProviderId`、`thinkingEffort`；由 `MemoryComponentDto.toDomain()` 生成
- **`ThinkingEffort`**：枚举序列化扩展函数集合：`String?.toThinkingEffort()` 解析 API 字符串，`toApiString()` 序列化为 API 字符串（OFF → null），`displayLabel()` 返回 UI 可展示的非空标签
- **`StreamEvent`**：sealed class，映射 SSE 帧的所有事件类型（TurnReceived / TextDelta / ToolRunning / ApprovalRequested 等）
- **`Message`**：包含 `blocks: List<ContentBlock>`，支持多块混合内容
- **`ApprovalSnapshot`**：REST 快照用的待审批条目（字段与 `GlobalApproval` 对齐，独立存放以避免 repository 反向依赖 viewmodel 包）

### `remote/`

网络通信层。

- **`ApiService`**：Retrofit 接口，涵盖认证、主对话 turn、session CRUD、agent、provider、审批、日志状态、health 等端点
- **`GlobalSseDispatcher`**：进程级单例，订阅全局 SSE 流，将 `StreamEvent` 广播给所有订阅者；暴露 `events: SharedFlow<StreamEvent>` 和 `connectionState: StateFlow<ConnectionState>`（Disconnected / Connecting / Connected）
- **`SseClient`**：OkHttp SSE 实现，提供：
  - `sessionStream(baseUrl, sessionId, lastEventId)`：单 session 事件流
  - `globalStream(baseUrl, lastEventId)`：全局事件流
  - 内置指数退避重连（1s / 2s / 4s，最多 3 次），Last-Event-ID 跨连接持久化
- **`dto/`**：DTO + 解析逻辑，`SseFrameDto.kt` 中的 `SseFrameParser.parse()` 将 JSON 字符串解析为 `StreamEvent`；`AgentDto.kt` 含 `AgentListResponse`；`AgentBindingDto.kt` 含 `SetBindingRequest` / `AgentBindingDto`；`LogStateDto.kt` 含 `LogStateDto` / `LogConfigPatchDto`；`MemoryComponentDto.kt` 含 `MemoryComponentDto` / `MemoryComponentsResponse`，`toDomain()` 将 DTO 转换为领域模型；`MemorySettingsDto.kt` 含 `MemorySettingsDto`（enabled 字段），用于 GET/PUT `/memory/settings`
- **`TimelineItemDto`**：镜像后端 session timeline 行（`seq`、`role`、`block_type`、`content`、`tool_name` 等字段），通过 `GET /api/v1/sessions/{id}?include_archived=true` 响应中的 `timeline_items` 数组返回
- **`TimelineMapper`**：唯一将 `TimelineItemDto` 列表转换为 `List<Message>` 的入口；`context_summary` 块映射为 `ContentBlock.SummaryBlock`，archived 原始行正常渲染，不做隐藏或置灰
- **`SseEnvelope`**：`data class SseEnvelope(val eventId: String?, val event: StreamEvent)`，在 `SseClient` 内部将 SSE `id:` 字段与解析后的事件一起传递，供 `ChatViewModel` 追踪 `lastDeliveredSseEventIds` 回放游标

### `repository/`

Repository 接口与实现（均通过 Hilt 在 `di/RepositoryModule.kt` 绑定）。

- **`ChatRepository`**：核心接口，包含 `sendTurn()` / `sendSessionTurn()` / `cancelTurn()` / `getMessages()` / `sessionStream()` / `globalStream()` / `grantApproval()` / `denyApproval()` / `getPendingApprovals()`
- **`SettingsRepository`**：提供 `serverUrl: Flow<String>` / `saveServerUrl()` / `token` 读写
- **`SessionRepository`**：session 列表加载、新建、删除
- **`AgentRepository`**：agent 列表加载、agent session 加载/创建、LLM 绑定设置（`setBinding()` / `clearBinding()`）

### `sync/`

App 状态对账层。

- **`AppStateReconciler`**：进程级单例（Hilt `@Singleton`），App 从后台恢复时通过 `reconcile()` 触发防抖（150ms），调用 `ChatRepository.getPendingApprovals()` 拉取最新待审批列表，再通过 `GlobalApprovalViewModel.replaceAll()` 覆盖本地状态，消除 SSE 断连期间可能积累的漏单

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 新增 REST 端点 | `remote/ApiService.kt` + 对应 DTO |
| 修改 SSE 帧解析 | `remote/dto/SseFrameDto.kt` |
| 修改 SSE 重连策略 | `remote/SseClient.kt` |
| 修改本地 Token 存储 | `local/SecureTokenStore.kt` |
| 修改设置持久化字段 | `local/SettingsDataStore.kt` + `repository/SettingsRepositoryImpl.kt` |
| 新增消息内容块类型 | `model/ContentBlock.kt` + `model/StreamEvent.kt` + `remote/dto/SseFrameDto.kt` |
| 修改 timeline 解析逻辑 | `remote/dto/TimelineItemDto.kt` + `remote/dto/TimelineMapper.kt` |
| 修改 SSE 事件 ID 传递 | `remote/SseClient.kt`（`SseEnvelope` 包装层） |
| 修改 Repository 接口 | 对应 `repository/XxxRepository.kt` + `XxxRepositoryImpl.kt` + `di/RepositoryModule.kt` |
| 修改审批对账逻辑 | `sync/AppStateReconciler.kt` |
| 修改全局 SSE 广播 | `remote/GlobalSseDispatcher.kt` |
| 修改 Agent 绑定 DTO | `remote/dto/AgentBindingDto.kt` + `remote/ApiService.kt` |
| 修改日志状态 API | `remote/dto/LogStateDto.kt` + `remote/ApiService.kt` |
| 修改记忆组件 LLM 绑定 DTO | `remote/dto/MemoryComponentDto.kt` + `remote/ApiService.kt` |
| 修改记忆开关设置 DTO | `remote/dto/MemorySettingsDto.kt` + `remote/ApiService.kt` |

---

> 修改 data 层结构后，请同步更新本 README 与上级 `ui/mobile-android/README.md`。

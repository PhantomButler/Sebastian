# viewmodel 层

> 上级：[ui/mobile-android/README.md](../../../../../../../../README.md)

MVVM ViewModel 层，使用 Hilt 注入依赖，通过 `StateFlow<UiState>` 向 UI 单向暴露状态。

## 目录结构

```text
viewmodel/
├── ChatViewModel.kt          # 主对话状态机（SSE 订阅、消息渲染、审批）
├── ProviderFormViewModel.kt  # Provider 新增/编辑表单状态
├── SessionViewModel.kt       # Session 列表与新建
├── SettingsViewModel.kt      # 设置页状态（serverUrl、当前 provider）
└── SubAgentViewModel.kt      # Sub-Agent 列表与 Agent Session 管理
```

## 模块说明

### `ChatViewModel`

最复杂的 ViewModel，负责：

1. **SSE 订阅**：通过 `ChatRepository.sessionStream()` 订阅当前 session 的事件流，生命周期随 App 前台/后台切换（`onAppStart()` / `onAppStop()`）
2. **增量刷新**：50ms 定时器将 `pendingDeltas`（`ConcurrentHashMap<blockId, StringBuilder>`）批量合并到消息列表，减少 recomposition 频率（`flushTick` 驱动 `MessageList` 滚动）
3. **消息状态机**：处理全部 `StreamEvent` 类型，按 blockId 精确更新对应 `ContentBlock`
4. **三态连接错误**：`isServerNotConfigured` / `isOffline` / `connectionFailed`，优先级从高到低
5. **全局审批**：审批事件由 `GlobalApprovalViewModel` 统一处理，不再由 `ChatViewModel` 管理
6. **滚动跟随**：`ScrollFollowState`（FOLLOWING / DETACHED / NEAR_BOTTOM）

关键状态枚举：

| 枚举 | 值 |
|------|-----|
| `ComposerState` | IDLE_EMPTY / IDLE_READY / SENDING / STREAMING / CANCELLING |
| `ScrollFollowState` | FOLLOWING / DETACHED / NEAR_BOTTOM |
| `AgentAnimState` | IDLE / THINKING / STREAMING / WORKING |

### `SessionViewModel`

- 加载 session 列表（`SessionRepository.getSessions()`）
- 新建 session（`SessionRepository.createSession()`）
- 暴露 `SessionUiState`（sessions 列表 + loading/error 标志）

### `SettingsViewModel`

- 读写 `serverUrl`（via `SettingsRepository`）
- 加载当前 LLM provider（`currentProvider`）
- 处理登录/登出（`ConnectionPage` 使用）

### `SubAgentViewModel`

- 加载 agent 列表（`AgentRepository.getAgents()`）
- 加载某 agent 的 session 列表（`AgentRepository.getAgentSessions(agentId)`）
- 新建 agent session（懒创建：`createAgentSession(agentType)`）

### `ProviderFormViewModel`

- 管理 Provider 表单状态（name / type / api_key / base_url / model / thinking_capability）
- 支持新增（`providerId == null`）和编辑（`providerId != null`）两种模式
- 调用 `createProvider()` / `updateProvider()` / `deleteProvider()`

## 数据流向

```
Repository (Flow / suspend fun)
        ↓  collect / onSuccess / onFailure
ViewModel (_uiState: MutableStateFlow<XxxUiState>)
        ↓  asStateFlow()
Screen (collectAsState())
        ↓  event callbacks
ViewModel (sendMessage / switchSession / ...)
```

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改主对话消息处理逻辑 | `ChatViewModel.handleEvent()` |
| 改 SSE 重连/断线逻辑 | `ChatViewModel.startSseCollection()` / `observeNetwork()` |
| 改全局审批处理 | `GlobalApprovalViewModel.grantApproval()` / `denyApproval()` |
| 改思考档位状态 | `ChatViewModel.setEffort()` |
| 改滚动跟随逻辑 | `ChatViewModel.onUserScrolled()` / `onScrolledNearBottom()` 等 |
| 改 session 列表加载 | `SessionViewModel` |
| 改设置页状态（serverUrl / provider） | `SettingsViewModel` |
| 改 Provider 表单逻辑 | `ProviderFormViewModel` |
| 改 Sub-Agent 状态 | `SubAgentViewModel` |

---

> 新增 ViewModel 或修改 UiState 定义后，请同步更新本 README。

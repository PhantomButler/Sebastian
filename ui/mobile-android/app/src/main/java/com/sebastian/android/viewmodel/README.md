# viewmodel 层

> 上级：[ui/mobile-android/README.md](../../../../../../../../README.md)

MVVM ViewModel 层，使用 Hilt 注入依赖，通过 `StateFlow<UiState>` 向 UI 单向暴露状态。

## 目录结构

```text
viewmodel/
├── AgentBindingsViewModel.kt       # Agent LLM 绑定主列表（仅加载）
├── AgentBindingEditorViewModel.kt  # 单个 Agent 绑定编辑（Provider + Thinking，防抖保存）
├── ChatViewModel.kt                # 主对话状态机（SSE 订阅、消息渲染）
├── GlobalApprovalViewModel.kt      # 全局审批队列（跨 session 的审批事件处理）
├── MemorySettingsViewModel.kt      # 记忆功能开关设置（toggle enabled，失败时回滚）
├── ProviderFormViewModel.kt        # Provider 新增/编辑表单状态
├── SessionViewModel.kt             # Session 列表与新建
├── SettingsViewModel.kt            # 设置页状态（serverUrl、当前 provider）
└── SubAgentViewModel.kt            # Sub-Agent 列表与 Agent Session 管理
```

## 模块说明

### `GlobalApprovalViewModel`

全局审批队列管理，负责：

1. **SSE 事件订阅**：通过 `GlobalSseDispatcher.events` 监听 `ApprovalRequested` / `ApprovalGranted` / `ApprovalDenied` 事件，实时 upsert / 移除审批项
2. **REST 快照同步**：由 `AppStateReconciler` 在 App 前台恢复时调用 `replaceAll(snapshot)` 覆盖本地审批列表
3. **审批操作**：`grantApproval(approvalId)` / `denyApproval(approvalId)` 先乐观移除本地项，再异步调用 Repository

暴露 `GlobalApprovalUiState`（`approvals: List<GlobalApproval>`）。

### `AgentBindingsViewModel`

Agent LLM 绑定主列表页的 ViewModel，仅负责数据加载：

- `load()`：并发加载 agent 列表和 provider 列表，合并到 `AgentBindingsUiState`

实际的绑定修改由次级编辑页 `AgentBindingEditorViewModel` 承担，主列表仅展示与导航。

### `AgentBindingEditorViewModel`

单个 Agent 的绑定编辑页 ViewModel（`@AssistedInject`，`Factory.create(agentType)`），负责：

- `load()`：拉取当前 binding 与 provider 列表；若服务端已保存档位超过当前 Provider capability 合法范围，自动钳到最高合法档并触发一次保存
- `selectProvider(providerId: String?)`：切换 Provider；切换时 `thinkingEffort` 复位为 `OFF`，若切换前存在配置则通过 snackbar 提示
- `setEffort(e: ThinkingEffort)`：修改思考档位
- 防抖自动保存：任何修改都会触发 300ms debounce 的 `schedulePut()`，调用 `AgentRepository.setBinding()`；失败时回滚到上一快照并 emit snackbar
- 暴露 `events: SharedFlow<EditorEvent>`，`EditorEvent.Snackbar(text)` 用于一次性提示

### `ChatViewModel`

最复杂的 ViewModel，负责：

1. **SSE 订阅**：通过 `ChatRepository.sessionStream()` 订阅当前 session 的事件流，生命周期随 App 前台/后台切换（`onAppStart()` / `onAppStop()`）
2. **增量刷新**：50ms 定时器将 `pendingDeltas`（`ConcurrentHashMap<blockId, StringBuilder>`）批量合并到消息列表，减少 recomposition 频率（`flushTick` 驱动 `MessageList` 滚动）
3. **消息状态机**：处理全部 `StreamEvent` 类型，按 blockId 精确更新对应 `ContentBlock`
4. **三态连接错误**：`isServerNotConfigured` / `isOffline` / `connectionFailed`，优先级从高到低
5. **全局审批**：审批事件由 `GlobalApprovalViewModel` 统一处理，不再由 `ChatViewModel` 管理

**Timeline Hydration 相关行为**：

- **客户端先行 Session ID**：新 Session 创建时由 App 生成 `UUID` 作为 `session_id`，SSE 先以该 ID 订阅，首条 turn POST 时携带同一 `session_id`，防止流事件在 REST 返回前丢失
- **`lastDeliveredSseEventIds`**：`Map<sessionId, String>` 短期回放游标，记录每个 session 最后收到的 SSE `event id`；切换 session 或断线重连时作为 `Last-Event-ID` 头传给服务端，服务端可补发漏掉的事件；REST timeline 仍是持久化权威来源
- **`ChatUiEffect`**：`sealed class`（`RestoreComposerText` / `ShowToast`），通过 `SharedFlow` 发一次性 UI 副作用；`RestoreComposerText` 在发送失败时将用户已输入的文本回填到 Composer，`ShowToast` 用于错误提示

> 滚动跟随语义由 UI 层（`MessageList`）自行维护（`atBottom` / `isUserDragging` / `userAway` 三层模型），
> ViewModel 不再持有 `ScrollFollowState` 字段或相关回调。

关键状态枚举：

| 枚举 | 值 |
|------|-----|
| `ComposerState` | IDLE_EMPTY / IDLE_READY / PENDING / STREAMING / CANCELLING |
| `AgentAnimState` | IDLE / PENDING / THINKING / STREAMING / WORKING |

### PENDING 语义

- **进入：** `sendMessage()` 入口（用户点发送）
- **持续：** 从发送到首个 SSE block 事件（`ThinkingBlockStart` / `TextBlockStart` / `ToolBlockStart`）；`TurnReceived` 不触发切换
- **退出：** 首个 block SSE 事件 → STREAMING/THINKING/WORKING；或 `TurnCancelled` / `TurnInterrupted` / `TurnResponse` → IDLE_EMPTY
- `SendButton` 显示可点停止；无 `activeSessionId` 时点停止走本地取消（保留 Composer 文本 + 用户气泡）
- 15s 前台累计超时触发"响应较慢"提示，`onAppStop` 暂停计时 / `onAppStart` 按剩余时长恢复
- `onAppStart` 在 PENDING 下调 `getMessages` 判断后台期是否已完成 turn；无论成败均重连 SSE
- AgentPill 显示 `BREATHING`（彩虹呼吸动画），文案"等待响应"

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

### `MemorySettingsViewModel`

记忆功能开关页 ViewModel（`@HiltViewModel`），负责：

- 初始化时调用 `SettingsRepository.getMemorySettings()` 加载当前开关状态
- `toggle(enabled)`：乐观更新本地 `enabled`，异步调用 `SettingsRepository.setMemoryEnabled()`；失败时回滚到调用前的值并 emit 错误提示
- 暴露 `MemorySettingsUiState`（`enabled` / `isLoading` / `error` / `errorSerial`），`errorSerial` 递增用于触发一次性 Snackbar

### `ProviderFormViewModel`

- 管理 LLM Account 表单状态（name / selectedCatalogId / providerType / base_url / api_key）
- 支持新增（`existingId == null`）和编辑（`existingId != null`）两种模式
- 支持内置 catalog 模式（`selectedCatalogId != "custom"`）和自定义模式（`selectedCatalogId == "custom"`，需填 base_url）
- 调用 `repository.createLlmAccount()` / `repository.updateLlmAccount()`；删除由 `ProviderListPage` 直接触发

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
| 改 SSE 回放游标逻辑 | `ChatViewModel`（`lastDeliveredSseEventIds` 字段） |
| 改发送失败回滚/提示 | `ChatViewModel`（`ChatUiEffect.RestoreComposerText` / `ShowToast`） |
| 改全局审批处理 | `GlobalApprovalViewModel.grantApproval()` / `denyApproval()` |
| 改 Agent LLM 绑定主列表加载 | `AgentBindingsViewModel.load()` |
| 改单个 Agent 绑定编辑（Provider + Thinking） | `AgentBindingEditorViewModel.selectProvider()` / `setEffort()` |
| 改记忆开关设置 | `MemorySettingsViewModel.toggle()` |
| 改滚动跟随逻辑 | `ui/chat/MessageList.kt`（UI 层，ViewModel 不参与） |
| 改 session 列表加载 | `SessionViewModel` |
| 改设置页状态（serverUrl / provider） | `SettingsViewModel` |
| 改 Provider 表单逻辑 | `ProviderFormViewModel` |
| 改 Sub-Agent 状态 | `SubAgentViewModel` |

---

> 新增 ViewModel 或修改 UiState 定义后，请同步更新本 README。

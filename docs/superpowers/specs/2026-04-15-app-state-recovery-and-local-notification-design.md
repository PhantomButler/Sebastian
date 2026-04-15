# App 状态恢复 + 本地通知

## Context

Android App 目前存在两个相关问题，本 spec 合并处理：

### 问题 1：状态恢复机制缺失

[`GlobalApprovalViewModel`](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/GlobalApprovalViewModel.kt) 只在内存 `MutableStateFlow` 里维护 approval 队列。生命周期行为：

- `onAppStart()` 启动全局 SSE（`/api/v1/stream`）监听 `ApprovalRequested`
- `onAppStop()` 取消 SSE Job
- 内存里的列表**仅靠 SSE push 填充**，启动/回前台时**不主动拉取快照**

失效场景：

1. 进程被系统回收 → ViewModel 丢失 → 重启后列表为空
2. SSE 断连期间事件从服务端 ring buffer（500 条）滚出 → 重连不重放
3. `onAppStart()` 时错过了离线期间产生的 approval（SSE 是增量事件流，不主动推送"当前状态"）

**结果**：用户触发 tool call → 审批面板弹出 → 切后台回桌面再进来 → 面板消失 → agent 卡住无法继续。

后端其实已经有恢复接口：[`GET /api/v1/approvals`](../../../sebastian/gateway/routes/approvals.py) 返回 `status=pending` 记录，Android 侧 [`ApiService.kt:66`](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt) 也已定义该端点，**但没人调用**。

同类问题还存在于 `ChatViewModel`（当前 session 进行中的 turn 状态），用户切后台再回来可能看到半截 assistant 气泡或输入框状态错乱。

### 问题 2：App 离线无任何通知

- `AndroidManifest.xml` 无 `POST_NOTIFICATIONS` 权限、无 `FirebaseMessagingService`
- 代码库搜不到 FCM / Firebase / notification 相关实现
- 后端 gateway 无 device token 注册 / push 下发接口

用户离开 App 时，审批请求和任务完成事件都不会产生任何通知，必须主动打开 App 才能看到。

### 本 spec 决策

修复问题 1 + 实现**本地通知**（`NotificationManager`，覆盖"App 在后台但进程存活"窗口）。真正跨进程推送留给后续独立 spec（要考虑国内厂商聚合：小米 MiPush / HMS Push / OPPO / vivo / 聚合 SDK），因为：

- 推送选型牵涉国内生态决策（Google 依赖 vs 厂商 SDK vs 聚合），值得独立讨论
- 状态恢复是 bug 必须修，推送是新能力，不应耦合进同一次改动

## 非目标

- **不做跨进程推送**（FCM / 厂商推送 / 聚合 SDK）—— 独立 spec
- **不做通知富交互**（通知栏内批准按钮、`RemoteInput`）—— 打磨项
- **不做通知摘要合并**（inbox style 多条折叠）—— 打磨项
- **不做 draft 同步 / 设备列表 / 踢下线** —— 与本 spec 正交
- **不做 session 状态机的完整落地**（orchestrator 单点驱动、`POST /turns` 409 兜底）—— 属于 [multi-device-session-state-sync spec](2026-04-14-multi-device-session-state-sync-design.md)，本次只补 `GET /sessions/{id}/recent` 响应的 `state` 字段
- **不抽通用 reconcile 框架** —— 当前 ViewModel 种类少，提前抽象是过度设计

## 架构

### 核心原则：REST 快照 + SSE 增量（幂等 merge）

所有状态对象按稳定主键 upsert，`replaceAll(list)` 和 `upsert(item)` / `removeById(id)` 三个幂等操作构成完整状态流：

- REST 拉回的列表 → `replaceAll(list)` 整体覆盖
- SSE 来的增量事件 → `upsert(item)` 或 `removeById(id)`
- 主键：approvals 用 `approvalId`，messages 用 `messageId`，sessions 用 `sessionId`

两类操作合并顺序无所谓，天然幂等。

### 状态恢复流程

```
ProcessLifecycleOwner.ON_START        GlobalSse.onOpen
         │                                   │
         └───────────┬───────────────────────┘
                    ▼
          AppStateReconciler.reconcile()
          （150ms debounce 合并两个触发源）
                    ▼
       并行拉取 REST 快照：
         ├─ GET /api/v1/approvals
         │     → GlobalApprovalViewModel.replaceAll(list)
         └─ GET /api/v1/sessions/{currentId}/recent
               → ChatViewModel.replaceAll(snapshot)
                 （同时恢复消息列表 + session_state → 输入框置灰）
                    ▼
       之后 SSE 事件正常增量 merge
```

**触发时机**：

- `ProcessLifecycleOwner` 的 `ON_START`（冷启动 + 回前台统一）
- 全局 SSE `onOpen` 回调（首次建连 + 重连）
- 150ms debounce 把近距离的两个触发点合并成一次请求

**当前 session 来源**：Reconciler 观察 `SessionRepository.currentSessionId`（已有的 StateFlow），只拉当前 session 的 recent，不拉所有 session。

### SSE 分发改造

当前 `GlobalApprovalViewModel` 独占全局 SSE 订阅。`NotificationDispatcher` 也要消费同一条流（不能开第二条连接，会导致事件顺序错乱）。引入 `GlobalSseDispatcher`：

```
OkHttp SSE /api/v1/stream
           │
           ▼
   GlobalSseDispatcher（Hilt Singleton）
     MutableSharedFlow<StreamEvent>（replay=0, extraBufferCapacity=64）
           │
           ├──→ GlobalApprovalViewModel.handleEvent()（现有逻辑迁移）
           └──→ NotificationDispatcher.handleEvent()（新增）
```

- 单条物理连接、单次订阅，多个消费者通过 `SharedFlow` 分发
- `GlobalSseDispatcher` 持有 SSE 连接生命周期，不再由 `GlobalApprovalViewModel` 管理
- 连接启停仍绑定 `ProcessLifecycleOwner`（后台断开省电、前台重连）

### 本地通知分发

```
GlobalSseDispatcher.events
        ↓
NotificationDispatcher.handleEvent(event)
        ↓
检查 ProcessLifecycleOwner.currentState >= STARTED ？
    是（前台）→ 丢弃，由应用内 UI 处理
    否（后台）→ 按事件类型映射到通知
```

**事件 → 通知映射**：

| 事件 | Channel | 优先级 | 标题 | 内容 | 点击 |
|------|---------|-------|------|------|------|
| `ApprovalRequested` | `approval` | HIGH (heads-up) | `需要审批：{toolName}` | `reason`（截断 120 字） | 跳转对应 session |
| `TurnCompleted` | `task_progress` | DEFAULT | `{agentName} 已完成` | 末条消息摘要（截断 120 字） | 跳转对应 session |
| `TurnFailed` | `task_progress` | DEFAULT | `{agentName} 执行失败` | error 摘要（截断 120 字） | 跳转对应 session |
| 其他（`TextDelta` / `Thinking` / `ApprovalGranted` / ...） | — | — | — | — | 不通知 |

**Channel 设计**：

- `approval` — HIGH：审批不处理 agent 就停住，heads-up + 声音 + 震动
- `task_progress` — DEFAULT：完成类"有空看一眼"，通知栏静默（含 TurnCompleted + TurnFailed；失败频次低不单独分 channel，过度设计）

用户可在系统设置里单独关掉某个 channel。Channel 初始化放在 `SebastianApp.onCreate`（`createNotificationChannel` 幂等）。

**通知去重**：

- `notificationId = event.primaryKey.hashCode()`（approvalId / turnId）
- 同一 approval 后续被 granted/denied 时，`NotificationManager.cancel(notificationId)` 撤回旧通知，避免用户点进去批完了通知栏还挂着过期提醒
- 订阅 `ApprovalGranted` / `ApprovalDenied` 事件触发撤回

### 权限处理

- `AndroidManifest.xml` 新增 `<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />`（Android 13+ 运行时，低版本自动视为已授权）
- `MainActivity.onCreate` 首次 `ON_START` 时用 `ActivityResultContracts.RequestPermission` 请求一次
- 用户拒绝后不再主动弹；在 **Settings 页** 加一行状态："通知权限未开启 [去设置]"，点击 `Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)` 跳系统通知设置

### 点击跳转

Deep link `sebastian://session/{sessionId}`：

- `AndroidManifest.xml` 的 `MainActivity` 加 `<intent-filter>` 声明 scheme
- `MainActivity.onNewIntent` / Navigation 的 deep link 处理器解析 `sessionId`，导航到 `Route.Chat(sessionId)` 或 `Route.AgentChat(agentId, ...)`（根据 session 所属 agent 判断）
- 不带 `openApproval=true` 之类 flag（多 approval 并发是低频边界，GlobalApprovalBanner 自然按队列显示）

### 后端配合改动

**1. `GET /api/v1/sessions/{id}/recent` 响应新增 `session_state` 字段**

值域：`"idle" | "user_sending" | "assistant_streaming" | "awaiting_approval"`

这是 [multi-device-session-state-sync spec](2026-04-14-multi-device-session-state-sync-design.md) 已规划字段，本次先落快照恢复这一半，完整状态机（orchestrator 单点驱动 + `POST /turns` 409 兜底）留给该 spec 正式执行。本 spec 的 `ChatViewModel.replaceAll(snapshot)` 基于该字段恢复输入框置灰状态。

**2. `TurnCompleted` / `TurnFailed` 事件 payload 新增 `agent_name`**

先检查现有事件结构是否已携带；缺失则在 [`sebastian/protocol/events/`](../../../sebastian/protocol/events/) 补字段 + 在 orchestrator 发事件处填充。通知文案 "{agentName} 已完成" 依赖该字段。

## 落地改动

| # | 改动 | 位置 | 规模 |
|---|------|------|------|
| 1 | 新增 `AppStateReconciler`（Hilt Singleton，监听 `ProcessLifecycleOwner`） | `ui/mobile-android/app/.../data/sync/AppStateReconciler.kt` | 中 |
| 2 | 新增 `GlobalSseDispatcher`（单条 SSE → SharedFlow 分发） | `.../data/remote/GlobalSseDispatcher.kt` | 中 |
| 3 | `GlobalApprovalViewModel` 改为从 `GlobalSseDispatcher` 订阅 + 新增 `replaceAll(list)` | `.../viewmodel/GlobalApprovalViewModel.kt` | 小 |
| 4 | `ChatViewModel` 新增 `replaceAll(snapshot)` + 消费 `session_state` 字段驱动输入框 | `.../viewmodel/ChatViewModel.kt` | 小 |
| 5 | 新增 `NotificationDispatcher`（订阅 SseDispatcher + 前后台判断 + 事件 → 通知） | `.../notification/NotificationDispatcher.kt` | 中 |
| 6 | 新增 `NotificationChannels`（`approval` HIGH / `task_progress` DEFAULT，`SebastianApp.onCreate` 注册） | `.../notification/NotificationChannels.kt` | 小 |
| 7 | 通知权限请求 + Settings 页未授权状态行 + 跳系统设置 | `MainActivity.kt`、`.../ui/settings/` | 小 |
| 8 | Deep link 路由 `sebastian://session/{sessionId}` | `AndroidManifest.xml`、`MainActivity.kt`、`ui/navigation/Route.kt` | 小 |
| 9 | Repository 接线：`listApprovals()` / `fetchRecentSession(id)` 暴露给 Reconciler | `.../data/repository/ChatRepository.kt` 等 | 小 |
| 10 | 后端 `GET /sessions/{id}/recent` 响应加 `session_state` 字段 | `sebastian/gateway/routes/sessions.py` + schema | 小 |
| 11 | 后端 `TurnCompleted` / `TurnFailed` 事件 payload 加 `agent_name`（若缺） | `sebastian/protocol/events/` + orchestrator 发事件处 | 小 |
| 12 | 单测：Reconciler 幂等 merge / NotificationDispatcher 前后台判断 / Channel 注册 | `app/src/test/` + `tests/unit/` | 中 |

整体一个 PR 边界清晰，Android 侧约 10 个新/改文件，后端 2 处小补丁。

## 关键设计考量

### 为什么选 "REST 快照 + SSE 增量"，不依赖 Last-Event-ID 做条件 reconcile

澄清两层概念：

1. **SSE 协议层的 Last-Event-ID 断点续传**（OkHttp SSE 客户端自动带 header，服务端 500 条 ring buffer 据此补发）—— **保留不动**。这是 SSE 本身的能力，`SseClient.kt` 和 `sebastian/gateway/sse.py` 已实现，省流量、事件顺序天然正确，是白用的优化。
2. **客户端逻辑层用 Last-Event-ID 判断"是否需要拉快照"**（典型思路："精准续传成功就不 reconcile，失败才退化"）—— **不做**。

不做第 2 层的原因：Ring buffer 500 条在"手机锁屏一晚上"或"进程被杀 + 长时间离线"场景下必然失效，快照兜底必须存在。既然必须有，就不值得再维护一条基于 Last-Event-ID 的条件分支。无条件每次都 reconcile 一次，逻辑统一、天然容错。

两层协同：reconcile 拉回快照作为 baseline，SSE 带 Last-Event-ID 重连后服务端续传增量事件，客户端按主键幂等 merge。快照里的旧状态被增量事件覆盖没问题（upsert 最终一致）。每次回前台多一次 HTTP（数据量很小）换来统一心智模型，是划算的交易。

### 为什么拆 `GlobalSseDispatcher`

两个消费者（`GlobalApprovalViewModel` / `NotificationDispatcher`）生命周期不同：一个是 ViewModel（跟 Activity / Nav scope 走），一个是 Singleton（跟 Application 走）。塞进同一个类无法共存；开两条物理 SSE 连接浪费且事件顺序不可控。用一个 Singleton 持有唯一连接，通过 `SharedFlow` 向多个消费者广播，是最小复杂度的正确做法。

### 为什么前台一律不发通知

App 内有完整的应用内 UI（GlobalApprovalBanner、ChatScreen 流式渲染），再发系统通知是冗余打扰。统一规则"前台不发、后台才发"比"按 session / 事件类型细分"更好记忆，用户行为可预期。

### 为什么启动就请求通知权限

审批通知是"用户离开 App 时 agent 卡住"的唯一自救通道，价值极高，不应该懒加载。一次请求，拒绝了就在 Settings 页留入口让用户后悔时能进去。

### 为什么不在本 spec 做推送

推送选型（FCM vs 国内厂商 vs 聚合）是独立的生态/架构决策，需要单独讨论：

- FCM 要求用户能访问 Google 服务，国内真机不稳
- 厂商 SDK 碎片化严重（小米 / 华为 / OPPO / vivo / 魅族），接入成本高
- 聚合 SDK（JPush / 个推）引入第三方依赖，与 Sebastian 自托管定位冲突
- 自托管长连接 + 各厂商回调唤醒是技术上最干净但工作量最大的方案

这些都值得独立 spec 展开，不应该裹在状态恢复修复里被匆忙拍板。

### 为什么顺带做 `session_state` 字段

[multi-device-session-state-sync spec](2026-04-14-multi-device-session-state-sync-design.md) 明确提到"客户端重连时通过 `GET /api/v1/sessions/{id}/recent` 拉最新状态（需要在 response 里带上 state 字段）"。这正是本 spec Reconciler 要用的能力，一起做避免后续返工；但完整状态机（orchestrator 单点驱动、409 兜底）不做，那是另一个 spec 的正题。

## 未来演进（不在本 spec 范围）

- 跨进程推送（独立 spec，选型待定）
- 通知富交互（批准按钮、RemoteInput）
- 通知摘要合并（inbox style）
- Session 状态机完整落地（multi-device spec 的主体）
- 设备列表 / 踢下线（Phase 5 identity）
- Draft 同步

## Amendments

### 2026-04-16: Chat reconcile 实现路径调整

原设计（L74-78、落地改动 #4/#9/#10）让 `AppStateReconciler` 拉
`GET /api/v1/sessions/{id}/recent` → `ChatViewModel.replaceAll(snapshot)` +
消费 `session_state` 字段。落地时发现两个问题：

1. **幂等 upsert 主键不对齐**：spec L53-61 要求按 `messageId` 幂等 merge，
   但客户端流式消息 id 是 `UUID.randomUUID()`，REST 快照的 id 是后端没返
   `id` 字段时由 [`MessageDto.toDomain`](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/MessageDto.kt)
   合成 `"$sessionId-$index"`。两套 id space 不通，要落地真幂等 upsert
   需改后端 schema + 协议 + 客户端，超出本 spec 范围。首次实现
   （commit `ad20d23` 的 `replaceMessages`）退化为 `clear + replace`，
   与正在流的 SSE 增量竞态，已在 commit `3ec08e0` 撤回。
2. **能力重复**：[`ChatViewModel.switchSession`](../../../ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt)
   已实现"清空 → `getMessages` 全量 hydrate → SSE `Last-Event-ID` replay"
   的完整原语，比 `replaceAll(snapshot)` 更严格（不残留旧状态）。

**修订决策**：

- 不引入 `getSessionRecent` / `replaceMessages`（已撤回）
- 不在本 spec 加 `session_state` 字段。`switchSession` 已把 `composerState`
  归位 `IDLE_EMPTY`，若有进行中 turn，SSE replay 会立刻推 `TurnReceived`
  恢复 STREAMING；无进行中 turn，IDLE_EMPTY 本身正确
- `ChatViewModel.onAppStart()` 升级为 reconcile 入口：非 streaming/sending/cancelling
  且非离线时，调 `switchSession(activeSessionId)` 走完整 hydrate + replay
- `ChatScreen` 已有的 `LifecycleEventObserver` 作为触发点，无需再走
  `AppStateReconciler`（后者收敛为只做 approval reconcile）
- spec L25 "半截 assistant 气泡 / 输入框错乱" 场景由此方案覆盖
- `session_state` 字段 + 完整状态机留给
  [multi-device-session-state-sync spec](2026-04-14-multi-device-session-state-sync-design.md)
  的正题

**关于 spec L83-89 的双触发 + debounce**：

原 spec 要求 chat reconcile 同时挂 `ProcessLifecycleOwner.ON_START` + SSE
`onOpen`，带 150ms debounce。本方案 **只挂 ON_START**（复用 `ChatScreen` 已有
的 `LifecycleEventObserver`），不挂 SSE `onOpen`。理由：

- SSE 重连路径已由 `ChatViewModel.observeNetwork` +
  `startSseCollection(replayFromStart = needsReplay)` 兜底：网络恢复触发
  重连，`Last-Event-ID` 断点续传，`needsReplay` 判断是否需要回放——这本身
  就是 SSE 层的"reconcile"，不需要再叠一次 `switchSession`
- approval reconcile 仍按原设计走 `AppStateReconciler` 的双触发 + debounce，
  因为 approval 快照没有 `Last-Event-ID` 回放机制，必须显式拉全量
- debounce 本是为双触发去抖而设，单触发场景不需要

**守卫条件增补**：`IDLE_READY`（用户正在编辑未发送 / 发送失败后残留草稿）
也跳过 reconcile。原因：Composer 的文本存在 `ChatScreen` 的 local
`remember { mutableStateOf }`，ViewModel 不感知；若此时 reconcile 把
`composerState` 拨回 `IDLE_EMPTY`，会导致"输入框有字、发送按钮灰"的视觉
错位。等用户把草稿发出去或清空（回到 IDLE_EMPTY）再 reconcile。

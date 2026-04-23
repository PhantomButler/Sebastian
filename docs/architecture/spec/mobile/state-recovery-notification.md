---
version: "1.0"
last_updated: 2026-04-23
status: implemented
---

# App 状态恢复与本地通知

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 问题背景

Android App 存在两个相关问题：

### 问题 1：状态恢复机制缺失

`GlobalApprovalViewModel` 只在内存 `MutableStateFlow` 里维护 approval 队列。进程被系统回收后 ViewModel 丢失，重启后列表为空。后端已有恢复接口 `GET /api/v1/approvals`（返回 `status=pending` 记录），Android 侧 `ApiService.kt` 也已定义该端点，但无人调用。

同类问题存在于 `ChatViewModel`：用户切后台再回来可能看到半截 assistant 气泡或输入框状态错乱。

### 问题 2：App 离线无任何通知

无 `POST_NOTIFICATIONS` 权限、无 `FirebaseMessagingService`、无 device token 注册。用户离开 App 时，审批请求和任务完成事件都不会产生任何通知。

### 决策

修复问题 1 + 实现**本地通知**（`NotificationManager`，覆盖"App 在后台但进程存活"窗口）。跨进程推送（FCM / 厂商推送 / 聚合 SDK）留给独立 spec。

---

## 2. 非目标

- 不做跨进程推送（FCM / 厂商推送 / 聚合 SDK）
- 不做通知富交互（通知栏内批准按钮、`RemoteInput`）
- 不做通知摘要合并（inbox style 多条折叠）
- 不做 draft 同步 / 设备列表 / 踢下线
- 不做 session 状态机完整落地（属于 multi-device-session-state-sync spec）
- 不抽通用 reconcile 框架

---

## 3. 架构

### 3.1 核心原则：REST 快照 + SSE 增量（幂等 merge）

所有状态对象按稳定主键 upsert：

- REST 拉回的列表 → `replaceAll(list)` 整体覆盖
- SSE 来的增量事件 → `upsert(item)` 或 `removeById(id)`
- 主键：approvals 用 `approvalId`，messages 用 `messageId`，sessions 用 `sessionId`

两类操作合并顺序无所谓，天然幂等。

### 3.2 SSE 分发改造

当前 `GlobalApprovalViewModel` 独占全局 SSE 订阅。`NotificationDispatcher` 也要消费同一条流。引入 `GlobalSseDispatcher`：

```
OkHttp SSE /api/v1/stream
           │
           ▼
   GlobalSseDispatcher（Hilt Singleton）
     MutableSharedFlow<StreamEvent>（replay=0, extraBufferCapacity=64）
           │
           ├──→ GlobalApprovalViewModel.handleEvent()
           └──→ NotificationDispatcher.handleEvent()
```

- 单条物理连接、单次订阅，多个消费者通过 `SharedFlow` 分发
- `GlobalSseDispatcher` 持有 SSE 连接生命周期，不再由 `GlobalApprovalViewModel` 管理
- 连接启停绑定 `ProcessLifecycleOwner`（后台断开省电、前台重连）

> **实现文件**：`ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/GlobalSseDispatcher.kt`

---

## 4. 状态恢复流程

### 4.1 Approval Reconcile

```
ProcessLifecycleOwner.ON_START        GlobalSse.onOpen
         │                                   │
         └───────────┬───────────────────────┘
                     ▼
          AppStateReconciler.reconcile()
          （150ms debounce 合并两个触发源）
                     ▼
           GET /api/v1/approvals
                → GlobalApprovalViewModel.replaceAll(list)
```

**触发时机**：
- `ProcessLifecycleOwner` 的 `ON_START`（冷启动 + 回前台统一）
- 全局 SSE `onOpen` 回调（首次建连 + 重连）
- 150ms debounce 把近距离的两个触发点合并成一次请求

> **实现文件**：`ui/mobile-android/app/src/main/java/com/sebastian/android/data/sync/AppStateReconciler.kt`

### 4.2 Chat Reconcile（修正后方案）

> **实现差异**：原设计让 Reconciler 拉 `GET /sessions/{id}/recent` → `ChatViewModel.replaceAll(snapshot)`，落地时发现幂等 upsert 主键不对齐（客户端流式消息 id 是 `UUID.randomUUID()`，REST 快照 id 由 `MessageDto.toDomain` 合成），退化为 `clear + replace` 与 SSE 增量竞态，已撤回。

**实际实现**：
- 不引入 `getSessionRecent` / `replaceMessages`
- `ChatViewModel.onAppStart()` 升级为 reconcile 入口：非 streaming/sending/cancelling 且非离线时，调 `switchSession(activeSessionId)` 走完整 hydrate + replay
- `ChatScreen` 已有的 `LifecycleEventObserver`（`ON_START`）作为触发点，不经过 `AppStateReconciler`
- SSE 重连路径已由 `ChatViewModel.observeNetwork` + `startSseCollection(replayFromStart = needsReplay)` 兜底（`Last-Event-ID` 断点续传）

**守卫条件**：`IDLE_READY`（用户正在编辑未发送 / 发送失败后残留草稿）也跳过 reconcile，避免 `composerState` 被拨回 `IDLE_EMPTY` 导致"输入框有字、发送按钮灰"的视觉错位。

> **实现文件**：`ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` L616 `onAppStart()`

---

## 5. 本地通知分发

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
| `SessionCompleted` | `task_progress` | DEFAULT | `{agentName} 已完成` | 末条消息摘要（截断 120 字） | 跳转对应 session |
| `SessionFailed` | `task_progress` | DEFAULT | `{agentName} 执行失败` | error 摘要（截断 120 字） | 跳转对应 session |
| 其他 | — | — | — | — | 不通知 |

> **实现差异**：spec 原文用 `TurnCompleted` / `TurnFailed` 事件名，实际代码使用 `SessionCompleted` / `SessionFailed`，并携带 `agentType` 字段（非 `agent_name`）。

**通知去重**：`notificationId = event.primaryKey.hashCode()`，同一 approval 被 granted/denied 时 `NotificationManager.cancel(notificationId)` 撤回。

> **实现文件**：`ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationDispatcher.kt`

---

## 6. 通知 Channel

| Channel | 优先级 | 用途 |
|---------|-------|------|
| `approval` | HIGH | 审批 heads-up + 声音 + 震动 |
| `task_progress` | DEFAULT | 完成/失败通知，通知栏静默 |

Channel 初始化在 `SebastianApp.onCreate`（`createNotificationChannel` 幂等）。

> **实现文件**：`ui/mobile-android/app/src/main/java/com/sebastian/android/notification/NotificationChannels.kt`

---

## 7. 权限处理

- `AndroidManifest.xml` 声明 `<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />`
- `MainActivity.maybeRequestNotificationPermission()` 在 API 33+ 首次请求运行时权限
- 用户拒绝后不再主动弹；Settings 页留"通知权限未开启 [去设置]"入口

---

## 8. Deep Link 跳转

Deep link `sebastian://session/{sessionId}`：

- `AndroidManifest.xml` 的 `MainActivity` 加 `<intent-filter>` 声明 scheme
- `MainActivity.onCreate` 解析 `intent.data`，通过 `LaunchedEffect(startSessionId)` 导航
- `onNewIntent()` 处理 `singleTask` 通知点击（通过 `recreate()`）

---

## 9. 后端配合改动

### 9.1 `session_state` 字段

> **未实现**：`GET /api/v1/sessions/{id}/recent` 响应无 `session_state` 字段。Chat reconcile 实际绕过此字段（见 §4.2 修正方案）。完整状态机属于 multi-device-session-state-sync spec。

### 9.2 事件 payload agent_name

> **未实现**：`TurnCompleted` / `TurnFailed` 事件类型不存在于代码库。Android 使用 `SessionCompleted` / `SessionFailed` 携带 `agentType`。

---

## 10. 设计考量

### 为什么选 "REST 快照 + SSE 增量"

SSE 协议层的 Last-Event-ID 断点续传保留不动（OkHttp SSE 客户端自动带 header，服务端 500 条 ring buffer 据此补发）。客户端逻辑层不依赖 Last-Event-ID 判断是否需要拉快照——无条件每次都 reconcile，逻辑统一、天然容错。

### 为什么拆 `GlobalSseDispatcher`

两个消费者生命周期不同：ViewModel 跟 Activity/Nav scope 走，Singleton 跟 Application 走。一个 Singleton 持有唯一连接，通过 `SharedFlow` 广播，是最小复杂度的正确做法。

### 为什么前台不发通知

App 内有完整 UI（GlobalApprovalBanner、ChatScreen 流式渲染），系统通知冗余打扰。统一"前台不发、后台才发"。

---

*← [Mobile 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

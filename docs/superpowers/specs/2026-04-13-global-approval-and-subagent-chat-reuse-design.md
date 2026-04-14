# 全局审批系统 + SubAgent 对话页复用主对话三面板

> Date: 2026-04-13
> Status: Approved

## 背景

当前 Android 原生 App 存在两个问题：

1. **审批弹窗绑定页面**：审批事件只通过 per-session SSE 在当前对话页面接收，用户必须在产生审批的 session 页面才能看到弹窗。如果用户在其他页面（设置、agent 列表等），审批请求会被遗漏。
2. **SubAgent 对话页与主对话逻辑重复**：SubAgent 有独立的 `SessionListScreen` → `SessionDetailScreen` 两级页面，但核心逻辑（SSE 连接、消息渲染、Composer）与主对话 `ChatScreen` 完全相同，代码大量重复且容易不同步。

## 目标

- 任何页面都能弹出审批通知，全局覆盖
- SubAgent 对话页复用 `ChatScreen` 三面板布局，消除重复代码
- 后端 API 全部连通

## 设计

### 一、全局审批系统

#### 1.1 GlobalApprovalViewModel

新增 `GlobalApprovalViewModel`，App 单例级别（`@HiltViewModel`），职责：

- 连接全局 SSE（`GET /api/v1/stream`），接收所有 session 的审批事件
- 维护审批队列 `List<GlobalApproval>`
- 事件处理：
  - `approval.requested` → 入队
  - `approval.granted` / `approval.denied` → 出队
- 提供 `grantApproval(id)` / `denyApproval(id)` 方法调用后端 API
- 生命周期：`ON_START` 连接全局 SSE，`ON_STOP` 断开

数据模型：

```kotlin
data class GlobalApproval(
    val approvalId: String,
    val sessionId: String,
    val agentType: String,    // 用于判断导航目标
    val agentName: String,    // 用于 banner 显示
    val description: String,
)
```

#### 1.1.1 后端改动：approval 事件补充 agent_type

当前后端 `conversation.py` 发出的 `USER_APPROVAL_REQUESTED` 事件 data 只包含 `approval_id`、`task_id`、`session_id`、`tool_name`、`tool_input`、`reason`，**缺少 `agent_type`**。

需要在 `request_approval` 方法中查询 session 的 `agent_type`（session 记录已有此字段），补充到事件 data 中：

```python
# conversation.py — request_approval 中的事件 data 补充
data={
    "approval_id": approval_id,
    "task_id": task_id,
    "session_id": session_id,
    "agent_type": agent_type,   # 新增
    "tool_name": tool_name,
    "tool_input": tool_input,
    "reason": reason,
},
```

Android 端 `StreamEvent.ApprovalRequested` 同步新增 `agentType` 字段。

#### 1.2 GlobalApprovalBanner Composable

放在 `MainActivity` 的 `SebastianNavHost` 外层，用 `Box` 叠加在 NavHost 之上（z-index），不推挤页面布局。

布局：
- 悬浮在页面顶部
- 两行：第一行显示 agent 名称 + 审批描述内容，第二行显示拒绝（红色实心，左侧）和允许（绿色实心，右侧）按钮
- 按钮间距 16dp，min-width 80dp，防误点
- 多条审批排队时只显示第一条，处理完自动显示下一条
- 带"查看详情"文字按钮，点击导航到对应 session

查看详情导航逻辑：
- 如果 `agentType == "sebastian"`（主管家）→ 在 `ChatScreen` 中 `switchSession(sessionId)`
- 如果 `agentType != "sebastian"`（SubAgent）→ 导航到 `Route.AgentChat(agentType)`，然后 `switchSession(sessionId)`

#### 1.3 移除各页面审批处理

- `ChatViewModel`：删除 `ApprovalRequested/Granted/Denied` 事件处理，删除 `ChatUiState.pendingApprovals` 字段，删除 `grantApproval/denyApproval` 方法
- `ChatScreen`：删除 `ApprovalDialog` 调用
- `SessionDetailScreen`：即将删除，无需处理

### 二、SubAgent 对话页复用三面板

#### 2.1 路由变更

```kotlin
// 新增
data class AgentChat(val agentId: String, val agentName: String) : Route()

// 删除
// data class AgentSessions(val agentId: String) : Route()  — 删除
// data class SessionDetail(val sessionId: String) : Route() — 删除
```

`agentName` 由 `AgentListScreen` 在导航时传入，避免 `ChatScreen` 再额外请求。

导航流程：
```
ChatScreen(主对话)
  → SessionPanel 点 "Sub-Agents"
    → AgentListScreen
      → 点击 agent
        → ChatScreen(agentId = "code_agent")
          → 返回键 → AgentListScreen
```

#### 2.2 ChatScreen 参数化

`ChatScreen` 新增参数 `agentId: String? = null`。

差异行为：

| 行为 | agentId == null（主对话） | agentId != null（SubAgent） |
|------|--------------------------|----------------------------|
| TopAppBar 标题 | "Sebastian" | agent 名称 |
| TopAppBar 左侧 | 汉堡菜单（展开 SessionPanel） | 返回箭头（popBackStack） |
| 左栏 SessionPanel | 完整面板（功能区 + 主 session 列表） | 精简面板（仅该 agent 的 session 列表） |
| session 数据源 | `SessionViewModel.loadSessions()` | `SessionViewModel.loadAgentSessions(agentId)` |
| 发送消息 | `sendMessage(text)` → `POST /api/v1/turns` | `sendAgentMessage(agentId, text)` |
| 新建对话 | `newSession()` | `newSession()`（同样清空 activeSessionId） |

#### 2.3 SessionPanel 精简模式

`SessionPanel` 新增参数：
- `agentId: String? = null`
- `agentName: String? = null`
- `onNavigateToSettings: () -> Unit = {}`（精简模式不传）
- `onNavigateToSubAgents: () -> Unit = {}`（精简模式不传）

精简模式（`agentId != null`）：
- 标题显示 agent 名称（替代 "Sebastian"）
- 去掉功能区（Sub-Agents / 设置 / 系统总览）
- 只显示该 agent 的历史 session 列表 + 新对话按钮

#### 2.4 ChatViewModel 改动

新增 `sendAgentMessage(agentId: String, text: String)`：
- `activeSessionId == null`（新对话）：调 `sessionRepository.createAgentSession(agentId, text)` 获取 `sessionId`，设置 `activeSessionId`，启动 SSE（`replayFromStart = true`），刷新 session 列表
- `activeSessionId != null`（已有 session）：调 `chatRepository.sendSessionTurn(sessionId, text)`，若 SSE 断开则重连

#### 2.5 SessionViewModel 改动

新增 agent session 感知：
- `loadAgentSessions(agentId)` 方法已存在于 `SubAgentViewModel`，需迁移到 `SessionViewModel`（或让 `SessionViewModel` 也支持按 agentId 加载）
- 结果写入同一个 `sessionsFlow`，`ChatScreen` 无需关心数据来源差异

### 三、文件增删

| 操作 | 文件 |
|------|------|
| 新增 | `viewmodel/GlobalApprovalViewModel.kt` |
| 新增 | `ui/common/GlobalApprovalBanner.kt` |
| 修改 | `MainActivity.kt` — NavHost 外包 GlobalApprovalBanner，路由表更新 |
| 修改 | `Route.kt` — 新增 AgentChat，删除 AgentSessions / SessionDetail |
| 修改 | `ChatScreen.kt` — 接收 agentId，条件渲染 TopAppBar 和 SessionPanel |
| 修改 | `SessionPanel.kt` — 新增精简模式 |
| 修改 | `ChatViewModel.kt` — 新增 sendAgentMessage，移除审批处理 |
| 修改 | `SessionViewModel.kt` — 新增 loadAgentSessions |
| 修改 | `AgentListScreen.kt` — 导航目标改为 Route.AgentChat |
| 删除 | `SessionListScreen.kt` |
| 删除 | `SessionDetailScreen.kt` |

### 四、后端 API 映射

| 功能 | API | 调用方 |
|------|-----|--------|
| 全局事件流 | `GET /api/v1/stream` | GlobalApprovalViewModel |
| 审批同意 | `POST /api/v1/approvals/{id}/grant` | GlobalApprovalViewModel |
| 审批拒绝 | `POST /api/v1/approvals/{id}/deny` | GlobalApprovalViewModel |
| 主对话发送 | `POST /api/v1/turns` | ChatViewModel.sendMessage |
| SubAgent 创建 session | `POST /api/v1/agents/{agentType}/sessions` | ChatViewModel.sendAgentMessage |
| SubAgent 发送 turn | `POST /api/v1/sessions/{sessionId}/turns` | ChatViewModel.sendAgentMessage |
| SubAgent session 列表 | `GET /api/v1/agents/{agentType}/sessions` | SessionViewModel.loadAgentSessions |
| Session 消息历史 | `GET /api/v1/sessions/{sessionId}` | ChatViewModel.switchSession |
| Per-session SSE | `GET /api/v1/sessions/{sessionId}/stream` | ChatViewModel.startSseCollection |

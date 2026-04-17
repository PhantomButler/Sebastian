---
version: "1.0"
last_updated: 2026-04-16
status: implemented
---

# 全局审批系统 + SubAgent 对话页复用

*← [Mobile Spec 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

### 1.1 审批弹窗绑定页面问题

审批事件原本只通过 per-session SSE 在当前对话页面接收，用户必须在产生审批的 session 页面才能看到弹窗。如果用户在其他页面（设置、agent 列表等），审批请求会被遗漏。

### 1.2 SubAgent 对话页代码重复

SubAgent 有独立的 `SessionListScreen` → `SessionDetailScreen` 两级页面，但核心逻辑（SSE 连接、消息渲染、Composer）与主对话 `ChatScreen` 完全相同，代码大量重复且容易不同步。

---

## 2. 全局审批系统

### 2.1 GlobalApprovalViewModel

App 单例级别（`@HiltViewModel`），职责：

- 通过 `GlobalSseDispatcher` 订阅全局 SSE（`GET /api/v1/stream`），接收所有 session 的审批事件
- 维护审批队列 `List<GlobalApproval>`
- 事件处理：
  - `approval.requested` → 入队
  - `approval.granted` / `approval.denied` → 出队
- REST 对账：首次加载时调用 `GET /api/v1/approvals` 获取 pending 状态的审批，`replaceAll` 同步队列
- 提供 `grantApproval(id)` / `denyApproval(id)` 方法调用后端 API

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

### 2.2 后端：approval 事件包含 agent_type

后端 `conversation.py` 的 `request_approval` 方法在事件 data 中包含 `agent_type` 字段：

```python
data={
    "approval_id": approval_id,
    "task_id": task_id,
    "session_id": session_id,
    "agent_type": agent_type,
    "tool_name": tool_name,
    "tool_input": tool_input,
    "reason": reason,
},
```

### 2.3 GlobalApprovalBanner

悬浮在 `MainActivity` 的 NavHost 之上（z-index 叠加），不推挤页面布局。

特性：
- 玻璃拟态风格卡片
- 显示 agent 类型、工具摘要、审批原因
- 拒绝（红色）/ 允许（绿色）按钮
- 多条审批排队时只显示第一条，处理完自动显示下一条
- "查看详情"按钮：点击导航到对应 session

查看详情导航逻辑：
- 如果 `agentType == "sebastian"`（主管家）→ 在 `ChatScreen` 中 `switchSession(sessionId)`
- 如果 `agentType != "sebastian"`（SubAgent）→ 导航到 `Route.AgentChat(agentType)`，然后 `switchSession(sessionId)`

### 2.4 审批处理迁移

审批逻辑已从 `ChatViewModel` 移至 `GlobalApprovalViewModel`：
- `ChatViewModel`：无审批相关代码
- `ChatScreen`：无 `ApprovalDialog` 调用
- `SessionDetailScreen`：已删除

---

## 3. SubAgent 对话页复用主对话页

### 3.1 路由变更

```kotlin
// 新增
data class AgentChat(
    val agentId: String,
    val agentName: String,
    val sessionId: String? = null,
) : Route()

// 已删除：AgentSessions、SessionDetail
```

`agentName` 由 `AgentListScreen` 在导航时传入。

导航流程：
```
ChatScreen(主对话)
  → SessionPanel 点 "Sub-Agents"
    → AgentListScreen
      → 点击 agent
        → ChatScreen(agentId = "code_agent")
          → 返回键 → AgentListScreen
```

### 3.2 ChatScreen 参数化

`ChatScreen` 接受 `agentId: String? = null` 和 `agentName: String? = null`。

差异行为：

| 行为 | agentId == null（主对话） | agentId != null（SubAgent） |
|------|--------------------------|----------------------------|
| TopAppBar 标题 | "Sebastian" | agent 名称 |
| TopAppBar 左侧 | 汉堡菜单（展开 SessionPanel） | 返回箭头（popBackStack） |
| 左栏 SessionPanel | 完整面板（功能区 + 主 session 列表） | 精简面板（仅该 agent 的 session 列表） |
| session 数据源 | `SessionViewModel.loadSessions()` | `SessionViewModel.loadAgentSessions(agentId)` |
| 发送消息 | `sendMessage(text)` | `sendAgentMessage(agentId, text)` |
| 新建对话 | `newSession()` | `newSession()`（同样清空 activeSessionId） |

### 3.3 SessionPanel 精简模式

`SessionPanel` 新增 `agentId` / `agentName` 参数。精简模式（`agentId != null`）：
- 标题显示 agent 名称
- 去掉功能区（Sub-Agents / 设置 / 系统总览）
- 只显示该 agent 的历史 session 列表 + 新对话按钮

### 3.4 ChatViewModel 改动

新增 `sendAgentMessage(agentId: String, text: String)`：
- `activeSessionId == null`（新对话）：调 `sessionRepository.createAgentSession(agentId, text)` 获取 `sessionId`，设置 `activeSessionId`，启动 SSE，刷新 session 列表
- `activeSessionId != null`（已有 session）：调 `chatRepository.sendSessionTurn(sessionId, text)`

---

## 4. 文件增删

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

---

## 5. 后端 API 映射

| 功能 | API | 调用方 |
|------|-----|--------|
| 全局事件流 | `GET /api/v1/stream` | GlobalSseDispatcher |
| 审批列表 | `GET /api/v1/approvals` | GlobalApprovalViewModel |
| 审批同意 | `POST /api/v1/approvals/{id}/grant` | GlobalApprovalViewModel |
| 审批拒绝 | `POST /api/v1/approvals/{id}/deny` | GlobalApprovalViewModel |
| 主对话发送 | `POST /api/v1/turns` | ChatViewModel.sendMessage |
| SubAgent 创建 session | `POST /api/v1/agents/{agentType}/sessions` | ChatViewModel.sendAgentMessage |
| SubAgent 发送 turn | `POST /api/v1/sessions/{sessionId}/turns` | ChatViewModel.sendAgentMessage |
| SubAgent session 列表 | `GET /api/v1/agents/{agentType}/sessions` | SessionViewModel.loadAgentSessions |
| Session 消息历史 | `GET /api/v1/sessions/{sessionId}` | ChatViewModel.switchSession |
| Per-session SSE | `GET /api/v1/sessions/{sessionId}/stream` | ChatViewModel.startSseCollection |

---

*← [Mobile Spec 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

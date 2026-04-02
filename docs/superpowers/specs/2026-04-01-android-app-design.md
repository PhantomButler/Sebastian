# Sebastian Android App 设计文档（Phase 1）

**版本**：v0.1
**日期**：2026-04-01
**状态**：待实施

---

## 1. 定位与范围

Sebastian Android App 是 Phase 1 的主要交互入口。定位为**纯展示 + 控制层**：

- 业务数据（消息历史、Task 状态、Session 记录）全部持久化在服务端
- 本地只存 `serverUrl`、`jwtToken`、Session 侧边栏索引（最多 20 条）
- App 是服务端状态的实时镜像，不是数据源

这一原则影响服务端设计：**服务端必须完整持久化所有 Session 消息和 Task 状态**，供 App 随时拉取同步。

---

## 2. 技术栈

| 项目 | 选型 |
|------|------|
| 框架 | Expo managed workflow |
| 路由导航 | Expo Router（文件系统路由） |
| UI 状态管理 | Zustand |
| 服务端数据 | React Query（缓存、loading、重试） |
| 实时推送（前台） | SSE（`GET /api/v1/stream`） |
| 实时推送（后台） | FCM（`expo-notifications`） |
| HTTP 客户端 | axios |
| 手势 | react-native-gesture-handler |
| 本地安全存储 | expo-secure-store |

---

## 3. 导航结构

底部 Tab 三项，顺序固定：

```
[ Sebastian ]  [ SubAgents ]  [ 设置 ]
      左             中           右
       ↑
    默认启动页
```

---

## 4. 项目目录结构

```
ui/mobile/
├── app/
│   ├── _layout.tsx                 # 底部 Tab 导航配置
│   └── (tabs)/
│       ├── chat/
│       │   ├── _layout.tsx
│       │   └── index.tsx           # Sebastian 主对话页
│       ├── subagents/
│       │   ├── _layout.tsx
│       │   └── index.tsx           # Sub-Agent 列表页
│       └── settings/
│           ├── _layout.tsx
│           └── index.tsx           # 设置页
│   └── subagents/
│       ├── [agentId].tsx           # 某个 Sub-Agent 的会话列表页
│       └── session/
│           └── [id].tsx            # 某个会话的详情页
├── src/
│   ├── api/
│   │   ├── client.ts               # axios 实例（动态读 serverUrl）
│   │   ├── auth.ts                 # 登录、token 刷新
│   │   ├── turns.ts                # POST /turns, GET /turns/:sessionId
│   │   ├── tasks.ts                # Task CRUD
│   │   ├── approvals.ts            # 审批 API
│   │   └── sse.ts                  # SSE 连接封装
│   ├── store/
│   │   ├── session.ts              # Session 索引、当前 Session、草稿逻辑
│   │   ├── tasks.ts                # Task 列表、Sub-Agent 状态
│   │   └── settings.ts             # serverUrl、jwtToken、LLM provider
│   ├── hooks/
│   │   ├── useSessions.ts          # React Query: Session 列表
│   │   ├── useMessages.ts          # React Query: 消息历史
│   │   ├── useTasks.ts             # React Query: Task 列表
│   │   └── useSSE.ts               # SSE → Zustand 桥接
│   └── components/
│       ├── common/
│       │   ├── Sidebar.tsx         # 手势侧边栏容器（仅对话页使用）
│       │   ├── EmptyState.tsx      # 空状态占位
│       │   └── StatusBadge.tsx     # 任务状态标签
│       ├── chat/
│       │   ├── ChatSidebar.tsx     # 历史 Session 列表 + 新对话按钮
│       │   ├── MessageList.tsx     # 消息内容区
│       │   ├── MessageBubble.tsx   # 单条消息气泡
│       │   ├── StreamingBubble.tsx # 流式输出气泡
│       │   └── MessageInput.tsx    # 悬浮输入框
│       ├── subagents/
│       │   ├── AgentList.tsx       # Sub-Agent 列表
│       │   ├── SessionList.tsx     # 某个 Sub-Agent 的会话列表
│       │   └── AgentStatusBadge.tsx # Agent 状态标签
│       └── settings/
│           ├── ServerConfig.tsx    # Server URL + 连接测试
│           ├── LLMProviderConfig.tsx  # LLM Provider + API Key
│           └── MemorySection.tsx   # 占位（Memory 管理，Phase 后续实现）
├── app.json
└── package.json
```

---

## 5. 页面设计

### 5.1 对话页

- 内容区全屏（顶到底），底部留 padding 避免被输入框遮挡
- 输入框悬浮在内容区上层（absolute bottom）
- 页面标题与底部 Tab 文案统一为 `Sebastian`
- 左滑手势拉出 `ChatSidebar`

**ChatSidebar**：
- 显示最近 20 条 Session（本地索引，仅存 id/title/时间）
- 超出 20 条自动删除最旧索引（服务端数据不删）
- "新对话"按钮仅在当前有实际内容的 Session 时显示：
  - 点击 → 创建草稿 Session（`draftSession=true`，未持久化），按钮随即消失
- 无 Session 或当前是草稿时：不显示"新对话"按钮

**Session 生命周期**：
```
无 Session：空白页 → 发消息 → 自动创建并持久化 Session
有 Session：点"新对话" → 草稿（按钮消失）→ 发消息 → 持久化
```

### 5.2 SubAgents 页

`SubAgents` 页不再镜像对话页，而是作为 Sub-Agent 浏览入口：

- 顶部展示固定标题 `Sub-Agents`
- 主区域直接显示 Sub-Agent 列表，不使用侧边栏
- 点击某个 Sub-Agent → 进入该 Agent 的二级页面，查看它的 Session 列表
- 再点击某个 Session → 进入三级详情页，查看消息与任务

**二级页面（某个 Sub-Agent 的 Session 列表）**：
- 顶部返回按钮 + Agent 名称
- 主区域显示该 Agent 的 Session 列表
- 无真实数据时允许展示 mock 数据，方便验证导航链路

**三级页面（Session 详情）**：
- 顶部返回按钮 + Session 标题
- `消息 / 任务` 双 tab 切换
- 底部保留输入框，可继续向该 Session 发送内容

**组件复用**：`SessionList`、`MessageList`、`MessageInput`、`SessionDetailView`
**数据流区别**：`Sebastian` 页连接主会话消息流；`SubAgents` 页只负责 Agent → Session → 详情的导航入口

### 5.4 输入框状态（Sebastian 页 & Session 详情页通用）

`MessageInput` 有两种状态，由 `isWorking` prop 控制：

| 状态 | 触发条件 | 发送按钮 | 回车键 | 点击发送按钮行为 |
|------|----------|----------|--------|-----------------|
| 空闲 | 无进行中任务/输出 | 发送图标 | 发送消息 | 发送消息 |
| 工作中 | Sebastian 思考/输出/安排 Sub-Agent 中；或 Sub-Agent 正在执行任务中 | 停止图标 | 无效 | 发送停止指令（`POST /api/v1/tasks/{id}/cancel` 或 SSE 中断） |

- 工作中状态下键盘回车键不触发发送
- 停止按钮点击后立即切换回空闲状态（乐观更新），等待服务端确认

### 5.3 设置页

- **Server URL**：手动填写，填写后自动测试连通性（`GET /api/v1/health`）
- **登录**：填写密码 → `POST /api/v1/auth/login` → JWT 存入 SecureStore
- **LLM Provider**：选择 provider（Anthropic / OpenAI）+ 填写 API Key
- **Memory 管理**：占位区块，显示"即将推出"

---

## 6. 数据流

```
REST 请求  →  React Query（缓存、loading、重试）→ 组件
SSE 事件   →  useSSE hook → Zustand store → 组件
UI 状态    →  Zustand store → 组件
```

**Zustand store 职责**（仅 UI 状态 + SSE 增量）：

```
session.ts
├── sessionIndex: SessionMeta[]   # 本地索引，最多 20 条
├── currentSessionId: string | null
├── draftSession: boolean
└── streamingMessage: string      # 当前流式输出内容

agents.ts
├── activeAgents: Agent[]         # 正在工作的 Sub-Agent 列表
├── currentAgentId: string | null # 当前查看的 Agent
└── streamingOutput: string       # 当前 Agent 流式输出内容

settings.ts
├── serverUrl: string
├── jwtToken: string | null       # 持久化到 SecureStore
└── llmProvider: { name, apiKey }
```

**React Query 职责**：Session 消息历史、Task 列表、Agent 列表的拉取与缓存。

---

## 7. SSE 与后台策略

- App **前台**：维持 `GET /api/v1/stream` SSE 长连接
  - `turn.delta` 事件 → 追加到 `streamingMessage`（流式显示）
  - `task.*` 事件 → patch `tasks` store
  - `approval.required` 事件 → 弹审批 Modal
- App **进入后台**：断开 SSE 连接（节省资源）
- App **回到前台**：重连 SSE + React Query 刷新 Task 列表 + 当前 Session 消息
  - 断开期间的 delta 流中断：回前台后拉取完整消息补齐
- **后台通知**：依赖 FCM 推送（见第 8 节）

---

## 8. FCM 推送

App 启动后通过 `expo-notifications` 获取 FCM token，上报至服务端：

```
POST /api/v1/devices
{ "fcm_token": "...", "platform": "android" }
```

**服务端需存储 FCM token**（与用户绑定），用于后台推送。

推送场景：

| 事件 | 通知内容 | 点击行为 |
|------|----------|----------|
| `approval.required` | "需要你的决策：{描述}" | 唤起 App → 弹审批 Modal |
| `task.completed` | "任务完成：{goal}" | 唤起 App → 跳转任务详情 |
| `task.failed` | "任务失败：{goal}" | 唤起 App → 跳转任务详情 |

---

## 9. 认证流程

1. 设置页填写 Server URL + 密码 → `POST /api/v1/auth/login` → JWT
2. JWT 存入 `expo-secure-store`
3. axios 实例拦截器自动附加 `Authorization: Bearer <token>`
4. 收到 401 → 清除 token → 跳转设置页重新登录

---

## 10. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 未配置 Server URL | `Sebastian` 页或 `SubAgents` 页显示引导，跳转设置页 |
| JWT 过期（401） | 清除 token，跳转设置页 |
| SSE 断连 | 指数退避自动重连（最多 3 次），失败显示离线 banner |
| 发消息失败 | 输入框保留内容，Toast 提示，用户手动重试 |

---

## 11. 服务端配合要求（Phase 1 新增）

以下为本文档识别出的服务端需补充实现项：

- `POST /api/v1/devices`：注册 FCM token（存储与用户绑定）
- Session 消息历史完整持久化（App 回前台后可拉取补齐）
- FCM 推送发送逻辑（approval、task 完成/失败事件触发）
- `GET /api/v1/turns/{session_id}` 支持分页
- `GET /api/v1/agents`：返回 Sub-Agent 列表，供 `SubAgents` 页展示
- `GET /api/v1/agents/{id}/sessions`：返回某个 Sub-Agent 的 Session 列表
- `GET /api/v1/agents/{id}/sessions/{session_id}`：返回某个 Session 的详情与消息历史

---

*本文档由脑暴会话生成并经用户确认。*

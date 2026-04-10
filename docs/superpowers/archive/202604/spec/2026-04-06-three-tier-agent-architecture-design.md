# 三层 Agent 架构设计

**版本**：v1.0
**日期**：2026-04-06
**状态**：设计完成，待实施
**前置依赖**：替代 `2026-04-01-sebastian-architecture-design.md` 中 §2.3 Agent 继承模型、§2.4 A2A 协议、§5 Sub-Agent 扩展规范相关内容

---

## 1. 背景与动机

现有架构中，Sub-Agent 采用 AgentPool + worker 多开模型：每个 agent_type 有固定数量的 worker 实例（如 `code_01`/`code_02`/`code_03`），通过 A2A Dispatcher 队列分发任务。存在以下问题：

1. **agent_id/worker 是多余抽象**：session_id 已能唯一定位工作记录，worker 身份无实际用途
2. **用户无法直接和 Sub-Agent 对话**：所有交互都经 Sebastian 代答（`intervene`），Sub-Agent 不能用自己的人格和能力回复
3. **Sub-Agent 无法拆解复杂任务**：缺少向下分派的能力，只能自己处理所有工作
4. **A2A Dispatcher 同步阻塞**：Sebastian 委派后等待 future 返回，无法"安排后不管"

---

## 2. 三层模型

用城堡比喻：用户是城堡主人，Sebastian 是总管家，第二层是各部门组长，第三层是组长安排的组员。

```
用户（城堡主人）
│
├── Sebastian（总管家，depth=1）
│     ├── 理解主人意图，分解目标，委派组长
│     └── 工具：delegate_to_agent, check_sub_agents, inspect_session
│
├── 铁匠（Code Agent 组长，depth=2）
│     ├── 简单任务自己干，复杂任务安排组员
│     ├── 工具：spawn_sub_agent, check_sub_agents, inspect_session + 领域工具
│     └── 组员（depth=3，最多 5 个同时工作）
│           ├── 铁匠组员 A — "实现用户认证模块"
│           ├── 铁匠组员 B — "编写单元测试"
│           └── ...
│
├── 骑士团长（Stock Agent 组长，depth=2）
│     └── ...
└── ...
```

### 2.1 层级规则

| 规则 | 说明 |
|------|------|
| 最大深度 | 3 层（Sebastian → 组长 → 组员） |
| 组长数量 | 由 `agents/` 目录下注册的 manifest.toml 决定，无上限 |
| 组员并发上限 | 每个组长可配置 `max_children`，默认 5 |
| 组员类型 | 与组长相同的 agent class，共享 persona 和 tools，scope 限定在子任务 |
| 通用组员 | 后续可创建通用类型 agent，组长需要安排非自身类型的第三级时使用通用 agent + 提示词 |

### 2.2 用户对话权限

| 操作 | Sebastian | 组长 (depth=2) | 组员 (depth=3) |
|------|-----------|---------------|---------------|
| 用户创建新对话 | ✓ | ✓ | ✗ |
| 用户发消息干预已有 session | ✓ | ✓ | ✓ |
| 出现在 App 列表中 | 主对话页侧边栏 | 组长 session 列表 | 组长 session 列表（带标记） |

### 2.3 两条信息线

**指挥链路**：用户 → Sebastian → 组长 → 组员（双向，自上而下委派 + 自下而上汇报）

**直接沟通**：用户 → 组长 → 组员（跳过 Sebastian，用户直接和组长开新对话或干预组员 session）

---

## 3. 数据模型变更

### 3.1 Agent 模型（替代 AgentPool/worker/agent_id）

**删除**：`AgentPool`、`A2ADispatcher`、`worker_id`、`agent_id` 概念全部移除。

每个 agent 类型是单例，通过 manifest.toml 注册：

```toml
# sebastian/agents/code/manifest.toml
[agent]
name = "铁匠"                # 对用户和 Sebastian 的呈现名，非技术名
class_name = "CodeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5              # 可同时运行的第三级 session 数
```

Agent 运行时属性：

- `agent_type: str` — 唯一标识（目录名，如 `"code"`）
- `name: str` — 呈现名（如 "铁匠"），暴露给 Sebastian 和用户
- `persona / system_prompt / tools / skills` — 自有能力，每个 agent 用自己的人格回复
- `max_children: int` — 该组长可同时运行的组员 session 上限

Sebastian 本身也是 agent（depth=1），拥有 `delegate_to_agent` 工具。组长是 depth=2，拥有 `spawn_sub_agent` 工具。

运行时维护 `state.agent_instances: dict[str, BaseAgent]`（每个 agent_type 一个实例），替代现有的 `state.agent_pools`。

### 3.2 Session 模型变更

```python
class Session:
    id: str
    agent_type: str                  # 归属哪个 agent
    title: str
    status: SessionStatus            # active / idle / completed / failed / stalled / cancelled
    depth: int                       # 1=Sebastian, 2=组长, 3=组员
    parent_session_id: str | None    # 组员 session 指向创建它的组长 session
    last_activity_at: datetime       # 最近一次 stream 事件时间
    created_at: datetime
    updated_at: datetime
    task_count: int
    active_task_count: int
```

- `depth` 决定 UI 行为：depth≤2 可新建对话，depth=3 只能干预
- `parent_session_id` 用于追溯关系和 UI 标记区分
- `last_activity_at` 用于 stalled 检测
- index.json 同步增加 `depth`、`parent_session_id`、`last_activity_at` 字段

### 3.3 Session 状态机

```
active → completed     （任务正常完成，自动转换）
active → failed        （执行出错，自动转换）
active → idle          （等待输入 / 暂停）
active → stalled       （无活动超过阈值，watchdog 标记）
active → cancelled     （上级或用户主动取消）
idle   → active        （收到新消息继续处理）
stalled → active       （收到干预消息后恢复）
stalled → cancelled    （上级或用户取消）
```

`max_children` 计数：只统计 `status=active` 的 depth=3 session。`completed`/`failed`/`cancelled` 不占位，`stalled` 仍占位。

---

## 4. 对话通道与 LLM 路由

### 4.1 核心变更：每个 agent 用自己的 persona 回复

| 场景 | 触发方式 | 谁回复 |
|------|---------|--------|
| 用户 ↔ Sebastian | 主对话页发消息 | Sebastian（不变） |
| 用户 ↔ 组长 | 组长 session 列表新建对话 / 点进已有 session | 组长自己（用自己的 persona + tools） |
| 用户 ↔ 组员 | 点进组员 session 发消息干预 | 组员（同类型 agent，scope 在子任务） |

用户向任意 session 发消息时：
1. 根据 session 的 `agent_type` 找到 `state.agent_instances[agent_type]`
2. 用该 agent 的 `system_prompt` + session 的历史消息 → 调 LLM
3. 响应写回该 session

不再经过 Sebastian 中转，不再有 `intervene` 的"代答"语义。

### 4.2 Sebastian 委派（异步）

Sebastian 调用 `delegate_to_agent` 工具：
1. 创建一个 `depth=2` 的 session
2. `session_store.create_session` + `index_store.upsert`
3. `asyncio.create_task` 触发组长 agent 异步处理
4. 立即返回 `ToolResult(ok=True, output="已安排{agent_name}处理：{goal}")`
5. 组长完成后通过 event bus 发事件 → 前端 tool call 状态从运行中变已完成

**删除同步等待**：不再使用 A2A Dispatcher 的 queue + future 机制。

### 4.3 组长分派组员（异步）

组长在处理复杂任务时调用 `spawn_sub_agent` 工具：
1. 检查当前 agent 活跃的 depth=3 session 数 < `max_children`
2. 超限时返回 `ToolResult(ok=False, error="当前已有{n}个组员在工作，已达上限{max}")`
3. 创建 `Session(agent_type=self.agent_type, depth=3, parent_session_id=当前session)`
4. `session_store.create_session` + `index_store.upsert`
5. `asyncio.create_task` 触发组员异步处理
6. 立即返回 `ToolResult(ok=True, output="已安排组员处理：{goal}")`

组员用和组长相同的 agent 实例（单例）。persona 和 system prompt 与组长完全一致，但 session 的初始消息包含子任务上下文（goal + context），以此区分工作范围。

### 4.4 Session 自动完成

agent 异步任务执行完毕时（LLM 调用链结束，无更多 tool call），自动更新 session 状态：

```python
async def _run_agent_session(agent, session, goal):
    try:
        await agent.run_streaming(goal, session.id)
        session.status = "completed"
    except Exception:
        session.status = "failed"
    finally:
        session.updated_at = now()
        await session_store.update_session(session)
        await index_store.upsert(session)
        await event_bus.publish(SESSION_COMPLETED / SESSION_FAILED 事件)
```

---

## 5. 工具设计

所有工具统一放在 `capabilities/tools/` 下，每个工具一个独立子目录。不再在 `orchestrator/tools/` 或其他位置放置工具。

```
capabilities/tools/
├── _loader.py                    # 启动时自动扫描注册
├── delegate_to_agent/            # Sebastian 专用
│   └── tool.py
├── spawn_sub_agent/              # 组长专用
│   └── tool.py
├── check_sub_agents/             # Sebastian 和组长共用
│   └── tool.py
├── inspect_session/              # Sebastian 和组长共用
│   └── tool.py
├── bash_execute/                 # 通用基础工具
│   └── tool.py
├── file_read/
│   └── tool.py
├── file_write/
│   └── tool.py
├── web_search/
│   └── tool.py
└── ...
```

### 5.1 delegate_to_agent（Sebastian 专用）

文件：`capabilities/tools/delegate_to_agent/tool.py`

```python
@tool(name="delegate_to_agent")
async def delegate_to_agent(agent_type: str, goal: str, context: str = "") -> ToolResult:
    # 1. 验证 agent_type 已注册
    # 2. 创建 depth=2 session
    # 3. asyncio.create_task 触发 agent 执行
    # 4. 返回 "已安排{agent_name}处理：{goal}"
```

### 5.2 spawn_sub_agent（组长专用）

文件：`capabilities/tools/spawn_sub_agent/tool.py`

```python
@tool(name="spawn_sub_agent")
async def spawn_sub_agent(goal: str, context: str = "") -> ToolResult:
    # 1. 检查 active depth=3 session 数 < max_children
    # 2. 创建 depth=3 session，parent_session_id=当前 session
    # 3. asyncio.create_task 触发组员执行
    # 4. 返回 "已安排组员处理：{goal}"
```

### 5.3 check_sub_agents（Sebastian 和组长共用）

文件：`capabilities/tools/check_sub_agents/tool.py`

```python
@tool(name="check_sub_agents")
async def check_sub_agents() -> ToolResult:
    # 查 index_store，返回下级 session 状态摘要
    # 例如："3 个下属任务：2 completed, 1 active"
    # 附带每个 session 的 id + goal + status + last_activity_at
```

调用时通过 `ToolCallContext` 获取当前 session 的 `agent_type` 和 `depth`：Sebastian 调用时查 depth=2（所有组长 session），组长调用时查 depth=3 且 `agent_type` 与自身相同。

### 5.4 inspect_session（Sebastian 和组长共用）

文件：`capabilities/tools/inspect_session/tool.py`

```python
@tool(name="inspect_session")
async def inspect_session(session_id: str, recent_n: int = 5) -> ToolResult:
    # 返回该 session 最近 N 条消息（含 tool call 记录）
    # + 当前 session 状态、last_activity_at、goal
    # 上级 agent 据此判断：卡在哪了、要不要干预、怎么干预
```

---

## 6. Stalled 检测（卡住举手示警）

### 6.1 机制

1. `Session.last_activity_at` 在每次 stream 事件（文字输出、tool call 开始、tool 返回结果）时更新
2. 后台 watchdog 任务每分钟扫描所有 `status=active` 的 session
3. 如果 `now - last_activity_at > stalled_threshold`（默认 5 分钟，可在 manifest.toml 配置），标记为 `stalled` 并发 `SESSION_STALLED` 事件
4. `stalled` 的 session 仍占 `max_children` 位（未释放资源）

### 6.2 处理链路

1. watchdog 检测到 stalled → 更新 session 状态 + 发 `SESSION_STALLED` 事件
2. 事件携带 `session_id` + `agent_type` + `goal` + `last_activity_at`
3. 上级 agent 收到事件 → 调用 `inspect_session` 获取最近消息和 tool call 上下文 → 综合判断
4. 判断后可以：发消息干预（恢复为 active）或取消该 session（标记 cancelled）
5. 用户在 App 里看到 stalled session 有橙色/黄色状态标记

### 6.3 典型场景

agent 调用 bash 执行测试 → 测试卡在等待输入 → bash tool 不返回 → 无新 stream 事件 → 5 分钟后标记 stalled → 上级 inspect 看到"tool_call bash_execute 已等待 8 分钟未返回" → 决定发消息干预"跳过这个测试"或取消 session。

---

## 7. API 接口变更

### 7.1 新增接口

| 方法 | 路径 | 用途 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/api/v1/agents/{agent_type}/sessions` | 用户为组长创建新对话 | `{content: str}` | `{session_id: str, ts: str}` |
| GET | `/api/v1/sessions/{session_id}/recent` | 查看 session 最近消息（inspect_session 的 HTTP 版） | query: `limit=5` | `{messages: [...], status, goal, last_activity_at}` |

### 7.2 修改接口

| 方法 | 路径 | 变更 |
|------|------|------|
| POST | `/api/v1/sessions/{session_id}/turns` | 不再走 Sebastian intervene，改为找 session 对应的 agent 实例直接回复 |
| GET | `/api/v1/agents/{agent_type}/sessions` | 返回数据新增 `depth`、`parent_session_id`、`last_activity_at` 字段 |
| GET | `/api/v1/agents` | 去掉 `workers` 数组，改为 `active_session_count`、`max_children` |

### 7.3 删除接口

| 方法 | 路径 | 原因 |
|------|------|------|
| GET | `/api/v1/agents/{agent_type}/workers/{agent_id}/sessions` | worker 概念移除 |

### 7.4 POST /agents/{agent_type}/sessions 详细流程

1. 验证 `agent_type` 已注册（404 if not）
2. 创建 Session：`depth=2, parent_session_id=null, status=active`
3. `session_store.create_session` + `index_store.upsert`
4. `asyncio.create_task` 触发该 agent 实例处理第一条消息
5. 返回 `{session_id, ts}`

### 7.5 POST /sessions/{id}/turns 路由变更

```python
# 之前（Sebastian 代答所有 sub-agent session）
state.sebastian.intervene(agent_type, session_id, content)

# 之后（agent 自答）
agent = state.agent_instances[session.agent_type]
asyncio.create_task(agent.run_streaming(content, session_id))
```

---

## 8. 前端变更

### 8.1 新增组件：NewChatFAB

文件：`ui/mobile/src/components/common/NewChatFAB.tsx`

深色圆角胶囊悬浮按钮，左侧 EditIcon + 右侧文字。

Props:
- `label: string` — 按钮文字
- `onPress: () => void`
- `disabled?: boolean` — 禁用时 opacity 降低，不响应点击
- `style?: ViewStyle` — 调用方控制定位

同时在 `Icons.tsx` 新增 `EditIcon`（从 `edit.svg` 提取 path data）。

### 8.2 Sub-agent session 列表页（[agentId].tsx）

- 底部添加 `NewChatFAB`，label="新对话"，永远不置灰
- 点击 → 导航到 `session/new?agent={agentType}`
- session 列表项根据 `depth` 区分：depth=3 带"子任务"标签

### 8.3 Sub-agent session 详情页（session/[id].tsx）

- `id=new` 时：渲染空 ConversationView + MessageInput，无真实 session
- 用户发第一条消息 → 调 `POST /agents/{agentType}/sessions`（body: `{content}`）→ 拿到真实 session_id → `router.replace('/subagents/session/{id}?agent={agentType}')` 替换路由
- 用户不发消息直接返回 → 什么都不创建，session 列表无变化
- `id` 为真实值时：行为不变，MessageInput 发消息走 `POST /sessions/{id}/turns`

### 8.4 侧边栏（AppSidebar.tsx）

- 删除 footer 区域，session 列表的 FlatList 撑满剩余空间
- `NewChatFAB` 以 `position: absolute, bottom, right` 悬浮在侧边栏内
- `disabled` 逻辑保留：`draftSession || !currentSessionId` 时不可点击

### 8.5 类型变更（types.ts）

- `SessionMeta` 增加 `depth: number`、`parent_session_id: string | null`、`last_activity_at: string`
- `Agent` 类型去掉 workers 相关，增加 `active_session_count: number`、`max_children: number`
- session status badge 增加 `stalled` 对应的橙色/黄色样式

---

## 9. 需要删除的现有代码

| 文件/模块 | 原因 |
|-----------|------|
| `sebastian/core/agent_pool.py` | worker pool 整体替换为 session 模型 |
| `sebastian/protocol/a2a/dispatcher.py` | queue + future 机制不再需要 |
| `sebastian/protocol/a2a/types.py` | `DelegateTask` / `TaskResult` 不再需要 |
| `sebastian/orchestrator/tools/` | 工具统一至 `capabilities/tools/`，此目录整体删除 |
| `BaseAgent.execute_delegated_task` | 替换为新的 session 级执行逻辑 |
| `app.py` 中 `_initialize_a2a_and_pools` | 替换为 agent 实例注册 |
| `app.py` 中 `_register_runtime_agent_state_handlers` | 基于 worker 状态的事件处理不再需要 |
| `gateway/state.py` 中 `agent_pools`、`worker_sessions` | 替换为 `agent_instances` |
| `Sebastian.intervene` 方法 | 不再有代答语义 |
| `tests/unit/test_agent_pool.py` | 对应模块删除 |

---

## 10. manifest.toml 新格式

```toml
[agent]
name = "铁匠"                          # 呈现名，暴露给 Sebastian 和用户
class_name = "CodeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5                        # 第三级组员并发上限，默认 5
stalled_threshold_minutes = 5           # 卡住检测阈值，默认 5 分钟

# 工具 / 技能权限（不变）
allowed_tools = ["bash_execute", "file_read", "file_write", "web_search"]
allowed_skills = ["research"]
```

`name` 字段的作用：
- Sebastian 的 system prompt 里用此名字介绍下属："你的下属有：铁匠（擅长编写代码）、骑士团长（擅长信息搜集）..."
- 用户可以说"让铁匠去做"，Sebastian 能对应到 `agent_type=code`
- App 中 agent 列表页也显示此名字

---

## 11. 与现有架构 spec 的关系

本 spec 替代 `2026-04-01-sebastian-architecture-design.md` 中以下内容：

| 原 spec 章节 | 本 spec 替代 |
|-------------|-------------|
| §2.3 Agent 继承模型 — AgentPool/Worker 多开模型 | §3.1 Agent 模型 |
| §2.4 三层协议栈 — A2A 部分 | §4 对话通道（直接调用，移除 A2A） |
| §5 Sub-Agent 扩展规范 — manifest.toml 格式 | §10 manifest.toml 新格式 |

以下内容**不变**：BaseAgent 继承体系、MCP/SSE 协议、Memory 三层结构、Dynamic Tool Factory、能力扩展方式（tools/mcps/skills 目录结构）。

---

## 12. 实现注意事项

### 12.1 单例并发安全

Agent 是单例但需同时处理多个 session 的并发请求。`BaseAgent` 中以下字段当前是实例级的，需要改为 per-session：

- `_active_stream` → `dict[str, asyncio.Task]`（key 为 session_id）
- `_current_task_goal` → `dict[str, str]`（key 为 session_id）

### 12.2 文件存储路径变更

移除 `agent_id` 后，session 目录结构简化：

```
# 之前
sessions/sebastian/{session_id}/
sessions/subagents/{agent_type}/{agent_id}/{session_id}/

# 之后
sessions/sebastian/{session_id}/        # Sebastian 不变
sessions/{agent_type}/{session_id}/     # 所有其他 agent，depth 由 meta.json 记录
```

`session_store.py` 中 `_session_dir` 和 `_session_dir_by_id` 去掉 `agent_id` 参数。`get_session` 改为只需 `session_id` + `agent_type`。

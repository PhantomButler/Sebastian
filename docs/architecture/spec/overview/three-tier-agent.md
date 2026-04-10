---
version: "1.0"
last_updated: 2026-04-10
status: implemented
---

# 三层 Agent 架构设计

*← [Overview 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与动机

原有架构采用 AgentPool + worker 多开模型（每个 agent_type 固定 3 个 worker），存在以下问题：

1. **worker 是多余抽象**：session_id 已能唯一定位工作记录，worker 身份无实际用途
2. **用户无法直接和 Sub-Agent 对话**：所有交互都经 Sebastian 代答，Sub-Agent 无法用自己的人格回复
3. **Sub-Agent 无法拆解复杂任务**：缺少向下分派的能力
4. **A2A Dispatcher 同步阻塞**：Sebastian 委派后等待 future 返回

新架构用三层模型 + 单例 + 直接调用替代上述所有机制。

---

## 2. 三层模型

### 2.1 层级规则

| 规则 | 说明 |
|------|------|
| 最大深度 | 3 层（Sebastian → 组长 → 组员） |
| 组长数量 | 由 `agents/` 目录下注册的 manifest.toml 决定，无上限 |
| 组员并发上限 | 每个组长可配置 `max_children`，默认 5 |
| 组员类型 | 与组长相同的 agent class，共享 persona 和 tools，scope 限定在子任务 |

### 2.2 用户对话权限

| 操作 | Sebastian | 组长 (depth=2) | 组员 (depth=3) |
|------|-----------|---------------|---------------|
| 用户创建新对话 | ✓ | ✓ | ✗ |
| 用户发消息干预已有 session | ✓ | ✓ | ✓ |
| 出现在 App 列表中 | 主对话页侧边栏 | 组长 session 列表 | 组长 session 列表（带标记） |

### 2.3 两条信息线

- **指挥链路**：用户 → Sebastian → 组长 → 组员（双向，自上而下委派 + 自下而上汇报）
- **直接沟通**：用户 → 组长 / 组员（跳过 Sebastian，直接对话或干预）

---

## 3. 数据模型

### 3.1 Agent 模型（单例）

每个 agent 类型是单例，通过 manifest.toml 注册：

```toml
[agent]
name = "铁匠"
class_name = "CodeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5
stalled_threshold_minutes = 5
allowed_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
allowed_skills = []
```

Agent 运行时属性：

- `agent_type: str` — 唯一标识（目录名，如 `"code"`）
- `name: str` — 呈现名（如 "铁匠"），暴露给 Sebastian 和用户
- `persona / system_prompt / tools / skills` — 自有能力
- `max_children: int` — 该组长可同时运行的组员 session 上限

运行时维护 `state.agent_instances: dict[str, BaseAgent]`，每个 agent_type 一个实例。

### 3.2 Session 模型

```python
class Session(BaseModel):
    id: str
    agent_type: str                  # 归属哪个 agent
    title: str
    goal: str
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
- `parent_session_id` 用于追溯关系和 UI 标记
- `last_activity_at` 用于 stalled 检测
- index.json 同步包含 `depth`、`parent_session_id`、`last_activity_at` 字段

### 3.3 Session 状态机

```
active → completed     （任务正常完成）
active → failed        （执行出错）
active → idle          （等待输入 / 暂停）
active → stalled       （无活动超过阈值，watchdog 标记）
active → cancelled     （上级或用户主动取消）
idle   → active        （收到新消息继续）
stalled → active       （收到干预消息后恢复）
stalled → cancelled    （上级或用户取消）
```

`max_children` 计数：只统计 `status=active` 的 depth=3 session。`completed`/`failed`/`cancelled` 不占位，`stalled` 仍占位。

---

## 4. 对话通道与 LLM 路由

### 4.1 每个 agent 用自己的 persona 回复

| 场景 | 触发方式 | 谁回复 |
|------|---------|--------|
| 用户 ↔ Sebastian | 主对话页发消息 | Sebastian |
| 用户 ↔ 组长 | 组长 session 列表新建对话 / 进入已有 session | 组长自己 |
| 用户 ↔ 组员 | 进入组员 session 发消息干预 | 组员 |

用户向任意 session 发消息时：

1. 根据 session 的 `agent_type` 找到 `state.agent_instances[agent_type]`
2. 用该 agent 的 `system_prompt` + session 的历史消息 → 调 LLM
3. 响应写回该 session

不再经过 Sebastian 中转。

### 4.2 Sebastian 委派（异步）

Sebastian 调用 `delegate_to_agent` 工具：

1. 创建一个 `depth=2` 的 session
2. `session_store.create_session` + `index_store.upsert`
3. `asyncio.create_task` 触发组长 agent 异步处理
4. 立即返回 `ToolResult(ok=True, output="已安排{agent_name}处理：{goal}")`
5. 组长完成后通过 event bus 发事件

### 4.3 组长分派组员（异步）

组长调用 `spawn_sub_agent` 工具：

1. 检查当前 agent 活跃的 depth=3 session 数 < `max_children`
2. 超限时返回错误
3. 创建 `Session(agent_type=self.agent_type, depth=3, parent_session_id=当前session)`
4. `asyncio.create_task` 触发组员异步处理
5. 立即返回

组员用和组长相同的 agent 实例（单例），persona 和 tools 一致，通过 session 初始消息中的子任务上下文区分工作范围。

### 4.4 Session 自动完成

agent 异步任务执行完毕时，自动更新 session 状态为 `completed` 或 `failed`，并发布对应事件。

---

## 5. 工具设计

所有工具统一放在 `capabilities/tools/` 下，每个工具一个独立子目录。

### 5.1 delegate_to_agent（Sebastian 专用）

```python
@tool(name="delegate_to_agent")
async def delegate_to_agent(agent_type: str, goal: str, context: str = "") -> ToolResult:
    # 1. 验证 agent_type 已注册
    # 2. 创建 depth=2 session
    # 3. asyncio.create_task 触发 agent 执行
    # 4. 返回 "已安排{agent_name}处理：{goal}"
```

### 5.2 spawn_sub_agent（组长专用）

```python
@tool(name="spawn_sub_agent")
async def spawn_sub_agent(goal: str, context: str = "") -> ToolResult:
    # 1. 检查 active depth=3 session 数 < max_children
    # 2. 创建 depth=3 session
    # 3. asyncio.create_task 触发组员执行
    # 4. 返回 "已安排组员处理：{goal}"
```

### 5.3 check_sub_agents（Sebastian 和组长共用）

```python
@tool(name="check_sub_agents")
async def check_sub_agents() -> ToolResult:
    # 通过 ToolCallContext 获取当前 agent_type 和 depth
    # Sebastian 调用时查 depth=2，组长调用时查 depth=3
    # 返回下级 session 状态摘要
```

### 5.4 inspect_session（Sebastian 和组长共用）

```python
@tool(name="inspect_session")
async def inspect_session(session_id: str, recent_n: int = 5) -> ToolResult:
    # 返回该 session 最近 N 条消息 + 状态 + goal
    # 上级据此判断：卡在哪了、要不要干预
```

---

## 6. Stalled 检测

### 6.1 机制

1. `Session.last_activity_at` 在每次 stream 事件时更新
2. 后台 watchdog 任务每分钟扫描所有 `status=active` 的 session
3. 如果 `now - last_activity_at > stalled_threshold`（默认 5 分钟），标记为 `stalled` 并发 `SESSION_STALLED` 事件
4. `stalled` 的 session 仍占 `max_children` 位

### 6.2 处理链路

1. watchdog 检测到 stalled → 更新 session 状态 + 发事件
2. 上级 agent 收到事件 → 调用 `inspect_session` 获取上下文 → 判断
3. 可以：发消息干预（恢复为 active）或取消（标记 cancelled）
4. App 中 stalled session 有橙色/黄色状态标记

### 6.3 典型场景

agent 调用 bash 执行测试 → 测试卡在等待输入 → bash tool 不返回 → 无新 stream 事件 → 5 分钟后标记 stalled → 上级 inspect 看到 tool_call 超时 → 决定干预或取消。

---

## 7. API 接口变更

### 7.1 新增接口

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/agents/{agent_type}/sessions` | 用户为组长创建新对话 |
| GET | `/api/v1/sessions/{session_id}/recent` | 查看 session 最近消息 |

### 7.2 修改接口

| 方法 | 路径 | 变更 |
|------|------|------|
| POST | `/api/v1/sessions/{session_id}/turns` | 找 session 对应的 agent 实例直接回复 |
| GET | `/api/v1/agents/{agent_type}/sessions` | 新增 depth、parent_session_id、last_activity_at |
| GET | `/api/v1/agents` | 返回 `active_session_count`、`max_children`（无 workers） |

**`GET /api/v1/agents` 响应格式**：

```json
{
  "agents": [
    {
      "agent_type": "code",
      "name": "铁匠",
      "description": "编写代码、调试问题、构建工具",
      "active_session_count": 2,
      "max_children": 5
    }
  ]
}
```

---

## 8. 前端变更

### 8.1 NewChatFAB 组件

深色圆角胶囊悬浮按钮（左侧 EditIcon + 右侧文字），用于在组长 session 列表页和侧边栏创建新对话。

### 8.2 Sub-agent session 列表页

- 底部 NewChatFAB，label="新对话"
- 点击 → 导航到 `session/new?agent={agentType}`
- session 列表项根据 `depth` 区分：depth=3 带"子任务"标签

### 8.3 Sub-agent session 详情页

- `id=new` 时：渲染空 ConversationView，用户发第一条消息后创建真实 session
- `id` 为真实值时：MessageInput 发消息走 `POST /sessions/{id}/turns`

### 8.4 类型变更

- `SessionMeta` 增加 `depth`、`parent_session_id`、`last_activity_at`
- `Agent` 类型增加 `active_session_count`、`max_children`
- session status badge 增加 `stalled` 橙色/黄色样式

---

## 9. 实现注意事项

### 9.1 单例并发安全

Agent 是单例但需同时处理多个 session 的并发请求。以下字段为 per-session：

- `_active_streams: dict[str, asyncio.Task]`（key 为 session_id）
- `_current_depth: dict[str, int]`（key 为 session_id）

### 9.2 文件存储路径

Session 目录按 `agent_type/session_id/` 存储，无 agent_id 层级：

```
sessions/
├── sebastian/{session_id}/
├── code/{session_id}/          # depth 由 meta.json 记录
└── stock/{session_id}/
```

---

*← [Overview 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

# Sub-Agent 主动通知与双向通信设计

**日期**：2026-04-12  
**状态**：待实现

## 问题背景

Sebastian 委派子代理任务后，子代理异步执行，完成时无任何主动通知机制：

1. `SESSION_COMPLETED` 事件已发布到 EventBus，但 SSE 路由按子代理 session_id 过滤，客户端订阅 Sebastian session_id，事件被丢弃，客户端永远收不到
2. 即使事件到达客户端，Sebastian 的当前对话轮次已结束，不会主动开口汇报
3. 子代理遇到决策点时无法主动暂停询问，只能失败或继续猜测
4. Sebastian 无法向已有的 waiting session 回复，缺乏双向通信

## 设计目标

- 子代理完成/失败时 Sebastian 主动向用户汇报结果
- 子代理遇到决策点时可主动暂停并向 Sebastian 请求指示
- Sebastian 可向 waiting 中的子代理发送指示并恢复其执行
- 客户端同时收到轻量 SSE 通知卡片（不依赖 LLM）

## 架构概览

```
子代理 run_agent_session 结束
    → publish SESSION_COMPLETED/FAILED (含 parent_session_id, goal)
        ├── SSEManager → 客户端通知卡片（轻量，方案 A）
        └── CompletionNotifier
                → session_store 取最后 assistant 消息
                → 构造结构化内部通知
                → per-session Queue 串行化
                → sebastian.run_streaming(通知, parent_session_id)
                    → SSE 流 → 客户端看到 Sebastian 汇报（方案 B）

子代理调 ask_parent(question)
    → session 状态 → WAITING
    → publish SESSION_WAITING (含 parent_session_id, question)
        ├── SSEManager → 客户端通知卡片
        └── CompletionNotifier → 同上流程，通知内容为问题

Sebastian 调 reply_to_agent(session_id, instruction)
    → 写入 waiting session 的 messages.jsonl（user turn）
    → 重新触发 run_agent_session
    → session 状态 → ACTIVE
```

---

## Section 1：数据层变更

### 1.1 `SessionStatus.WAITING`（`core/types.py`）

新增 `WAITING` 状态，语义为子代理主动暂停等待指示，与 `STALLED`（系统检测到无响应）明确区分：

```python
class SessionStatus(StrEnum):
    ACTIVE    = "active"
    IDLE      = "idle"
    COMPLETED = "completed"
    FAILED    = "failed"
    STALLED   = "stalled"     # 系统检测到卡死（被动）
    WAITING   = "waiting"     # 子代理主动暂停等待指示（主动）← 新增
    CANCELLED = "cancelled"
```

### 1.2 `EventType.SESSION_WAITING`（`protocol/events/types.py`）

```python
# Session lifecycle (three-tier architecture)
SESSION_COMPLETED = "session.completed"
SESSION_FAILED    = "session.failed"
SESSION_CANCELLED = "session.cancelled"
SESSION_STALLED   = "session.stalled"
SESSION_WAITING   = "session.waiting"   # ← 新增
```

### 1.3 `IndexStore.upsert` 补 `goal` 字段（`store/index_store.py`）

现有 bug：`check_sub_agents` 里用 `s.get("goal")` 但 `upsert` 从未写入该字段，始终 fallback 到 `title`。顺手修复：

```python
entry = {
    "id": session.id,
    "agent_type": session.agent_type,
    "title": session.title,
    "goal": session.goal,          # ← 补上
    "status": session.status.value,
    "depth": session.depth,
    "parent_session_id": session.parent_session_id,
    "last_activity_at": session.last_activity_at.isoformat(),
    "updated_at": session.updated_at.isoformat(),
    "task_count": session.task_count,
    "active_task_count": session.active_task_count,
}
```

### 1.4 Session 事件统一携带 `parent_session_id` 和 `goal`（`core/session_runner.py`）

`run_agent_session` 的 `finally` 块发布事件时统一补充字段：

```python
await event_bus.publish(
    Event(
        type=event_type,
        data={
            "session_id": session.id,
            "parent_session_id": session.parent_session_id,  # ← 新增
            "agent_type": session.agent_type,
            "goal": session.goal,                            # ← 新增
            "status": session.status.value,
        },
    )
)
```

---

## Section 2：SSE 路由修复（`gateway/sse.py`）

**现有逻辑**：只按 `event.data["session_id"]` 匹配订阅的 session_id，子代理事件因 session_id 不匹配被丢弃。

**修改后**：`session_id` 或 `parent_session_id` 任一匹配订阅即下发：

```python
# 修改前
if (
    subscription.session_id is not None
    and event.data.get("session_id") != subscription.session_id
):
    continue

# 修改后
if subscription.session_id is not None:
    event_session_id = event.data.get("session_id")
    event_parent_id = event.data.get("parent_session_id")
    if subscription.session_id not in (event_session_id, event_parent_id):
        continue
```

**效果**：客户端订阅 Sebastian session_id 后，其所有子代理（depth=2）的生命周期事件均可收到，用于渲染轻量通知卡片。

---

## Section 3：Completion Notifier（`gateway/completion_notifier.py`）

### 职责

订阅 `SESSION_COMPLETED`、`SESSION_FAILED`、`SESSION_WAITING`，触发父会话（Sebastian 或 Leader）的新一轮 LLM turn，实现主动汇报。

### 通知内容构造

从 `session_store.get_messages(session_id, agent_type, limit=10)` 取最后一条 `role == "assistant"` 的 `content`，超 500 字截断。

**completed/failed 格式：**
```
[内部通知] 子代理 {display_name} 已{完成/失败}任务
目标：{session.goal}
状态：{completed/failed}
汇报：{last_assistant_content}
session_id：{session_id}（可用 inspect_session 查看详情）
```

**waiting 格式：**
```
[内部通知] 子代理 {display_name} 遇到问题，需要你的指示
目标：{session.goal}
问题：{question}
session_id：{session_id}（回复请使用 reply_to_agent 工具）
```

### 并发处理

每个父 session 维护一个 `asyncio.Queue`，保证同一父 session 的通知串行处理，不并发触发 LLM turn：

```python
class CompletionNotifier:
    def __init__(self, event_bus, session_store, agent_instances, agent_registry):
        self._session_store = session_store
        self._agent_instances = agent_instances
        self._agent_registry = agent_registry
        self._queues: dict[str, asyncio.Queue] = {}
        event_bus.subscribe(self._on_session_event, EventType.SESSION_COMPLETED)
        event_bus.subscribe(self._on_session_event, EventType.SESSION_FAILED)
        event_bus.subscribe(self._on_session_event, EventType.SESSION_WAITING)
```

每个父 session 的 queue 由一个独立 asyncio task 驱动，串行消费通知消息后调用 `agent.run_streaming(notification, parent_session_id)`。

### 初始化

在 `gateway/app.py` 启动时创建实例：

```python
completion_notifier = CompletionNotifier(
    event_bus=state.event_bus,
    session_store=state.session_store,
    agent_instances=state.agent_instances,
    agent_registry=state.agent_registry,
)
```

---

## Section 4：`ask_parent` 工具（`capabilities/tools/ask_parent/__init__.py`）

子代理遇到决策点时主动调用，触发 `WAITING` 状态和父会话通知。

```python
@tool(
    name="ask_parent",
    description="遇到无法自行决定的问题时，暂停当前任务并向上级请求指示。上级回复前请勿继续执行任何操作。",
    permission_tier=PermissionTier.LOW,
)
async def ask_parent(question: str) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")
    if ctx.depth == 1:
        return ToolResult(ok=False, error="Sebastian 没有上级，无法调用此工具")
    ...
```

**调用时做三件事：**

1. 将 session 状态更新为 `WAITING`（`index_store.upsert` + `session_store.update_session`）
2. 发布 `SESSION_WAITING` 事件，`data` 携带 `question`、`parent_session_id`、`goal`
3. 返回阻塞提示，LLM 收到后停止继续执行：

```python
return ToolResult(
    ok=True,
    output="已向上级请求指示，请等待回复后继续。请不要继续执行任何操作。"
)
```

**注意**：`ask_parent` 调用后子代理的 `run_streaming` 会在当前 turn 结束（LLM 收到 tool result 后不再有新的 human turn 驱动），session 保持 `WAITING` 直到 `reply_to_agent` 重新激活它。

---

## Section 5：`reply_to_agent` 工具（`capabilities/tools/reply_to_agent/__init__.py`）

Sebastian 或 Leader 向 waiting 子代理发送指示并恢复其执行。

```python
@tool(
    name="reply_to_agent",
    description="向等待指示的子代理发送回复，恢复其任务执行。",
    permission_tier=PermissionTier.LOW,
)
async def reply_to_agent(session_id: str, instruction: str) -> ToolResult:
    ...
```

**调用时做三件事：**

1. **校验 session 状态**：从 `index_store` 查 session，确认状态为 `WAITING`；不是则返回错误
2. **写入指示到 session 历史**：`session_store.append_message(session_id, role="user", content=instruction, agent_type=...)`
3. **重新触发执行**：`asyncio.create_task(run_agent_session(agent, session, goal=session.goal, ...))`，session 状态恢复 `ACTIVE`

**完整流转：**

```
子代理 ask_parent("这个文件要覆盖吗？")
    → session.status = WAITING
    → SESSION_WAITING 事件 → Sebastian 收到通知并向用户汇报

用户："可以覆盖"
Sebastian → reply_to_agent(session_id="xxx", instruction="可以覆盖，继续执行")
    → append_message(role="user", content="可以覆盖，继续执行")
    → run_agent_session 重新启动（带完整历史）
    → 子代理继续执行
```

---

## 文件改动清单

| 操作 | 文件 |
|------|------|
| 修改 | `sebastian/core/types.py` — 新增 `SessionStatus.WAITING` |
| 修改 | `sebastian/protocol/events/types.py` — 新增 `EventType.SESSION_WAITING` |
| 修改 | `sebastian/store/index_store.py` — `upsert` 补 `goal` 字段 |
| 修改 | `sebastian/core/session_runner.py` — 事件 data 加 `parent_session_id`、`goal` |
| 修改 | `sebastian/gateway/sse.py` — SSE 路由支持 `parent_session_id` 匹配 |
| 新增 | `sebastian/gateway/completion_notifier.py` — CompletionNotifier |
| 修改 | `sebastian/gateway/app.py` — 初始化 CompletionNotifier |
| 新增 | `sebastian/capabilities/tools/ask_parent/__init__.py` |
| 新增 | `sebastian/capabilities/tools/reply_to_agent/__init__.py` |
| 修改 | `sebastian/capabilities/README.md` — 更新工具列表 |
| 新增/修改 | `tests/unit/` — 对应单元测试 |

---

## 不在本次范围内

- 子代理 depth=3（Leader 的子代理）调 `ask_parent` 后的 Leader 通知路径——本次只覆盖 depth=2 通知 Sebastian，depth=3 的链路结构相同，后续可扩展
- 客户端通知卡片的 UI 渲染（Android 端另行处理）
- `ask_parent` 超时处理（子代理等待超过一定时间后的降级策略）

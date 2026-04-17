---
version: "1.0"
last_updated: 2026-04-17
status: in-progress
---

# Sub-Agent 主动通知与双向通信

*← [Gateway 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 问题背景

Sebastian 委派子代理任务后，子代理异步执行，完成时无任何主动通知机制：

1. `SESSION_COMPLETED` 事件已发布到 EventBus，但 SSE 路由按子代理 session_id 过滤，客户端订阅 Sebastian session_id，事件被丢弃，客户端永远收不到
2. 即使事件到达客户端，Sebastian 的当前对话轮次已结束，不会主动开口汇报
3. 子代理遇到决策点时无法主动暂停询问，只能失败或继续猜测
4. Sebastian 无法向已有的 waiting session 回复，缺乏双向通信

## 2. 设计目标

- 子代理完成/失败时 Sebastian 主动向用户汇报结果
- 子代理遇到决策点时可主动暂停并向 Sebastian 请求指示
- Sebastian 可向 waiting 中的子代理发送指示并恢复其执行
- 客户端同时收到轻量 SSE 通知卡片（不依赖 LLM）

## 3. 架构概览

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

## 4. 数据层变更

### 4.1 `SessionStatus.WAITING`（`core/types.py`）

新增 `WAITING` 状态，语义为子代理主动暂停等待指示，与 `STALLED`（系统检测到无响应）明确区分：

```python
class SessionStatus(StrEnum):
    ACTIVE    = "active"
    IDLE      = "idle"
    COMPLETED = "completed"
    FAILED    = "failed"
    STALLED   = "stalled"     # 系统检测到卡死（被动）
    WAITING   = "waiting"     # 子代理主动暂停等待指示（主动）
    CANCELLED = "cancelled"
```

### 4.2 `EventType.SESSION_WAITING`（`protocol/events/types.py`）

```python
SESSION_COMPLETED = "session.completed"
SESSION_FAILED    = "session.failed"
SESSION_CANCELLED = "session.cancelled"
SESSION_STALLED   = "session.stalled"
SESSION_WAITING   = "session.waiting"
```

### 4.3 `IndexStore.upsert` 补 `goal` 字段（`store/index_store.py`）

```python
entry = {
    "id": session.id,
    "agent_type": session.agent_type,
    "title": session.title,
    "goal": session.goal,
    "status": session.status.value,
    "depth": session.depth,
    "parent_session_id": session.parent_session_id,
    "last_activity_at": session.last_activity_at.isoformat(),
    "updated_at": session.updated_at.isoformat(),
    "task_count": session.task_count,
    "active_task_count": session.active_task_count,
}
```

### 4.4 Session 事件统一携带 `parent_session_id` 和 `goal`（`core/session_runner.py`）

`run_agent_session` 的 `finally` 块发布事件时统一补充字段：

```python
await event_bus.publish(
    Event(
        type=event_type,
        data={
            "session_id": session.id,
            "parent_session_id": session.parent_session_id,
            "agent_type": session.agent_type,
            "goal": session.goal,
            "status": session.status.value,
        },
    )
)
```

> **实现增强**：代码中 `WAITING` 状态不通过 session_runner 的 finally 块发布事件，而是由 `ask_parent` 工具自己发布 `SESSION_WAITING`，避免事件重复。

---

## 5. SSE 路由修复（`gateway/sse.py`）

**修改前**：只按 `event.data["session_id"]` 匹配订阅的 session_id，子代理事件因 session_id 不匹配被丢弃。

**修改后**：`session_id` 或 `parent_session_id` 任一匹配订阅即下发：

```python
if subscription.session_id is not None:
    event_session_id = event.data.get("session_id")
    event_parent_id = event.data.get("parent_session_id")
    if subscription.session_id not in (event_session_id, event_parent_id):
        continue
```

**效果**：客户端订阅 Sebastian session_id 后，其所有子代理（depth=2）的生命周期事件均可收到，用于渲染轻量通知卡片。

> **实现差异**：SSE replay（历史事件回放）路径仅按 `session_id` 匹配，不检查 `parent_session_id`。只有实时事件流同时匹配两者。replay 场景下子代理事件不回放，影响有限。

---

## 6. CompletionNotifier（`gateway/completion_notifier.py`）

### 职责

订阅 `SESSION_COMPLETED`、`SESSION_FAILED`、`SESSION_WAITING`，触发父会话（Sebastian 或 Leader）的新一轮 LLM turn，实现主动汇报。

### 通知内容构造

从 `session_store.get_messages(session_id, agent_type, limit=10)` 取最后一条 `role == "assistant"` 的 `content`，超 500 字截断。

**completed/failed 格式：**
```
[内部通知] 子代理 {agent_type.capitalize()} 已{完成/失败}任务
目标：{session.goal}
状态：{completed/failed}
汇报：{last_assistant_content}
session_id：{session_id}（可用 inspect_session 查看详情）
```

**waiting 格式：**
```
[内部通知] 子代理 {agent_type.capitalize()} 遇到问题，需要你的指示
目标：{session.goal}
问题：{question}
session_id：{session_id}（回复请使用 resume_agent 工具）
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

### 初始化

在 `gateway/app.py` 启动时创建实例。

---

## 7. `ask_parent` 工具（`capabilities/tools/ask_parent/`）

子代理遇到决策点时主动调用，触发 `WAITING` 状态和父会话通知。

```python
@tool(
    name="ask_parent",
    description="遇到无法自行决定的问题时，暂停当前任务并向上级请求指示。上级回复前请勿继续执行任何操作。",
    permission_tier=PermissionTier.LOW,
)
async def ask_parent(question: str) -> ToolResult:
    ...
```

**调用时做三件事：**

1. 将 session 状态更新为 `WAITING`（`index_store.upsert` + `session_store.update_session`）
2. 发布 `SESSION_WAITING` 事件，`data` 携带 `question`、`parent_session_id`、`goal`
3. 返回阻塞提示，LLM 收到后停止继续执行

---

## 8. `resume_agent` 工具（`capabilities/tools/resume_agent/`）

Sebastian 或 Leader 向 waiting 或 idle 子代理发送指示并恢复其执行（原 `reply_to_agent`，已改名扩展）。

```python
@tool(
    name="resume_agent",
    description="恢复暂停（IDLE）或等待（WAITING）状态的 sub-agent，可选追加指令。",
    permission_tier=PermissionTier.LOW,
)
async def resume_agent(agent_type: str, session_id: str, instruction: str = "") -> ToolResult:
    ...
```

> **实现增强**：原设计为 `reply_to_agent`（仅处理 `WAITING` 状态），实际实现已扩展为 `resume_agent`，同时支持 `WAITING` 和 `IDLE` 状态恢复，`instruction` 参数可空。详见 [agent-stop-resume.md](agent-stop-resume.md)。

---

## 9. 文件改动清单

| 操作 | 文件 |
|------|------|
| 修改 | `sebastian/core/types.py` — `SessionStatus.WAITING` |
| 修改 | `sebastian/protocol/events/types.py` — `EventType.SESSION_WAITING` |
| 修改 | `sebastian/store/index_store.py` — `upsert` 补 `goal` 字段 |
| 修改 | `sebastian/core/session_runner.py` — 事件 data 加 `parent_session_id`、`goal` |
| 修改 | `sebastian/gateway/sse.py` — SSE 路由支持 `parent_session_id` 匹配 |
| 新增 | `sebastian/gateway/completion_notifier.py` — CompletionNotifier |
| 修改 | `sebastian/gateway/app.py` — 初始化 CompletionNotifier |
| 新增 | `sebastian/capabilities/tools/ask_parent/__init__.py` |
| 新增 | `sebastian/capabilities/tools/resume_agent/__init__.py`（原 `reply_to_agent`，已改名扩展，见 [agent-stop-resume.md](agent-stop-resume.md)） |

---

## 10. 不在本 spec 范围内

- 子代理 depth=3（Leader 的子代理）调 `ask_parent` 后的 Leader 通知路径——本次只覆盖 depth=2 通知 Sebastian，depth=3 的链路结构相同，后续可扩展
- 客户端通知卡片的 UI 渲染（Android 端另行处理）
- `ask_parent` 超时处理（子代理等待超过一定时间后的降级策略）

---

*← [Gateway 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

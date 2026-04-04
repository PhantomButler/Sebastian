# protocol — 事件总线与 A2A 协议

## 职责

两部分：`events/` 提供进程内发布-订阅事件总线；`a2a/` 定义 Sebastian ↔ Sub-Agent 通信的数据结构。

## 关键文件

| 文件 | 职责 |
|---|---|
| `events/bus.py` | `EventBus`：内存发布-订阅，`subscribe(handler, event_type?)`、`publish(event)`，支持通配符订阅（不传 event_type 接收所有事件） |
| `events/types.py` | `EventType`（所有事件类型枚举）和 `Event`（Pydantic 模型，含 id/type/data/ts） |
| `a2a/types.py` | A2A 消息类型：`DelegateTask`（Sebastian → Sub-Agent）、`EscalateRequest`（Sub-Agent → Sebastian）、`TaskResult`（Sub-Agent → Sebastian） |

## 事件类型速查

```
task.*          任务生命周期（created / planning_started / started / completed / failed / cancelled）
agent.*         Agent 协调（delegated / escalated / result_received）
user.*          用户交互（approval_requested / approval_granted / approval_denied / interrupted）
approval.*      审批流（requested / granted / denied）
turn.*          LLM turn 流（delta / thinking_delta / tool_block_start / done）
```

## 公开接口（其他模块如何使用）

```python
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

bus = EventBus()

# 订阅特定事件
async def on_task_done(event: Event) -> None: ...
bus.subscribe(on_task_done, EventType.TASK_COMPLETED)

# 订阅所有事件
bus.subscribe(handler)  # 不传 event_type

# 发布
await bus.publish(Event(type=EventType.TASK_STARTED, data={"task_id": "..."}))

# A2A 消息
from sebastian.protocol.a2a.types import DelegateTask, TaskResult
```

## 常见任务入口

- **新增事件类型** → `events/types.py` 的 `EventType` 枚举（加一行即可，Bus 自动支持）
- **修改 EventBus 异常处理/广播逻辑** → `events/bus.py` 的 `publish()`
- **新增 A2A 消息结构** → `a2a/types.py`
- **查看某事件的所有订阅者** → 在代码库中 grep `subscribe.*EventType.XXX`

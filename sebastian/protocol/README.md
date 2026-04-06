# protocol — 事件总线与 A2A 协议

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供 Sebastian 内部事件通信基础设施：`events/` 是进程内发布-订阅事件总线，供各模块解耦通信。`a2a/` 目录保留但 dispatcher 与 types 已移除——Agent 间协作现通过 `spawn_sub_agent` / `delegate_to_agent` 等工具调用 + `asyncio.create_task` 实现，无需独立调度器。

## 目录结构

```
protocol/
├── __init__.py          # 模块入口（空）
├── events/              # 进程内发布-订阅事件总线
│   ├── __init__.py
│   ├── bus.py           # EventBus：subscribe() / publish()，支持通配符订阅
│   └── types.py         # EventType 枚举 + Event Pydantic 模型（id/type/data/ts）
└── a2a/                 # Agent-to-Agent 协议目录（dispatcher/types 已移除）
    └── __init__.py
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增事件类型 | [events/types.py](events/types.py) 的 `EventType` 枚举（加一行即可） |
| 修改 EventBus 广播/异常处理逻辑 | [events/bus.py](events/bus.py) 的 `publish()` |
| 修改 Agent 间委派逻辑 | `capabilities/tools/delegate_to_agent/` 或 `spawn_sub_agent/` |
| 查看某事件的所有订阅者 | 搜索 `subscribe.*EventType.XXX` |

## 事件类型速查

```
task.*          任务生命周期（created / planning_started / started / completed / failed / cancelled）
agent.*         Agent 协调（delegated / escalated / result_received）
user.*          用户交互（approval_requested / approval_granted / approval_denied / interrupted）
approval.*      审批流（requested / granted / denied）
turn.*          LLM turn 流（delta / thinking_delta / tool_block_start / done）
```

## 公开接口

```python
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

bus = EventBus()

# 订阅特定事件
async def on_task_done(event: Event) -> None: ...
bus.subscribe(on_task_done, EventType.TASK_COMPLETED)

# 订阅所有事件（不传 event_type）
bus.subscribe(handler)

# 发布
await bus.publish(Event(type=EventType.TASK_STARTED, data={"task_id": "..."}))
```

## 子模块

- `events/` — 进程内事件总线，`bus.py` + `types.py`，无外部依赖，任意模块可订阅
- `a2a/` — A2A 协议目录（dispatcher/types 已移除，仅保留 `__init__.py`）

---

> 修改本目录或模块后，请同步更新此 README。

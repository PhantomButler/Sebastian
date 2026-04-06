# events

> 上级索引：[protocol/](../README.md)

## 目录职责

提供系统级事件总线，用于在 Sebastian 各模块间解耦发布和订阅内部事件。覆盖 Task 生命周期、Agent 协调、用户交互、审批流程、对话轮次及工具执行等全部运行时事件类型。

## 目录结构

```
events/
├── __init__.py        # 包入口（空）
├── types.py           # EventType 枚举（所有事件类型）+ Event 数据模型
└── bus.py             # EventBus：发布/订阅实现 + 全局单例 bus
```

## 核心概念

### 事件类型（types.py）

`EventType`（StrEnum）涵盖以下事件域：

| 事件域 | 示例类型 |
|--------|---------|
| Task 生命周期 | `task.created` / `task.started` / `task.completed` / `task.failed` |
| Agent 协调 | `agent.delegated` / `agent.escalated` / `agent.result_received` |
| 用户交互 | `user.interrupted` / `user.approval_requested` / `user.approval_granted` |
| 审批流 | `approval.requested` / `approval.granted` / `approval.denied` |
| 对话轮次 | `turn.delta` / `turn.response` / `turn.interrupted` |
| 内容块 | `thinking_block.start` / `text_block.start` / `tool_block.start` |
| 工具执行 | `tool.running` / `tool.executed` / `tool.failed` |

### 事件总线（bus.py）

`EventBus` 支持按 `EventType` 精确订阅，也支持通配符（`event_type=None`）接收所有事件。`publish()` 并发调用所有匹配处理器（`asyncio.gather`），单个处理器异常不影响其余处理器。

模块底部暴露全局单例 `bus`，各模块直接 `from sebastian.protocol.events.bus import bus` 使用。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增事件类型 | [types.py](types.py) — 在 `EventType` 枚举中添加 |
| 订阅/发布逻辑、通配符行为 | [bus.py](bus.py) — `EventBus.subscribe / publish` |
| 全局单例引用 | [bus.py](bus.py) — 文件底部 `bus = EventBus()` |

---

> 修改本目录或模块后，请同步更新此 README。

# a2a

> 上级索引：[protocol/](../README.md)

## 目录职责

实现 Agent-to-Agent（A2A）通信协议。定义 Sebastian 主管家与各 Sub-Agent 之间消息传递的数据结构，并提供异步分发器，将任务路由到对应 Agent 的专属队列，通过 Future 机制等待结果回传。

## 目录结构

```
a2a/
├── __init__.py        # 包入口（空）
├── types.py           # A2A 消息数据模型（DelegateTask / EscalateRequest / TaskResult / Artifact）
└── dispatcher.py      # A2ADispatcher：按 agent_type 路由任务队列，Future 等待结果
```

## 核心概念

### 消息类型（types.py）

| 类型 | 方向 | 用途 |
|------|------|------|
| `DelegateTask` | Sebastian → Sub-Agent | 下发任务，含 goal / context / constraints |
| `EscalateRequest` | Sub-Agent → Sebastian | 请求人工或主管家决策 |
| `TaskResult` | Sub-Agent → Sebastian | 上报任务完成结果或错误 |
| `Artifact` | 附属于 TaskResult | 任务产物（文件内容、代码等） |

### 分发器（dispatcher.py）

`A2ADispatcher` 为每种 agent_type 维护一个独立的 `asyncio.Queue`，避免不同类型 Agent 之间的队头阻塞。任务通过 `delegate()` 入队后挂起等待，Worker 完成后调用 `resolve()` 触发 Future 返回结果。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| A2A 消息结构（新增字段、修改约束） | [types.py](types.py) |
| 任务路由逻辑（队列策略、超时处理） | [dispatcher.py](dispatcher.py) |

---

> 修改本目录或模块后，请同步更新此 README。

# core — BaseAgent 引擎

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供所有 Agent 的执行基础：任务生命周期管理、LLM 流式调用循环、工具注册与调度、并发 Worker 池。所有 Sub-Agent 均继承 `BaseAgent`，通过 `AgentLoop` 驱动多轮工具调用，由 `TaskManager` 管理状态机流转。

## 目录结构

```
core/
├── __init__.py          # 模块入口（空导出，按需 import 子模块）
├── base_agent.py        # 所有 Agent 的抽象基类，持有 registry/session_store/event_bus，提供 run_streaming() 入口
├── agent_loop.py        # 单次 LLM turn 执行循环：发请求 → 处理 tool_use → 迭代，最多 MAX_ITERATIONS=20 轮
├── agent_pool.py        # 固定大小 Worker 槽池：acquire() 拿到空闲 worker_id，release() 归还
├── task_manager.py      # Task 提交与状态机驱动：submit() 创建异步 Task，transition() 推进状态并发布 EventBus 事件
├── protocols.py         # 结构子类型 Protocol 定义：ApprovalManagerProtocol、ToolSpecProvider
├── stream_events.py     # LLM 流式输出的内部事件 dataclass（TextDelta、ToolCallReady、TurnDone 等）
├── tool.py              # @tool 装饰器系统：自动提取函数签名生成 ToolSpec，注册到全局 _tools 字典
└── types.py             # 核心数据类型：Task、Session、TaskStatus 状态机枚举、ToolResult、Checkpoint 等
```

## 任务状态机

```
CREATED → PLANNING → RUNNING → COMPLETED
                   ↘ FAILED
              ↘ FAILED
                              ↘ CANCELLED
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Task 状态流转规则 | [task_manager.py](task_manager.py) 的 `_VALID_TRANSITIONS` |
| LLM 调用参数 / 最大迭代次数 | [agent_loop.py](agent_loop.py) 的 `MAX_ITERATIONS` |
| Anthropic / OpenAI 消息格式适配 | [agent_loop.py](agent_loop.py)，由 `provider.message_format` 自动分支 |
| BaseAgent 默认行为（system_prompt、run_streaming） | [base_agent.py](base_agent.py) |
| Worker 并发槽数 | [agent_pool.py](agent_pool.py)，由 `gateway/app.py` 初始化时传入 `worker_count` |
| 新增核心数据类型 | [types.py](types.py) |
| 注册新工具（@tool 装饰器） | [tool.py](tool.py)，工具实现放 `capabilities/tools/` |
| Approval / ToolSpec 跨模块接口 | [protocols.py](protocols.py) |
| LLM 流式事件结构 | [stream_events.py](stream_events.py) |

## 公开接口（其他模块如何使用）

```python
# 继承 BaseAgent 实现自定义 Agent
from sebastian.core.base_agent import BaseAgent

# 提交任务并驱动状态机
from sebastian.core.task_manager import TaskManager
await task_manager.submit(task, async_fn)

# 并发 Worker 调度
from sebastian.core.agent_pool import AgentPool
worker_id = await pool.acquire()
pool.release(worker_id)

# 注册工具（capabilities/tools/ 中使用）
from sebastian.core.tool import tool
@tool(description="...")
async def my_tool(...) -> ToolResult: ...

# 核心类型
from sebastian.core.types import Task, TaskStatus, Session, ToolResult
```

---

> 修改本目录或模块后，请同步更新此 README。

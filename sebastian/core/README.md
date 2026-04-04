# core — BaseAgent 引擎

## 职责

提供所有 Agent 的执行基础：任务生命周期管理、LLM 流式调用循环、工具注册与调度、并发 Worker 池。

## 关键文件

| 文件 | 职责 |
|---|---|
| `base_agent.py` | 所有 Agent 的抽象基类，持有 registry/session_store/event_bus，提供 `run_streaming()` 入口 |
| `agent_loop.py` | 单次 LLM turn 执行循环：发请求 → 处理 tool_use → 迭代，最多 `MAX_ITERATIONS=20` 轮 |
| `task_manager.py` | Task 提交与状态机驱动：`submit()` 创建异步 Task，`transition()` 推进状态，发布 EventBus 事件 |
| `agent_pool.py` | 固定大小 Worker 槽池：`acquire()` 拿到空闲 worker_id，`release()` 归还，内部用 Future 队列等待 |
| `tool.py` | `@tool` 装饰器系统：自动提取函数签名生成 `ToolSpec`，注册到全局 `_tools` 字典 |
| `types.py` | 核心数据类型：`Task`、`Session`、`TaskStatus`（状态机枚举）、`ToolResult`、`Checkpoint` 等 |
| `stream_events.py` | LLM 流式输出的内部事件 dataclass（`TextDelta`、`ToolCallReady`、`TurnDone` 等），用于 AgentLoop → BaseAgent 的事件传递 |

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

## 任务状态机

```
CREATED → PLANNING → RUNNING → COMPLETED
                   ↘ FAILED
              ↘ FAILED
                              ↘ CANCELLED
```

## 常见任务入口

- **修改 Task 状态流转规则** → `task_manager.py` 的 `_VALID_TRANSITIONS`
- **修改 LLM 调用参数/最大迭代次数** → `agent_loop.py` 的 `MAX_ITERATIONS` 和 `_run_turn()`
- **新增/修改 BaseAgent 行为** → `base_agent.py`，覆写 `system_prompt` 或 `run_streaming()`
- **调整 Worker 并发数** → `gateway/app.py` 中 `AgentPool(worker_count=N)` 的初始化
- **新增核心数据类型** → `types.py`

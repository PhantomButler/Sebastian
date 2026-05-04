# core — BaseAgent 引擎

> 上级索引：[sebastian/](../README.md)

## 模块职责

提供所有 Agent 的执行基础：任务生命周期管理、LLM 流式调用循环、工具注册与调度、Sub-Agent session 运行与僵死检测。所有 Sub-Agent 均继承 `BaseAgent`，通过 `AgentLoop` 驱动多轮工具调用，由 `TaskManager` 管理状态机流转，Sub-Agent 的独立 session 通过 `session_runner.py` 以 `asyncio.create_task` 方式启动。

## 目录结构

```
core/
├── __init__.py          # 模块入口（空导出，按需 import 子模块）
├── base_agent.py        # 所有 Agent 的抽象基类，持有 registry/session_store/event_bus，提供 run_streaming() 入口；通过 SessionStore.get_context_messages() 获取对话上下文，append_message() 写入消息
├── agent_loop.py        # 单次 LLM turn 执行循环：发请求 → 处理 tool_use → 迭代，最多 MAX_ITERATIONS=20 轮
├── session_runner.py    # Sub-Agent session 独立执行入口：run_agent_session()，供 gateway 通过 asyncio.create_task 调用
├── stalled_watchdog.py  # 僵死 session 检测：定期扫描长时间无响应的 session 并触发恢复或告警
├── task_manager.py      # Task 提交与状态机驱动：submit() 创建异步 Task，transition() 推进状态并发布 EventBus 事件
├── protocols.py         # 结构子类型 Protocol 定义：ApprovalManagerProtocol、ToolSpecProvider
├── stream_events.py     # LLM 流式输出的内部事件 dataclass（TextDelta、ToolCallReady、TurnDone 等）
├── tool.py              # @tool 装饰器系统：自动提取函数签名生成 ToolSpec，支持 review_preflight，注册到全局 _tools 字典
├── tool_context.py      # ContextVar 封装：暴露当前执行工具的 ToolCallContext，供 PolicyGate 读取
└── types.py             # 核心数据类型：Task、Session、TaskStatus 状态机枚举、ToolResult、Checkpoint 等
```

## 任务状态机

```
CREATED → PLANNING → RUNNING → COMPLETED
                   ↘ FAILED
              ↘ FAILED
                              ↘ CANCELLED
```

## Cancel 三段式生命周期

| 字典 | 语义 | 消费方 |
|------|------|--------|
| `_pending_cancel_intents[sid]` | 流尚未登记时记录的预取消 intent（REST 已返回、`_active_streams` 未写入） | `run_streaming` 登记 `_active_streams` 后立即消费 |
| `_cancel_requested[sid]` | 流运行中被取消的 intent | `run_streaming` finally 块 |
| `_completed_cancel_intents[sid]` | 流已终止的取消 intent，供外部（如 resume 工具）消费 | `consume_cancel_intent()` |

`_pending_cancel_intents` 条目带 60s TTL（`_schedule_pending_cancel_cleanup` / `_expire_pending_cancel`），防止 turn 从未真正启动时泄漏。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| Task 状态流转规则 | [task_manager.py](task_manager.py) 的 `_VALID_TRANSITIONS` |
| LLM 调用参数 / 最大迭代次数 | [agent_loop.py](agent_loop.py) 的 `MAX_ITERATIONS` |
| Anthropic / OpenAI 消息格式适配 | [agent_loop.py](agent_loop.py)，由 `provider.message_format` 自动分支 |
| 工具结果回灌给 LLM 的内容 | [agent_loop.py](agent_loop.py) 的 `_tool_result_content`；`artifact` 工具结果只能回灌轻量事实文本 |
| 多轮 thinking signature 回填逻辑 | [agent_loop.py](agent_loop.py) 处理 `ThinkingBlockStop` 的分支 |
| BaseAgent 默认行为（system_prompt、run_streaming、thinking_effort 参数） | [base_agent.py](base_agent.py) |
| 每轮 system prompt 的记忆上下文注入（`_resident_memory_section` 注入常驻快照、`_memory_section` 注入动态检索；注入顺序：base → resident → dynamic → todos） | [base_agent.py](base_agent.py) |
| 对话上下文读取（`get_context_messages`）和消息写入（`append_message`） | [base_agent.py](base_agent.py) 直接调用 `SessionStore`（不经 `EpisodicMemory`） |
| Sub-Agent session 执行入口 | [session_runner.py](session_runner.py) 的 `run_agent_session()` |
| 僵死 session 检测与恢复 | [stalled_watchdog.py](stalled_watchdog.py) |
| 新增核心数据类型 | [types.py](types.py) |
| 注册新工具（@tool 装饰器 / review_preflight） | [tool.py](tool.py)，工具实现放 `capabilities/tools/` |
| 读取当前工具执行上下文（ToolCallContext） | [tool_context.py](tool_context.py) 的 `get_tool_context()` |
| Approval / ToolSpec 跨模块接口 | [protocols.py](protocols.py) |
| LLM 流式事件结构 | [stream_events.py](stream_events.py) |

## 公开接口（其他模块如何使用）

```python
# 继承 BaseAgent 实现自定义 Agent
from sebastian.core.base_agent import BaseAgent

# 提交任务并驱动状态机
from sebastian.core.task_manager import TaskManager
await task_manager.submit(task, async_fn)

# Sub-Agent session 执行（供 gateway 通过 asyncio.create_task 调用）
from sebastian.core.session_runner import run_agent_session
await run_agent_session(agent, session, goal, session_store, event_bus)

# 注册工具（capabilities/tools/ 中使用）
from sebastian.core.tool import tool
@tool(description="...")
async def my_tool(...) -> ToolResult: ...

# 核心类型
from sebastian.core.types import Task, TaskStatus, Session, ToolResult
```

---

> 修改本目录或模块后，请同步更新此 README。

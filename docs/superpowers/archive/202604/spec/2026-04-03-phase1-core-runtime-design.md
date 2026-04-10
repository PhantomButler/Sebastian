# Phase 1 核心运行时设计

**版本**：v1.0  
**日期**：2026-04-03  
**状态**：已确认，待实施  
**关联**：`2026-04-01-sebastian-architecture-design.md` Phase 1 待完成部分

---

## 1. 背景与范围

本文档补充 Phase 1 的核心运行时细节，覆盖以下决策：

1. **AgentLoop Streaming** — 从全量返回改为 async generator，yield 结构化流事件
2. **SSE 事件协议** — block 级完整事件表，解决 OpenJax 多段 thinking 流写入同一卡片的问题
3. **BaseAgent Streaming + 打断机制** — cancel + partial + 分发表优化
4. **Task 状态机** — 完整转换规则与非法转换保护
5. **AgentPool** — worker 槽位管理，每个 agent_type 最多 3 个并发 worker
6. **REST API** — 以 Session 为中心的完整路由设计

---

## 2. 核心架构决策

### 2.1 流式输出通道

**决策：独立 SSE 通道（方案 A）**

- `POST /turns` 立即返回 `{ session_id, ts }`，不等 LLM 响应
- LLM token 和所有运行时事件统一通过 SSE 长连接推送
- App 只需维护一条 SSE 连接，离线/后台场景靠 FCM 补位

**放弃的方案**：HTTP streaming response（每次 turn 新开流式请求，App 端维护成本高，后台被 OS 断开）

### 2.2 AgentLoop 与 BaseAgent 职责划分

**决策：分层执行（方案 B）**

```
AgentLoop（发动机）
└── 职责：与 LLM 的来回、流式解析、yield 结构化事件
└── 不持有：EventBus、SessionStore、CapabilityRegistry

BaseAgent（协调层，每个 agent 实例持有一个 loop）
└── 职责：加载历史、消费 loop yield、执行工具、publish 事件、写持久化
└── 持有：AgentLoop、EventBus、SessionStore、CapabilityRegistry
```

AgentLoop 无副作用，可独立测试（直接消费 generator，无需 mock）。

### 2.3 打断机制

**决策：cancel stream + keep partial + restart**

Sebastian 定位是对话优先、任务下放，自身极少长时间霸占 LLM 推理。打断场景基本只发生在"正在生成回复时用户又说话"，因此：

- 新消息到来 → cancel 当前 asyncio Task
- partial 内容写入 history（作为被打断的 assistant 消息）
- 以新 context（含 partial）重新请求 LLM
- LLM 自然理解被打断语义，无需额外提示工程

**放弃的方案**：fork/ghost 分身（过度设计，Sebastian 自身任务量不支撑这个复杂度）

---

## 3. AgentLoop Streaming

### 3.1 内部流事件类型

放置于 `sebastian/core/stream_events.py`：

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Union

@dataclass
class ThinkingBlockStart:
    block_id: str

@dataclass
class ThinkingDelta:
    block_id: str
    delta: str

@dataclass
class ThinkingBlockStop:
    block_id: str

@dataclass
class TextBlockStart:
    block_id: str

@dataclass
class TextDelta:
    block_id: str
    delta: str

@dataclass
class TextBlockStop:
    block_id: str

@dataclass
class ToolCallBlockStart:
    block_id: str
    tool_id: str      # Anthropic 返回的 tool use id
    name: str

@dataclass
class ToolCallReady:
    block_id: str
    tool_id: str
    name: str
    inputs: dict[str, Any]

@dataclass
class ToolResult:
    tool_id: str
    name: str
    ok: bool
    output: Any
    error: str | None

@dataclass
class TurnDone:
    full_text: str    # 拼接的完整回复内容

LLMStreamEvent = Union[
    ThinkingBlockStart, ThinkingDelta, ThinkingBlockStop,
    TextBlockStart, TextDelta, TextBlockStop,
    ToolCallBlockStart, ToolCallReady, ToolResult,
    TurnDone,
]
```

### 3.2 block_id 规范

格式：`b{iteration}_{block_index}`

- `iteration`：第几轮 LLM 请求（0 起始，每次 tool_use 后 +1）
- `block_index`：本轮第几个 content block（0 起始）
- 示例：`b0_0`（第一轮第一个 block），`b1_2`（第二轮第三个 block）
- **前端只用 block_id 作为卡片 key，不解析其格式**

同一个 block_id 的 start/delta/stop 必定属于同一张卡片，解决多段 thinking 流写入同一卡片的问题。

### 3.3 AgentLoop.stream() 接口

```python
class AgentLoop:
    async def stream(
        self,
        system: str,
        messages: list[dict],
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        """
        Yields LLMStreamEvent 序列。
        ToolCallReady 事件支持 send() 回注 ToolResult，
        loop 收到后继续下一轮 LLM 请求。
        """
```

**工具结果回注**（双向 generator）：

```python
# BaseAgent 消费端
gen = self._loop.stream(system, messages)
send_val = None
while True:
    event = await gen.asend(send_val)
    send_val = None
    if isinstance(event, ToolCallReady):
        result = await self._registry.call(event.name, **event.inputs)
        send_val = result   # 下一次 asend 把结果注回 loop
    ...
```

---

## 4. SSE 事件协议

### 4.1 完整事件表

| 事件类型 | 触发时机 | 核心字段 |
|---|---|---|
| `turn.received` | 用户消息进入 | `session_id`, `agent_id` |
| `thinking_block.start` | thinking block 开始 | `session_id`, `block_id` |
| `turn.thinking_delta` | 每个 thinking token | `session_id`, `block_id`, `delta` |
| `thinking_block.stop` | thinking block 结束 | `session_id`, `block_id` |
| `text_block.start` | text block 开始 | `session_id`, `block_id` |
| `turn.delta` | 每个文字 token | `session_id`, `block_id`, `delta` |
| `text_block.stop` | text block 结束 | `session_id`, `block_id` |
| `tool_block.start` | tool call 开始（name 已知） | `session_id`, `block_id`, `tool_id`, `name` |
| `tool_block.stop` | tool inputs 完整 | `session_id`, `block_id`, `tool_id`, `name`, `inputs` |
| `tool.running` | 工具开始执行 | `session_id`, `tool_id`, `name` |
| `tool.executed` | 工具执行成功 | `session_id`, `tool_id`, `name`, `result_summary` |
| `tool.failed` | 工具执行失败 | `session_id`, `tool_id`, `name`, `error` |
| `turn.response` | 整个 turn 正常结束 | `session_id`, `content`, `interrupted: false` |
| `turn.interrupted` | 用户打断，生成取消 | `session_id`, `partial_content` |
| `task.created` | task 提交 | `session_id`, `task_id`, `goal`, `agent_id` |
| `task.started` | task 开始执行 | `session_id`, `task_id` |
| `task.completed` | task 完成 | `session_id`, `task_id` |
| `task.failed` | task 失败 | `session_id`, `task_id`, `error` |
| `task.cancelled` | task 取消 | `session_id`, `task_id` |
| `approval.requested` | 需要用户审批 | `session_id`, `approval_id`, `description`, `options` |
| `approval.granted` | 用户批准 | `approval_id` |
| `approval.denied` | 用户拒绝 | `approval_id` |

### 4.2 SSE 帧格式

```
id: 42
data: {"type":"turn.delta","data":{"session_id":"...","block_id":"b0_1","delta":"好的"},"ts":"2026-04-03T10:00:00Z"}

```

- `id`：每条连接独立自增序号
- 断线重连带 `Last-Event-ID` header，服务端从缓冲重放
- 服务端维护最近 **500 条**事件滑动缓冲（内存）

### 4.3 完整 turn 事件序列示例

```
turn.received          {session_id, agent_id: "sebastian_01"}

thinking_block.start   {session_id, block_id: "b0_0"}
turn.thinking_delta    {session_id, block_id: "b0_0", delta: "用户想要..."}
turn.thinking_delta    {session_id, block_id: "b0_0", delta: "先查一下"}
thinking_block.stop    {session_id, block_id: "b0_0"}

text_block.start       {session_id, block_id: "b0_1"}
turn.delta             {session_id, block_id: "b0_1", delta: "好的，我来"}
turn.delta             {session_id, block_id: "b0_1", delta: "帮你查一下"}
text_block.stop        {session_id, block_id: "b0_1"}

tool_block.start       {session_id, block_id: "b0_2", tool_id: "tu_01", name: "web_search"}
tool_block.stop        {session_id, block_id: "b0_2", tool_id: "tu_01", inputs: {"query":"港股"}}
tool.running           {session_id, tool_id: "tu_01", name: "web_search"}
tool.executed          {session_id, tool_id: "tu_01", result_summary: "找到5条结果"}

thinking_block.start   {session_id, block_id: "b1_0"}
turn.thinking_delta    {session_id, block_id: "b1_0", delta: "结果显示..."}
thinking_block.stop    {session_id, block_id: "b1_0"}

text_block.start       {session_id, block_id: "b1_1"}
turn.delta             {session_id, block_id: "b1_1", delta: "根据最新数据..."}
text_block.stop        {session_id, block_id: "b1_1"}

turn.response          {session_id, content: "...", interrupted: false}
```

### 4.4 打断事件序列

```
turn.received          {session_id}
text_block.start       {session_id, block_id: "b0_0"}
turn.delta             {session_id, block_id: "b0_0", delta: "好的，我来分析"}
                       ← 新消息到来，cancel stream
turn.interrupted       {session_id, partial_content: "好的，我来分析"}
turn.received          {session_id}   ← 新 turn 开始
...
```

### 4.5 前端使用约定

- 每个 `block_id` 对应一张卡片（thinking 折叠卡、tool 折叠卡、text 气泡）
- `turn.response.content` 是唯一可信的完整内容，流式显示用 delta 拼接，存储以 `turn.response` 为准
- App 同一时间只订阅一条 SSE：Sebastian 页用全局流，进入 SubAgent 详情页切换到 session 级别流，退出时断开

---

## 5. BaseAgent Streaming + 打断机制

### 5.1 BaseAgent 新增字段

```python
class BaseAgent(ABC):
    def __init__(self, registry, session_store, event_bus, model=None):
        ...
        self._active_stream: asyncio.Task | None = None  # 当前流式任务
```

### 5.2 run_streaming() 流程

```
1. 若 _active_stream 未完成 → cancel，等 CancelledError 处理完毕
2. publish turn.received
3. 加载 episodic history（最近 20 条），追加用户消息，持久化
4. asyncio.create_task(_stream_inner(...)) → 赋给 _active_stream
5. await _active_stream（gateway 层等待完成后返回 HTTP response）
```

### 5.3 _stream_inner() 优化实现

使用**分发表**替代 if-else 链，O(1) 类型查表：

```python
_EVENT_MAP: ClassVar[dict[type, EventType]] = {
    ThinkingBlockStart: EventType.THINKING_BLOCK_START,
    ThinkingDelta:      EventType.TURN_THINKING_DELTA,
    ThinkingBlockStop:  EventType.THINKING_BLOCK_STOP,
    TextBlockStart:     EventType.TEXT_BLOCK_START,
    TextDelta:          EventType.TURN_DELTA,
    TextBlockStop:      EventType.TEXT_BLOCK_STOP,
    ToolCallBlockStart: EventType.TOOL_BLOCK_START,
}

async def _stream_inner(self, messages, session_id, task_id) -> None:
    full_text = ""
    gen = self._loop.stream(self.system_prompt, messages)
    send_val: ToolResult | None = None
    try:
        while True:
            try:
                event = await gen.asend(send_val)
                send_val = None
            except StopAsyncIteration:
                break

            if isinstance(event, ToolCallReady):
                # 工具执行（有副作用 + send_val 回注）
                ...
                send_val = result
                continue

            if isinstance(event, TurnDone):
                # 持久化 + publish turn.response
                return

            if isinstance(event, TextDelta):
                full_text += event.delta

            if evt_type := _EVENT_MAP.get(type(event)):
                await self._publish(session_id, evt_type, dataclasses.asdict(event))

    except asyncio.CancelledError:
        # partial 写入 history，publish turn.interrupted
        raise  # 必须重新 raise
```

**性能说明**：真正瓶颈是每个 delta 的 `await publish()`（队列写入），分发表优化解决 CPU 分支开销。若将来 delta 频率成为瓶颈，可在 SSEManager 层做微批（5ms 内合并），但 Phase 1 无需处理。

---

## 6. Task 状态机

### 6.1 状态转换图

```
CREATED → PLANNING → RUNNING → COMPLETED
                   ↘ FAILED    ↘ FAILED
                               ↘ CANCELLED
```

Phase 1 中 `PLANNING` 直通 `RUNNING`（Planner 未实现），接口预留。

### 6.2 合法转换表

| 当前状态 | 可转换到 |
|---|---|
| `CREATED` | `PLANNING` |
| `PLANNING` | `RUNNING`, `FAILED` |
| `RUNNING` | `COMPLETED`, `FAILED`, `CANCELLED` |
| `COMPLETED` | —（终止态） |
| `FAILED` | —（终止态） |
| `CANCELLED` | —（终止态） |

非法转换抛 `InvalidTaskTransitionError`，不静默忽略。

### 6.3 状态 → 事件映射

| 状态 | 发布事件 |
|---|---|
| `PLANNING` | `task.planning_started` |
| `RUNNING` | `task.started` |
| `COMPLETED` | `task.completed` |
| `FAILED` | `task.failed` |
| `CANCELLED` | `task.cancelled` |

### 6.4 Session 计数维护

- 进入 `PLANNING`：`session.task_count += 1`，`active_task_count += 1`
- 进入 `COMPLETED / FAILED / CANCELLED`：`active_task_count -= 1`
- 每次变更同步写 `index.json`

---

## 7. AgentPool — Worker 槽位管理

### 7.1 设计决策

每个 `agent_type` 有固定的 3 个具名 worker（持久 worker 方案），理由：

- App 需要展示具体 worker 身份（stock_01 在做什么）
- 未来 Phase 2 可给每个 worker 建立专属 episodic memory
- 实现复杂度与临时实例方案相当

### 7.2 Worker 命名规范

```
{agent_type}_{序号两位}
示例：stock_01, stock_02, stock_03
      code_01, code_02, code_03
      sebastian_01（Sebastian 只有 1 个 worker）
```

### 7.3 AgentPool 接口

```python
class WorkerStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"

class AgentPool:
    MAX_WORKERS: int = 3

    async def acquire(self) -> str:
        """获取空闲 worker_id，无空闲时挂起等待。"""

    def release(self, worker_id: str) -> None:
        """释放 worker，有排队任务则直接转交。"""

    def status(self) -> dict[str, WorkerStatus]:
        """返回所有 worker 当前状态。"""

    @property
    def queue_depth(self) -> int:
        """当前排队等待的任务数。"""
```

### 7.4 Session 模型更新

```python
class Session(BaseModel):
    agent_type: str    # "stock"（agent 类型）
    agent_id: str      # "stock_01"（具体 worker）
    ...
```

原 `agent: str` 字段拆分为 `agent_type + agent_id`，所有相关路由、存储、事件同步更新。

---

## 8. REST API

### 8.1 路由总表

```
# 认证
POST   /api/v1/auth/login

# 对话（Sebastian 主入口）
POST   /api/v1/turns

# Session
GET    /api/v1/sessions                                    # 全局索引
GET    /api/v1/sessions/{session_id}                       # 详情（meta + messages）
GET    /api/v1/agents/{agent_type}/sessions                # 指定 agent_type 的所有 sessions
GET    /api/v1/agents/{agent_type}/workers/{agent_id}/sessions  # 指定 worker 的 sessions

# Turn（SubAgent 纠偏 / 继续对话）
POST   /api/v1/sessions/{session_id}/turns

# Task
GET    /api/v1/sessions/{session_id}/tasks
GET    /api/v1/sessions/{session_id}/tasks/{task_id}
POST   /api/v1/sessions/{session_id}/tasks/{task_id}/cancel

# 审批
GET    /api/v1/approvals
POST   /api/v1/approvals/{approval_id}/grant
POST   /api/v1/approvals/{approval_id}/deny

# SSE
GET    /api/v1/stream                          # 全局事件流
GET    /api/v1/sessions/{session_id}/stream    # 单 session 事件流

# 系统
GET    /api/v1/agents                          # agent 列表 + worker 状态
GET    /api/v1/health
```

### 8.2 关键端点 Request/Response

**`POST /api/v1/turns`**

```json
// Request
{ "content": "帮我分析港股近期走势", "session_id": "..." }

// Response 200（立即返回，内容走 SSE）
{ "session_id": "2026-04-03T10-30-00_abc123", "ts": "2026-04-03T10:30:01Z" }
```

**`GET /api/v1/sessions`**

```json
// Query: agent_type=stock&status=active&limit=20&offset=0
{
  "sessions": [
    {
      "id": "...", "agent_type": "stock", "agent_id": "stock_01",
      "title": "分析港股近期走势", "status": "active",
      "task_count": 2, "active_task_count": 1, "updated_at": "..."
    }
  ],
  "total": 42
}
```

**`GET /api/v1/sessions/{session_id}`**

```json
{
  "id": "...", "agent_type": "stock", "agent_id": "stock_01",
  "title": "...", "status": "active",
  "task_count": 2, "active_task_count": 1,
  "created_at": "...", "updated_at": "...",
  "messages": [
    { "role": "user",      "content": "帮我分析港股", "ts": "..." },
    { "role": "assistant", "content": "好的...",      "ts": "..." }
  ]
}
```

**`GET /api/v1/agents`**

```json
{
  "agents": [
    {
      "agent_type": "sebastian", "description": "总管家",
      "workers": [
        { "agent_id": "sebastian_01", "status": "idle", "session_id": null }
      ],
      "queue_depth": 0
    },
    {
      "agent_type": "stock", "description": "金融顾问",
      "workers": [
        { "agent_id": "stock_01", "status": "busy", "session_id": "..." },
        { "agent_id": "stock_02", "status": "busy", "session_id": "..." },
        { "agent_id": "stock_03", "status": "idle", "session_id": null }
      ],
      "queue_depth": 2
    }
  ]
}
```

**`POST /api/v1/sessions/{session_id}/tasks/{task_id}/cancel`**

```json
// Response 200
{ "ok": true }

// Response 409
{ "detail": "Task is not cancellable (status: completed)", "code": "INVALID_TASK_TRANSITION" }
```

### 8.3 错误格式

所有 4xx/5xx 统一格式，通过 FastAPI exception handler 集中处理：

```json
{ "detail": "...", "code": "MACHINE_READABLE_CODE" }
```

### 8.4 SSE 流选择策略

| App 场景 | 使用端点 |
|---|---|
| Sebastian 主页 | `GET /api/v1/stream`（全局） |
| SubAgent 详情页 | `GET /api/v1/sessions/{id}/stream`（单 session） |
| 退出详情页 | 断开连接 |
| 重新进入详情页 | 重连，带 `Last-Event-ID`，服务端重放缓冲 |

---

## 9. 文件变更清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `sebastian/core/stream_events.py` | 新增 | LLMStreamEvent 所有类型 |
| `sebastian/core/agent_loop.py` | 重构 | `run()` → `stream()` async generator |
| `sebastian/core/base_agent.py` | 重构 | 新增 `run_streaming()`，打断机制 |
| `sebastian/core/types.py` | 修改 | Session 拆分 `agent` → `agent_type + agent_id` |
| `sebastian/core/task_manager.py` | 修改 | `_transition()` 统一状态变更，加合法性校验 |
| `sebastian/core/agent_pool.py` | 新增 | AgentPool worker 槽位管理 |
| `sebastian/protocol/events/types.py` | 修改 | 补全 block 级事件类型 |
| `sebastian/gateway/routes/turns.py` | 修改 | 非阻塞返回，去掉 await |
| `sebastian/gateway/routes/sessions.py` | 修改 | 路由更新，支持 agent_type/agent_id 查询 |
| `sebastian/gateway/routes/agents.py` | 修改 | 返回 worker 状态和 queue_depth |
| `sebastian/gateway/sse.py` | 修改 | 支持 session 级别过滤，event id + 缓冲重放 |
| `tests/unit/test_agent_loop.py` | 新增/重构 | 基于 generator 的单元测试 |
| `tests/unit/test_agent_pool.py` | 新增 | pool acquire/release/排队测试 |
| `tests/unit/test_task_manager.py` | 修改 | 补全状态转换测试 |

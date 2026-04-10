---
version: "1.0"
last_updated: 2026-04-10
status: implemented
---

# 核心运行时设计

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 核心架构决策

### 1.1 流式输出通道

**决策：独立 SSE 通道**

- `POST /turns` 立即返回 `{ session_id, ts }`，不等 LLM 响应
- LLM token 和所有运行时事件统一通过 SSE 长连接推送
- App 只需维护一条 SSE 连接，后台/熄屏场景靠 FCM 补位

### 1.2 AgentLoop 与 BaseAgent 职责划分

**决策：分层执行**

```
AgentLoop（发动机）
└── 职责：与 LLM 的来回、流式解析、yield 结构化事件
└── 不持有：EventBus、SessionStore、CapabilityRegistry

BaseAgent（协调层）
└── 职责：加载历史、消费 loop yield、执行工具、publish 事件、写持久化
└── 持有：AgentLoop、EventBus、SessionStore、CapabilityRegistry
```

AgentLoop 无副作用，可独立测试（直接消费 generator，无需 mock）。

### 1.3 打断机制

**决策：cancel stream + keep partial + restart**

- 新消息到来 → cancel 当前 asyncio Task
- partial 内容写入 history（作为被打断的 assistant 消息）
- 以新 context（含 partial）重新请求 LLM
- LLM 自然理解被打断语义

---

## 2. AgentLoop Streaming

### 2.1 内部流事件类型

文件：`sebastian/core/stream_events.py`

```python
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
    thinking: str              # 完整 thinking 文本
    signature: str | None      # Anthropic 签名（多轮回填必需）

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
    text: str                  # 完整文本

@dataclass
class ToolCallBlockStart:
    block_id: str
    tool_id: str               # Anthropic 返回的 tool use id
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
    full_text: str             # 拼接的完整回复内容

LLMStreamEvent = Union[
    ThinkingBlockStart, ThinkingDelta, ThinkingBlockStop,
    TextBlockStart, TextDelta, TextBlockStop,
    ToolCallBlockStart, ToolCallReady, ToolResult,
    TurnDone,
]
```

### 2.2 block_id 规范

格式：`b{iteration}_{block_index}`

- `iteration`：第几轮 LLM 请求（0 起始，每次 tool_use 后 +1）
- `block_index`：本轮第几个 content block（0 起始）
- 示例：`b0_0`（第一轮第一个 block），`b1_2`（第二轮第三个 block）
- **前端只用 block_id 作为卡片 key，不解析其格式**

同一个 block_id 的 start/delta/stop 必定属于同一张卡片。

### 2.3 AgentLoop.stream() 接口

```python
class AgentLoop:
    async def stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        task_id: str | None = None,
        thinking_effort: str | None = None,
    ) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
        """
        Yields LLMStreamEvent 序列。
        ToolCallReady 事件支持 send() 回注 ToolResult，
        loop 收到后继续下一轮 LLM 请求。
        最大迭代次数：MAX_ITERATIONS = 20。
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
        send_val = result
    ...
```

**多轮 thinking 回填**：

AgentLoop 在 tool_use 后重新请求 LLM 时，需要将上一轮的 thinking block 原样带回。Anthropic Extended Thinking 要求 thinking block 包含 `signature` 字段：

```python
if isinstance(event, ThinkingBlockStop):
    block_dict = {"type": "thinking", "thinking": event.thinking}
    if event.signature is not None:
        block_dict["signature"] = event.signature
    assistant_blocks.append(block_dict)
```

OpenAI 路径不需要 signature。

---

## 3. BaseAgent Streaming + 打断机制

### 3.1 关键字段

```python
class BaseAgent(ABC):
    _active_streams: dict[str, asyncio.Task]   # session_id → 当前流式任务
    _current_depth: dict[str, int]             # session_id → depth
```

### 3.2 run_streaming() 流程

1. 若该 session 的 `_active_stream` 未完成 → cancel，等 CancelledError 处理完毕
2. publish `turn.received`
3. 加载历史消息，追加用户消息，持久化
4. `asyncio.create_task(_stream_inner(...))` → 赋给 `_active_streams[session_id]`
5. await 该 task

### 3.3 _stream_inner() 分发表实现

使用分发表替代 if-else 链，O(1) 类型查表：

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
```

CancelledError 时：partial 写入 history，publish `turn.interrupted`，然后重新 raise。

---

## 4. Task 状态机

### 4.1 状态转换图

```
CREATED → PLANNING → RUNNING → COMPLETED
                   ↘ FAILED    ↘ FAILED
                               ↘ CANCELLED
```

### 4.2 合法转换表

| 当前状态 | 可转换到 |
|----------|---------|
| `CREATED` | `PLANNING` |
| `PLANNING` | `RUNNING`, `FAILED` |
| `RUNNING` | `COMPLETED`, `FAILED`, `CANCELLED` |
| `COMPLETED` | — |
| `FAILED` | — |
| `CANCELLED` | — |

非法转换抛 `InvalidTaskTransitionError`，不静默忽略。

### 4.3 状态 → 事件映射

| 状态 | 发布事件 |
|------|---------|
| `PLANNING` | `task.planning_started` |
| `RUNNING` | `task.started` |
| `COMPLETED` | `task.completed` |
| `FAILED` | `task.failed` |
| `CANCELLED` | `task.cancelled` |

### 4.4 Session 计数维护

- 进入 `PLANNING`：`session.task_count += 1`，`active_task_count += 1`
- 进入 `COMPLETED / FAILED / CANCELLED`：`active_task_count -= 1`
- 每次变更同步写 `index.json`

---

## 5. SSE 事件协议

### 5.1 完整事件表

| 事件类型 | 触发时机 | 核心字段 |
|----------|---------|---------|
| `turn.received` | 用户消息进入 | `session_id` |
| `thinking_block.start` | thinking block 开始 | `session_id`, `block_id` |
| `turn.thinking_delta` | 每个 thinking token | `session_id`, `block_id`, `delta` |
| `thinking_block.stop` | thinking block 结束 | `session_id`, `block_id` |
| `text_block.start` | text block 开始 | `session_id`, `block_id` |
| `turn.delta` | 每个文字 token | `session_id`, `block_id`, `delta` |
| `text_block.stop` | text block 结束 | `session_id`, `block_id` |
| `tool_block.start` | tool call 开始 | `session_id`, `block_id`, `tool_id`, `name` |
| `tool_block.stop` | tool inputs 完整 | `session_id`, `block_id`, `tool_id`, `name`, `inputs` |
| `tool.running` | 工具开始执行 | `session_id`, `tool_id`, `name` |
| `tool.executed` | 工具执行成功 | `session_id`, `tool_id`, `name`, `result_summary` |
| `tool.failed` | 工具执行失败 | `session_id`, `tool_id`, `name`, `error` |
| `turn.response` | 整个 turn 正常结束 | `session_id`, `content` |
| `turn.interrupted` | 用户打断 | `session_id`, `partial_content` |
| `task.created` | task 提交 | `session_id`, `task_id`, `goal` |
| `task.started` | task 开始 | `session_id`, `task_id` |
| `task.completed` | task 完成 | `session_id`, `task_id` |
| `task.failed` | task 失败 | `session_id`, `task_id`, `error` |
| `task.cancelled` | task 取消 | `session_id`, `task_id` |
| `approval.requested` | 需要审批 | `session_id`, `approval_id`, `description` |
| `approval.granted` | 用户批准 | `approval_id` |
| `approval.denied` | 用户拒绝 | `approval_id` |

### 5.2 SSE 帧格式

```
id: 42
data: {"type":"turn.delta","data":{"session_id":"...","block_id":"b0_1","delta":"好的"},"ts":"2026-04-03T10:00:00Z"}

```

- `id`：每条连接独立自增序号
- 断线重连带 `Last-Event-ID` header，服务端从缓冲重放
- 服务端维护最近 **500 条**事件滑动缓冲（内存）

### 5.3 完整 turn 事件序列示例

```
turn.received          {session_id}

thinking_block.start   {session_id, block_id: "b0_0"}
turn.thinking_delta    {session_id, block_id: "b0_0", delta: "用户想要..."}
thinking_block.stop    {session_id, block_id: "b0_0"}

text_block.start       {session_id, block_id: "b0_1"}
turn.delta             {session_id, block_id: "b0_1", delta: "好的，我来"}
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

turn.response          {session_id, content: "..."}
```

### 5.4 打断事件序列

```
turn.received          {session_id}
text_block.start       {session_id, block_id: "b0_0"}
turn.delta             {session_id, block_id: "b0_0", delta: "好的，我来分析"}
                       ← 新消息到来，cancel stream
turn.interrupted       {session_id, partial_content: "好的，我来分析"}
turn.received          {session_id}   ← 新 turn 开始
...
```

### 5.5 前端使用约定

- 每个 `block_id` 对应一张卡片（thinking 折叠卡、tool 折叠卡、text 气泡）
- `turn.response.content` 是唯一可信的完整内容，流式用 delta 拼接显示，存储以 `turn.response` 为准
- App 同一时间只订阅一条 SSE：Sebastian 页用全局流，进入 SubAgent 详情页切到 session 级流

---

## 6. REST API 路由总表

```
# 认证
POST   /api/v1/auth/login

# 对话（Sebastian 主入口）
POST   /api/v1/turns

# Session
GET    /api/v1/sessions                                    # 全局索引
GET    /api/v1/sessions/{session_id}                       # 详情
GET    /api/v1/agents/{agent_type}/sessions                # 指定 agent_type 的所有 sessions

# 为组长创建新对话
POST   /api/v1/agents/{agent_type}/sessions

# Turn（SubAgent 对话 / 纠偏）
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
GET    /api/v1/stream                                      # 全局事件流
GET    /api/v1/sessions/{session_id}/stream                # 单 session 事件流

# LLM Provider
GET    /api/v1/llm/providers
POST   /api/v1/llm/providers
PUT    /api/v1/llm/providers/{id}
DELETE /api/v1/llm/providers/{id}
POST   /api/v1/llm/providers/{id}/set-default

# 调试
GET    /api/debug/logging
PATCH  /api/debug/logging

# 系统
GET    /api/v1/agents                                      # agent 列表 + 状态
GET    /api/v1/health
```

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

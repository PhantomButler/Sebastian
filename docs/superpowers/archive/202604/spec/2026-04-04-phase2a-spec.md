# Phase 2a 详细设计：完整链路（Multi-Agent + LLM Provider 管理）

**版本**：v1.0
**日期**：2026-04-04
**状态**：已确认，待实施
**关联**：`2026-04-01-sebastian-architecture-design.md` Phase 2a

---

## 1. 背景与范围

Phase 1 已完成单 Agent 基础运行时。Phase 2a 目标是跑通完整端到端链路：

- Sebastian 能将任务委派给 Sub-Agent 执行
- LLM provider 可配置、可切换，不再硬编码 Anthropic
- Sub-Agent 通过目录扫描自动注册，无需改核心代码
- Skills 以 Markdown 指令文件形式扫描注册，支持用户目录外置扩展
- Android App SubAgents 页展示 A2A 任务流，Settings 页接入 LLM Provider 管理

**不在本 Phase 范围：**
- Memory 系统（Phase 2b）
- Code Agent / StockAgent 完整实现（Phase 2b）
- 语音、iOS、FCM 推送（Phase 3）
- Session 详情页 block 级渲染、ApprovalModal（Phase 2b App 对接）

---

## 2. 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| A2A 队列结构 | per-agent-type `asyncio.Queue` | stock burst 不阻塞 life，与 AgentPool 模型一一对应 |
| A2A 结果回传 | per-task `asyncio.Future` | Sebastian 可 await 单个任务结果，不阻塞其他对话 |
| Agent Router | `delegate_to_agent` tool call，LLM 决策 | 零额外 LLM 调用，路由逻辑内嵌 Sebastian system prompt |
| LLM Provider API key 存储 | SQLite 明文 | 自托管个人系统，SQLite 与 .env 安全边界相同，加密收益接近零 |
| Skills 格式 | `SKILL.md` + frontmatter（与 Claude Code 一致） | 纯文本，LLM 可读执行，无需程序化步骤引擎 |
| Skills/Agents 扩展目录 | `{DATA_DIR}/extensions/skills/` + `{DATA_DIR}/extensions/agents/` | 用户可在不改源码的情况下扩展，同名时用户目录优先 |
| 实施策略 | 薄切片优先 | 最早验证完整链路（LLM Provider → A2A → App），风险提前暴露 |

---

## 3. LLM Provider 管理

### 3.1 目录结构

```
sebastian/llm/
  __init__.py
  provider.py          # LLMProvider 抽象基类
  anthropic.py         # Anthropic SDK 适配
  openai_compat.py     # OpenAI /v1/chat/completions 适配（兼容所有兼容端点）
  registry.py          # 从 DB 加载，提供 get_provider() 接口
```

### 3.2 数据模型

新增到 `sebastian/store/models.py`：

```python
class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)                  # 用户命名，如 "Claude Opus 家用"
    provider_type: Mapped[str] = mapped_column(String, nullable=False)         # "anthropic" | "openai"
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)        # None 则用 SDK 默认
    api_key: Mapped[str] = mapped_column(String, nullable=False)               # 明文存储
    model: Mapped[str] = mapped_column(String, nullable=False)                 # "claude-opus-4-6" / "gpt-4o"
    thinking_format: Mapped[str | None] = mapped_column(String, nullable=True) # 见下方说明
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 3.3 LLMProvider 抽象接口

`sebastian/llm/provider.py`：

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from sebastian.core.stream_events import LLMStreamEvent

class LLMProvider(ABC):
    """单次 LLM 调用抽象。多轮循环逻辑在 AgentLoop，不在此处。"""

    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AsyncGenerator[LLMStreamEvent, None]: ...
```

**职责边界**：`LLMProvider.stream()` 只负责单次 LLM 调用，将原始 SDK 事件映射为 `LLMStreamEvent`。多轮循环（工具调用 → 追加结果 → 再次请求）由 `AgentLoop` 管理，不下沉到 provider。

### 3.4 Anthropic 适配（`anthropic.py`）

封装 `anthropic.AsyncAnthropic`，将 `content_block_start/delta/stop` 原始事件映射为 `LLMStreamEvent`。

**需同步更新 `stream_events.py`**：`ThinkingBlockStop` 和 `TextBlockStop` 补充内容字段，使 AgentLoop 能从事件本身重建 `assistant_content`，不再依赖 `stream.current_message`：

```python
@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str    # 新增：完整 thinking 文本

@dataclass
class TextBlockStop:
    block_id: str
    text: str        # 新增：完整文本
```

### 3.5 OpenAI 兼容适配（`openai_compat.py`）

通过 `openai.AsyncOpenAI(base_url=..., api_key=...)` 调用，将 OpenAI streaming chunks 映射为相同的 `LLMStreamEvent`。兼容任何实现 `/v1/chat/completions` 的端点（本地模型、代理等）。

**`thinking_format` 字段说明**（`LLMProviderRecord` 字段，控制 thinking 提取方式）：

| 值 | 适用场景 | 处理方式 |
|----|---------|---------|
| `None`（默认） | 标准 OpenAI / GPT 系列 | 不提取 thinking，只 yield text/tool events |
| `"reasoning_content"` | DeepSeek API、支持 `reasoning_content` 的端点 | 检测 `delta.reasoning_content` 字段，yield `ThinkingBlockStart/Delta/Stop` |
| `"think_tags"` | llama.cpp 本地部署（QwQ、DeepSeek-R1 等） | 缓冲文本流，在 `<think>` 与 `</think>` 之间 yield ThinkingDelta，其余 yield TextDelta |

Anthropic 适配不受此字段影响，始终走 SDK 原生 thinking 事件。

`openai_compat.py` 根据 `thinking_format` 分支处理，新增格式时只需加枚举分支，不改接口。App Settings LLM Provider 表单新增 `thinking_format` 下拉选项（None / reasoning_content / think_tags）。

### 3.6 LLMProviderRegistry（`registry.py`）

```python
class LLMProviderRegistry:
    async def get_provider(
        self,
        provider_type: str | None = None,
        model: str | None = None,
    ) -> LLMProvider:
        """
        优先级：
        1. provider_type + model 精确匹配
        2. provider_type 匹配，取 is_default=True 的记录
        3. 全局 is_default=True 的记录
        4. 抛出 ConfigError（无可用 provider）
        """
```

启动时从 DB 加载所有 provider 记录，缓存实例（避免重复创建 SDK client）。DB 变更时支持热重载（通过 API 增删改后刷新缓存）。

### 3.7 AgentLoop 改造

构造器签名变更：

```python
# 之前
def __init__(self, client: Any, registry: CapabilityRegistry, model: str, ...)

# 之后
def __init__(self, provider: LLMProvider, registry: CapabilityRegistry, ...)
# model 和 max_tokens 由调用方（BaseAgent）通过 provider 实例携带或作为参数传入 stream()
```

内层循环替换：

```python
# 之前
async with self._client.messages.stream(**kwargs) as stream:
    async for raw in stream:
        ...  # 手动解析 Anthropic 原始事件

# 之后
async for event in self._provider.stream(system, messages, tools, model, max_tokens):
    ...  # 直接处理 LLMStreamEvent，逻辑不变
```

从 `TextBlockStop.text` / `ThinkingBlockStop.thinking` 取内容重建 `assistant_content`，移除对 `stream.current_message.content[block_index]` 的依赖。

### 3.8 BaseAgent 集成

`BaseAgent.__init__()` 从 `LLMProviderRegistry` 获取 provider 并注入 `AgentLoop`：

```python
provider = await llm_registry.get_provider(
    provider_type=self._agent_config.llm_provider_type,  # 来自 manifest.toml [llm]
    model=self._agent_config.llm_model,
)
self._loop = AgentLoop(provider=provider, registry=self._capability_registry)
```

### 3.9 Gateway 路由

新增 `sebastian/gateway/routes/llm_providers.py`：

```
GET    /api/v1/llm/providers              # 列表（api_key 返回 "***"）
POST   /api/v1/llm/providers              # 新增
PUT    /api/v1/llm/providers/{id}         # 修改
DELETE /api/v1/llm/providers/{id}         # 删除
POST   /api/v1/llm/providers/{id}/set-default  # 设为全局默认
```

---

## 4. Sub-Agent 自动注册

### 4.1 manifest.toml 最小格式（Phase 2a）

```toml
[agent]
name = "StockAgent"
description = "金融市场分析与投资研究专家"
capabilities = ["stock_analysis", "market_research", "financial_news"]

[prompt]
persona = """
你是 Sebastian 的金融分析顾问，专注于股票市场研究与投资分析。
遇到超出金融领域的问题，优先上报 Sebastian 处理。
"""

[llm]               # 可选，不填则使用全局默认 provider
provider_type = "anthropic"
model = "claude-haiku-4-5"

[concurrency]       # 可选，默认 max_parallel_tasks = 3
max_parallel_tasks = 3
```

### 4.2 AgentConfig 数据类

```python
class AgentConfig(BaseModel):
    agent_type: str              # 目录名，如 "stock"
    name: str                    # 展示名，来自 manifest.toml [agent].name
    description: str             # 能力描述，用于 Agent Router prompt 注入
    capabilities: list[str]      # 能力 tag，用于 Router 展示
    persona: str                 # system prompt 附加段
    llm_provider_type: str | None = None
    llm_model: str | None = None
    max_parallel_tasks: int = 3
```

### 4.3 _loader.py 逻辑

```
扫描路径（按优先级）：
1. {DATA_DIR}/extensions/agents/   ← 用户自定义（优先）
2. sebastian/agents/               ← 内置（源码）

对每个含 manifest.toml 的子目录：
  1. 解析 manifest.toml → AgentConfig
  2. 检查是否有 agent.py（自定义 BaseAgent 子类）；无则用 BaseAgent
  3. 创建 AgentPool（worker 数 = max_parallel_tasks，默认 3）
  4. 注册到全局 agent_registry: dict[str, AgentPool]
  5. 向 A2ADispatcher 注册该 agent_type 的队列

同名冲突：用户目录优先，内置同名 agent 跳过（日志 warning）。
```

---

## 5. A2A 协议实现

### 5.1 A2ADispatcher（`protocol/a2a/dispatcher.py`）

```python
class A2ADispatcher:
    """
    per-agent-type asyncio.Queue 传入委派任务。
    per-task asyncio.Future 传回执行结果。
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queues: dict[str, asyncio.Queue[DelegateTask]] = {}
        self._futures: dict[str, asyncio.Future[TaskResult]] = {}

    def register_agent_type(self, agent_type: str) -> None:
        """_loader.py 注册 agent 时调用"""
        self._queues[agent_type] = asyncio.Queue()

    def queue_for(self, agent_type: str) -> asyncio.Queue[DelegateTask]:
        return self._queues[agent_type]

    async def delegate(self, agent_type: str, task: DelegateTask) -> TaskResult:
        """
        Sebastian 调用：将任务投入目标 agent 队列，挂起等待结果。
        不阻塞 EventBus 和对话路径（在独立 asyncio Task 中调用）。
        """
        if agent_type not in self._queues:
            raise ValueError(f"Unknown agent_type: {agent_type}")
        loop = asyncio.get_event_loop()
        future: asyncio.Future[TaskResult] = loop.create_future()
        self._futures[task.task_id] = future
        await self._queues[agent_type].put(task)
        await self._bus.publish(Event(type=EventType.AGENT_DELEGATED, data={"task_id": task.task_id, "agent_type": agent_type}))
        return await future

    async def resolve(self, result: TaskResult) -> None:
        """Sub-Agent worker 完成任务时调用"""
        future = self._futures.pop(result.task_id, None)
        if future and not future.done():
            future.set_result(result)
        await self._bus.publish(Event(type=EventType.AGENT_RESULT_RECEIVED, data={"task_id": result.task_id, "ok": result.ok}))

    async def escalate(self, request: EscalateRequest) -> None:
        """Sub-Agent 遇阻上报，Sebastian 通过 EventBus 感知"""
        await self._bus.publish(Event(type=EventType.AGENT_ESCALATED, data={"task_id": request.task_id, "reason": request.reason}))
```

### 5.2 AgentPool Worker 消费循环

每个 AgentPool worker 启动时运行：

```python
async def _worker_loop(self, agent_id: str, dispatcher: A2ADispatcher) -> None:
    queue = dispatcher.queue_for(self._agent_type)
    while True:
        task = await queue.get()
        self._status[agent_id] = "busy"
        self._current_task[agent_id] = task.task_id
        try:
            result = await self._agent_instances[agent_id].execute_delegated_task(task)
            await dispatcher.resolve(result)
        except Exception as exc:
            await dispatcher.resolve(TaskResult(task_id=task.task_id, ok=False, output={"error": str(exc)}, artifacts=[]))
        finally:
            self._status[agent_id] = "idle"
            self._current_task[agent_id] = None
            queue.task_done()
```

### 5.3 BaseAgent.execute_delegated_task()

Sub-Agent 收到委派时的执行入口（新增方法）：

```python
async def execute_delegated_task(self, task: DelegateTask) -> TaskResult:
    """
    在该 agent 的 Session 上下文中执行委派任务。
    创建新 Session（或复用已有），运行 AgentLoop，返回结果。
    """
    session = await self._session_store.create_session(
        agent_type=self.agent_type,
        agent_id=self.agent_id,
        title=task.goal[:50],
    )
    # 将 goal + context 作为首条 user 消息注入
    messages = [{"role": "user", "content": _build_task_message(task)}]
    result_text = ""
    async for event in self._loop.stream(self.system_prompt, messages):
        # 收集最终文本输出
        if isinstance(event, TextDelta):
            result_text += event.delta
        # tool calls 由 BaseAgent.run_streaming() 的同一逻辑处理
    return TaskResult(task_id=task.task_id, ok=True, output={"result": result_text}, artifacts=[])
```

---

## 6. Agent Router

### 6.1 delegate_to_agent Tool

在 `sebastian/orchestrator/tools/delegate.py` 中定义，Sebastian 初始化时手动注册到自己的 `CapabilityRegistry`，**不放** `capabilities/tools/`（后者是全局共享目录，Sub-Agent 不应拥有委派能力）：

```python
@tool(
    name="delegate_to_agent",
    description="将任务委派给指定 Sub-Agent 异步执行",
)
async def delegate_to_agent(
    agent_type: str,   # "stock" / "code" / "life" 等已注册类型
    goal: str,         # 任务目标描述
    context: dict,     # 相关上下文（可为空 dict）
) -> ToolResult:
    from sebastian.gateway.state import dispatcher
    task = DelegateTask(
        task_id=f"task_{uuid4().hex[:8]}",
        goal=goal,
        context=context,
        constraints={},
        callback_url="memory://local",
    )
    result = await dispatcher.delegate(agent_type, task)
    return ToolResult(ok=result.ok, output=result.output)
```

### 6.2 Sebastian System Prompt 动态注入

`Sebastian.chat()` 在构建 system prompt 时，从 `agent_registry` 读取已注册 agent 列表，拼接到 prompt 末尾：

```
## 可用 Sub-Agent

| agent_type | 名称 | 能力 |
|------------|------|------|
| stock | StockAgent | stock_analysis, market_research, financial_news |
| life  | LifeAgent  | calendar, reminders, home_automation |

当任务超出你的直接能力或需要专项执行时，调用 delegate_to_agent tool 委派。
委派是异步的：tool 返回后任务已完成，结果在返回值中。
```

无已注册 agent 时，该段不注入（Sebastian 独立运行，不暴露无效工具）。

---

## 7. Skills 扫描注册

### 7.1 目录结构与格式

```
capabilities/skills/         ← 内置 Skills（源码）
  _loader.py
  <skill-name>/
    SKILL.md                 ← 必须存在
    <helper-script>.py       ← 可选辅助文件

{DATA_DIR}/extensions/skills/  ← 用户 Skills（外置，运行时可写）
  <skill-name>/
    SKILL.md
```

`SKILL.md` frontmatter 格式：

```markdown
---
name: deep-research
description: 多轮搜索 + 综合分析 + 报告生成，适用于需要深度研究某个主题的场景
---

# deep-research

## 执行步骤
...（自然语言步骤，LLM 按此执行）
```

### 7.2 _loader.py 注册逻辑

扫描两个目录（用户目录优先，同名覆盖内置），每个 `SKILL.md` 注册为 registry 中一个 tool：

```python
tool_name = f"skill__{skill_dir_name.replace('-', '_')}"  # "skill__deep_research"
description = frontmatter["description"]
skill_content = skill_md_body  # SKILL.md 正文（去掉 frontmatter）

# 等价于动态注册：
@tool(name=tool_name, description=description)
async def _skill_handler(**_kwargs) -> ToolResult:
    return ToolResult(ok=True, output=skill_content)
```

Agent 调用此 tool 时，`ToolResult.output` 即为完整 `SKILL.md` 正文，LLM 读取后按步骤执行。

### 7.3 Agent 自增 Skill

Agent 执行过程中若需新增 Skill，写文件到 `{DATA_DIR}/extensions/skills/<name>/SKILL.md`，然后调用 `registry.reload_skills()` 热加载，新 Skill 立即可用，无需重启。

---

## 8. Android App 对接

### 8.1 SubAgents 页（A2A 任务流）

**后端变更**：`GET /api/v1/agents` 响应新增字段：

```json
{
  "agents": [
    {
      "agent_type": "stock",
      "name": "StockAgent",
      "description": "金融市场分析与投资研究专家",
      "workers": [
        {
          "agent_id": "stock_01",
          "status": "busy",
          "session_id": "2026-04-04T10-00-00_abc",
          "current_goal": "分析港股近期走势"
        },
        { "agent_id": "stock_02", "status": "idle", "session_id": null, "current_goal": null },
        { "agent_id": "stock_03", "status": "idle", "session_id": null, "current_goal": null }
      ],
      "queue_depth": 0
    }
  ]
}
```

**前端变更**：

- `mapAgentSummary()` 使用 `description` 字段，busy worker 展示 `current_goal`
- 点击 Agent 卡片 → 调用 `GET /api/v1/agents/{agent_type}/sessions` → 展示 `SessionList`
- `api/agents.ts` 新增 `getAgentSessions(agentType: string)`
- 新增独立 store `useAgentSessionsStore`（避免与现有 `useAgentsStore` 混用）

### 8.2 Settings 页（LLM Provider 管理）

**新增 `api/llm_providers.ts`**：

```typescript
export async function getLLMProviders(): Promise<LLMProvider[]>
export async function createLLMProvider(data: LLMProviderCreate): Promise<LLMProvider>
export async function updateLLMProvider(id: string, data: LLMProviderUpdate): Promise<LLMProvider>
export async function deleteLLMProvider(id: string): Promise<void>
export async function setDefaultLLMProvider(id: string): Promise<void>
```

**类型定义（`types/index.ts` 新增）**：

```typescript
export interface LLMProvider {
  id: string
  name: string
  provider_type: 'anthropic' | 'openai'
  base_url: string | null
  api_key: string                                              // GET 时固定返回 "***"
  model: string
  thinking_format: 'reasoning_content' | 'think_tags' | null  // null = 无 thinking
  is_default: boolean
}
```

**`LLMProviderConfig.tsx` 重写**：从本地 `useSettingsStore` 切换为 `useLLMProvidersStore`（新 store）。

UI 交互：
- 列表展示所有 provider，默认标记
- 点击单条进入编辑表单（name / provider_type / base_url / api_key / model）
- 编辑页底部"设为默认"按钮
- 顶部"+ 添加"按钮进入新增表单

废弃：`useSettingsStore` 里的 `llmProvider` / `setLlmProvider` 字段。

---

## 9. 部署说明

### 9.1 当前（Docker）

适用于开发和无 macOS 依赖的部署场景，维持现有 `docker-compose.yml`。

### 9.2 Mac mini 中枢部署（未来）

Docker 在 macOS 上运行于 Linux 虚拟机，**无法访问**：osascript、Accessibility API、HomeKit、Contacts/Calendar 原生框架、系统通知中心等 macOS 系统能力。

若 Sebastian 需要接管 Mac mini 作为系统中枢（控制原生 App、调用 macOS 系统 API），应使用 **原生 Python 进程 + launchd** 部署：

```xml
<!-- ~/Library/LaunchAgents/com.sebastian.plist -->
<key>ProgramArguments</key>
<array>
  <string>/Users/xxx/.sebastian/venv/bin/uvicorn</string>
  <string>sebastian.gateway.app:app</string>
  <string>--host</string><string>127.0.0.1</string>
  <string>--port</string><string>8000</string>
</array>
<key>RunAtLoad</key><true/>
```

`DATA_DIR` 指向 `~/.sebastian/`，extensions 目录自动为 `~/.sebastian/extensions/`。

实施时机：Phase 3+ 需要 macOS 系统工具时，补充 `deploy/macos/` 目录（launchd plist + 安装脚本）。

---

## 10. 实施顺序（薄切片策略）

按端到端可验证节点分阶段推进：

### 切片 1：LLM Provider 注入（后端基础）

1. `stream_events.py` 补充 `ThinkingBlockStop.thinking` / `TextBlockStop.text` 字段
2. 实现 `sebastian/llm/provider.py`（抽象基类）
3. 实现 `sebastian/llm/anthropic.py`（Anthropic 适配）
4. 实现 `sebastian/llm/registry.py`（从 DB 加载）
5. `store/models.py` 新增 `LLMProviderRecord` + migration
6. `AgentLoop` 构造器改为接收 `LLMProvider`，内层循环改用 provider
7. `BaseAgent` 从 registry 获取 provider 注入 AgentLoop
8. 验证：现有单元测试通过，Sebastian 对话功能不退化

### 切片 2：A2A 基础链路

9. 实现 `protocol/a2a/dispatcher.py`（`A2ADispatcher`）
10. `agents/_loader.py`：扫描 `manifest.toml`，注册 AgentConfig + AgentPool + Dispatcher 队列
11. `AgentPool` 增加 worker 消费循环 + `current_goal` 状态
12. `BaseAgent.execute_delegated_task()` 实现
13. `orchestrator/tools/delegate.py`（`delegate_to_agent` tool，仅注册到 Sebastian）
14. Sebastian system prompt 动态注入 agent 列表
15. 为 stock/life/code 各添加最小 `manifest.toml`
16. 验证：Sebastian 能委派任务给 StockAgent，收到结果

### 切片 3：Gateway 路由 + App SubAgents 页

17. `gateway/routes/llm_providers.py`（5 个端点）
18. `GET /api/v1/agents` 响应补充 `name`/`description`/`current_goal` 字段
19. App `api/agents.ts` + `getAgentSessions()`
20. App `useLLMProvidersStore` + `LLMProviderConfig.tsx` 重写
21. 验证：App SubAgents 页展示 A2A 任务流，Settings 页 LLM Provider 管理可用

### 切片 4：Skills 扫描注册

22. `capabilities/skills/_loader.py`：扫描两个目录，注册为 tool
23. 验证：内置 + 用户目录 Skill 均可被 Agent 调用

---

## 11. 测试要求

### 单元测试

- `tests/unit/test_llm_anthropic.py`：mock Anthropic SDK，验证 `LLMStreamEvent` 映射正确
- `tests/unit/test_llm_openai_compat.py`：mock OpenAI SDK，同上
- `tests/unit/test_llm_registry.py`：provider_type + model 匹配优先级逻辑
- `tests/unit/test_a2a_dispatcher.py`：delegate → resolve 流程，queue 隔离（stock 队列满不影响 life）
- `tests/unit/test_agent_loader.py`：manifest.toml 解析，AgentConfig 字段正确，同名优先级
- `tests/unit/test_skill_loader.py`：两目录扫描，同名覆盖，tool 注册

### 集成测试

- `tests/integration/test_llm_providers_api.py`：CRUD 5 个端点，set-default 互斥逻辑
- `tests/integration/test_a2a_delegation.py`：Sebastian → StockAgent 完整委派链路，结果回传正确
- `tests/integration/test_agent_auto_registration.py`：有 manifest.toml 的目录启动后可通过 `GET /api/v1/agents` 查到

---

*本文档 v1.0，覆盖 Phase 2a 全部设计决策，对应架构文档 v0.5 Phase 2a 章节。*

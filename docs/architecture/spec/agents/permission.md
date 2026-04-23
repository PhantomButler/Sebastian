---
version: "1.2"
last_updated: 2026-04-23
status: implemented
---

# 权限系统：PolicyGate + PermissionReviewer

*← [Agents 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

为 tool call 执行链引入三档权限体系：

- 低风险工具（只读、无副作用）零额外开销直接执行
- 中风险工具由 PermissionReviewer（无状态 LLM 审查）逐次判断是否需要用户审批
- 高风险工具必定向用户发起审批，无例外
- 权限执行是必经路径，不依赖继承，不可绕过
- `CapabilityRegistry` 保持纯净，不感知权限逻辑

**不在范围内**：SubAgent 工具可见性过滤（由 manifest.toml 决定）、用户身份分级（Phase 5 identity 模块）。

---

## 2. 三档权限体系

```python
class PermissionTier(str, Enum):
    LOW           = "low"           # 直接执行，无拦截
    MODEL_DECIDES = "model_decides" # 模型附带 reason，PermissionReviewer 决定是否升级
    HIGH_RISK     = "high_risk"     # 必定向用户发起审批
```

`ToolSpec` 使用单一字段 `permission_tier: PermissionTier`，默认值 `MODEL_DECIDES`。

> **实现差异**：spec 原设计默认值为 `LOW`，实际代码采用 `MODEL_DECIDES` 作为更保守的默认值。由于所有工具均显式声明 tier，默认值不影响运行行为。

### 现有工具档位分配

| 工具 | 档位 | 理由 |
|---|---|---|
| Read / Glob / Grep | `LOW` | 只读，无副作用 |
| Write / Edit | `MODEL_DECIDES` | 写入有影响，交 Reviewer 判断 |
| Bash | `MODEL_DECIDES` | 命令千变万化，交 Reviewer 逐次判断 |
| web_search | `LOW` | 只读，无副作用 |
| MCP 工具（未分类） | `MODEL_DECIDES`（默认） | 保守处理 |

---

## 3. 模块结构

```
sebastian/permissions/
    __init__.py
    types.py       # PermissionTier、ToolCallContext、ReviewDecision
    reviewer.py    # PermissionReviewer — 无状态 LLM 单次调用
    gate.py        # PolicyGate — 包裹 registry 的权限代理

sebastian/core/protocols.py   # ApprovalManagerProtocol（避免循环依赖）
```

### 分层示意

```
gateway/app.py
    └── orchestrator/sebas.py
            └── core/base_agent.py
                    └── permissions/gate.py       ← 权限代理层
                            ├── capabilities/registry.py    ← 保持纯净
                            └── permissions/reviewer.py     ← LLM 审查
```

---

## 4. PolicyGate

所有 Agent 通过 `PolicyGate` 访问工具，不直接持有 `CapabilityRegistry`。

### 接口

```python
class PolicyGate:
    def __init__(
        self,
        registry: CapabilityRegistry,
        reviewer: PermissionReviewer,
        approval_manager: ApprovalManagerProtocol,
    ) -> None: ...

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """对 MODEL_DECIDES 工具注入 reason 必填字段后返回。"""

    async def call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult: ...
```

### get_all_tool_specs() — reason 注入

对 `MODEL_DECIDES` 工具，在 `input_schema.properties` 追加：

```json
"reason": {
    "type": "string",
    "description": "Explain why you need to call this tool and confirm it aligns with the current task goal."
}
```

并将 `"reason"` 加入 `required` 列表。`LOW` 和 `HIGH_RISK` 工具不注入。

### call() 执行路径

```
call(tool_name, inputs, context)
    │
    ├─ Stage 0: agent 身份白名单校验（所有 tier）
    │       context.allowed_tools 非 None 且 tool_name 不在其中 → 立即返回错误
    │
    ├─ workspace 边界前置检查（见 workspace-boundary.md）
    │
    ├─ tier == LOW
    │       └─→ registry.call(tool_name, **inputs)
    │
    ├─ tier == MODEL_DECIDES
    │       1. 从 inputs 提取并移除 reason
    │       2. reviewer.review(tool_name, inputs, reason, context.task_goal)
    │              → ReviewDecision(proceed | escalate, explanation)
    │       3. proceed  → registry.call(tool_name, **inputs)
    │          escalate → approval_manager.request_approval(...)
    │                     → granted: registry.call(tool_name, **inputs)
    │                     → denied:  ToolResult(ok=False, error="User denied approval")
    │
    └─ tier == HIGH_RISK
            → approval_manager.request_approval(...)
              → granted: registry.call(tool_name, **inputs)
              → denied:  ToolResult(ok=False, error="User denied approval")
```

### ToolCallContext

```python
@dataclass
class ToolCallContext:
    task_goal: str       # 交互式: 当前 user_message；委派任务: task.goal
    session_id: str
    task_id: str | None
    agent_type: str      # 实现时新增，用于上下文追踪
    depth: int           # 实现时新增，用于上下文追踪
```

---

## 5. PermissionReviewer

无状态 LLM 单次调用，每次审查完全独立。

### 接口

```python
@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str

class PermissionReviewer:
    def __init__(self, llm_registry: LLMProviderRegistry) -> None: ...

    async def review(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        task_goal: str,
    ) -> ReviewDecision: ...
```

### System Prompt

```
You are a security reviewer for an AI assistant system.
Your job: decide whether a tool call should proceed directly or require user approval.

Rules:
- PROCEED if: the action is reversible, read-only, or clearly aligned with the stated task goal
- ESCALATE if: the action is destructive, irreversible, accesses sensitive data,
  or the stated reason does not match the task goal
- If the tool is Bash and the command writes/modifies/deletes files
  outside the workspace directory ({workspace_dir}), you MUST respond with ESCALATE
- When in doubt, ESCALATE

Respond ONLY in valid JSON:
{"decision": "proceed" | "escalate", "explanation": "..."}
```

> **实现增强**：system prompt 动态注入 `workspace_dir`，使 Reviewer 能判断 Bash 命令是否越界。

### LLM 选择

使用 `LLMProviderRegistry.get_provider()` 获取系统默认 provider，与 Sebastian 主模型解耦。Lazy 初始化，首次 review 时才创建 provider 实例。

### 容错

API 错误或 JSON 解析失败时，**默认返回 `escalate`**，记录日志，不中断主流程。

---

## 6. BaseAgent 集成

### 构造器

```python
class BaseAgent(ABC):
    def __init__(
        self,
        gate: PolicyGate,            # 替换原 registry: CapabilityRegistry
        session_store: SessionStore,
        event_bus: EventBus | None = None,
    ) -> None: ...
```

- `AgentLoop` 调用 `gate.get_all_tool_specs()` 获取工具列表传给 LLM，不执行工具
- 工具执行（`gate.call()`）在 `BaseAgent._stream_inner` 里，收到 `ToolCallReady` 后调用

### task_goal 传递

在 `run_streaming()` 入口设置 `self._current_task_goals[session_id]`：

```python
context = ToolCallContext(
    task_goal=self._current_task_goals[session_id],
    session_id=session_id,
    task_id=task_id,
    agent_type=self.agent_type,
    depth=self._current_depth.get(session_id, 1),
)
result = await self._gate.call(event.name, event.inputs, context)
```

---

## 7. ApprovalManager 集成

审批无超时，无限等待用户处理：

```python
class ApprovalManagerProtocol(Protocol):
    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
    ) -> bool: ...
```

`reason` 写入 `ApprovalRecord`（`reason: Mapped[str]` 字段）并通过 SSE 事件推给前端。

---

## 8. Tool 目录结构

每个工具为独立子目录包：

```
capabilities/tools/
    _loader.py          # 扫描逻辑：平铺 .py + 子目录包
    _file_state.py      # 全局 mtime 缓存
    _path_utils.py      # 共享路径解析
    read/
        __init__.py
    write/
        __init__.py
    edit/
        __init__.py
    bash/
        __init__.py
    glob/
        __init__.py
    grep/
        __init__.py
    web_search/
        __init__.py
```

`_loader.py` 同时支持平铺 `.py` 文件和子目录包，`_` 开头的文件/目录被跳过。

---

## 9. Gateway 接线

```python
# lifespan 里
policy_gate = PolicyGate(
    registry=registry,
    reviewer=PermissionReviewer(llm_registry=llm_provider_registry),
    approval_manager=conversation,
)
sebastian_agent = Sebastian(gate=policy_gate, ...)
```

SubAgent 实例化时也传入同一个 `policy_gate`。

---

## 10. 工具可见性与白名单

Sub-agent 的 `allowed_tools` 白名单在两层强制生效：

1. **LLM 可见性层**（`AgentLoop.stream()`）
   - `AgentLoop` 在 `__init__` 存储 `allowed_tools` / `allowed_skills`。
   - 每轮调用 LLM 前通过 `PolicyGate.get_callable_specs(allowed_tools, allowed_skills)` 获取过滤后的 spec 列表。
   - LLM 只"看到"白名单内的工具，避免误调用。

2. **执行校验层**（`PolicyGate.call()` Stage 0）
   - `BaseAgent._stream_inner` 创建 `ToolCallContext` 时把 `allowed_tools` 传入（`frozenset[str] | None`）。
   - `PolicyGate.call()` 在路径规范化之前即做身份白名单校验，拒绝白名单外的调用。
   - 防御 LLM 幻觉工具名——即使模型编造不存在于 `tools` 列表的名字也会被拒绝。

两层之所以同时存在：
- 可见性层降低幻觉概率（LLM 看不到的工具，幻觉率显著下降）。
- 校验层提供硬保证（无论 LLM 怎么调用，身份边界不会被突破）。

白名单取值语义参见 `sebastian/agents/README.md` 的 "`allowed_tools` 白名单语义" 一节。

---

## 11. 工具可见性：能力白名单与协议工具自动注入

### 背景

`manifest.toml` 的 `allowed_tools` 字段是一个白名单：若声明了此字段，子代理只能看到（并调用）白名单内的工具。问题在于：白名单只表达"领域能力"，而 `ask_parent` 这类"协议工具"是所有子代理都需要的层级通信手段，不应要求每个 manifest 手动声明——否则遗漏就是 bug。

### 工具两类划分

| 类别 | 说明 | 控制方式 |
|------|------|---------|
| **能力工具** | 决定 Agent 能做什么（Read / Write / Bash 等） | manifest `allowed_tools` 白名单 |
| **协议工具** | 决定 Agent 如何在层级中通信（ask_parent / resume_agent / stop_agent / spawn_sub_agent / check_sub_agents / inspect_session） | 按角色自动注入，不受白名单影响 |

### 实现：`_loader.py` 自动追加

```python
# sebastian/agents/_loader.py
_SUBAGENT_PROTOCOL_TOOLS: tuple[str, ...] = (
    "ask_parent",
    "resume_agent",
    "stop_agent",
    "spawn_sub_agent",
    "check_sub_agents",
    "inspect_session",
)

if raw_tools is not None:
    protocol_extra = [t for t in _SUBAGENT_PROTOCOL_TOOLS if t not in raw_tools]
    effective_tools = list(raw_tools) + protocol_extra
else:
    effective_tools = None  # 不限制，全量工具已含协议工具
```

- 仅影响经 `_loader.py` 加载的子代理（`agents/` 目录）
- Sebastian 在 `app.py` 直接实例化，不经过此路径，完全不受影响
- `spawn_sub_agent` / `check_sub_agents` / `inspect_session` 同属协议工具：`check_sub_agents` 内部按 depth 分支（depth=1 看 depth=2，depth=2 看 depth=3），天然支持组长使用；`inspect_session` 按 session_id 查询，层级无关
- `resume_agent` / `stop_agent` 的具体作用域由工具内部基于 `ToolCallContext.depth` 和 parent 关系做硬校验（depth>=3 直接拒绝）

### 决策依据

单一白名单把"领域能力"和"层级通信权利"混在一起管，导致两个问题：
1. 每个 manifest 都需要手动维护协议工具，遗漏即 bug（Forge 曾经漏掉 `ask_parent`）
2. 新增子代理时需要知道哪些协议工具是必须的，隐式知识变成显式负担

分离之后，manifest 只表达一件事：这个 Agent 能用哪些执行能力。

### Sebastian vs Subagent 协议工具对比

Sebastian 不经过 `_loader.py`，在 `sebas.py` 手工维护 `allowed_tools`：

```python
# sebastian/orchestrator/sebas.py
allowed_tools = [
    "delegate_to_agent", "check_sub_agents", "inspect_session",
    "resume_agent", "stop_agent",
    "todo_write", "memory_save", "memory_search",
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
]
```

各层级协议工具分配：

| 能力 | Sebastian (depth=1) | 组长 (depth=2) | 组员 (depth=3) |
|---|---|---|---|
| 向下派活 | `delegate_to_agent` | `spawn_sub_agent` | — |
| 回复下属 | `resume_agent` | `resume_agent` | — |
| 暂停下属 | `stop_agent` | `stop_agent` | — |
| 问上级 | — (无上级) | `ask_parent` | `ask_parent` |
| 查下属进度 | `check_sub_agents` | `check_sub_agents` | — |
| 查 session | `inspect_session` | `inspect_session` | `inspect_session` |

---

*← [Agents 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

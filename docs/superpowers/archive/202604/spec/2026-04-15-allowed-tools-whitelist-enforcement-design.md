---
integrated_to: agents/permission.md
integrated_at: 2026-04-23
---

# allowed_tools 白名单强制生效 — 设计文档

**日期**：2026-04-15
**状态**：设计待实现
**关联模块**：`sebastian/core/`、`sebastian/permissions/`、`sebastian/agents/`、`sebastian/orchestrator/`

## 背景

Sebastian 的子代理通过 `manifest.toml` 的 `allowed_tools` 字段声明能力白名单，`sebastian/agents/_loader.py` 会自动追加协议工具（`ask_parent` / `resume_agent` / `stop_agent` / `spawn_sub_agent` / `check_sub_agents` / `inspect_session`）。

经代码审查发现：**当前 `allowed_tools` 形同虚设**。白名单只影响 system prompt 里罗列的工具描述清单，并没有真正限制 LLM 能调用的工具。

根因：

1. `sebastian/core/agent_loop.py:101` 调用 `self._registry.get_all_tool_specs()` —— 传给 LLM 的 `tools` 参数是**全量**，LLM 看到的远多于白名单。
2. `sebastian/capabilities/registry.py:22-24` 的 `get_all_tool_specs()` 硬编码 `allowed_tools=None`。
3. `sebastian/permissions/gate.py` 的 `call()` 方法没有做 agent 身份层的白名单校验，LLM 若幻觉出白名单外的工具名，只会被 `PolicyGate` 的风险档（LOW / MODEL_DECIDES / HIGH_RISK）拦截，而不是被身份白名单拦截。

结果：子代理 LLM 可以调用注册表里**任意**工具。

## 目标

让 `allowed_tools` 成为**真正的能力边界**，在两层都强制过滤：

1. **LLM 可见性层**：传给 LLM 的 `tools` 参数按 `allowed_tools` 过滤，LLM 看不到白名单外的工具。
2. **执行校验层**：`PolicyGate.call()` 前置校验 `tool_name` 在白名单内，防止 LLM 幻觉工具名绕过可见性层。

## 非目标

- 不改变 `PolicyGate` 的三档 tier 逻辑（LOW / MODEL_DECIDES / HIGH_RISK）。
- 不改变 MCP 工具、Skill 工具的注册与调用路径。
- 不重新设计 depth=3 组员的协议工具集（当前 depth=2 和 depth=3 共用同一套协议 6 工具，属于已知简化，本次不动）。

## 整体架构

两层强制边界：

```
manifest.toml
 allowed_tools = ["Read", "Glob"]
        ↓
_loader.py 自动追加协议工具
 effective = ["Read", "Glob", "ask_parent", "resume_agent", "stop_agent",
              "spawn_sub_agent", "check_sub_agents", "inspect_session"]
        ↓
BaseAgent.__init__ 存 self.allowed_tools
        ↓
 ┌─────────────────────────────────────────────┐
 │  Layer 1: LLM 可见性层                        │
 │  AgentLoop 存 allowed_tools/allowed_skills    │
 │  → PolicyGate.get_callable_specs(...)         │
 │  → LLM 只"看到"白名单工具                     │
 └─────────────────────────────────────────────┘
                  ↓ LLM 调用工具（可能幻觉名字）
 ┌─────────────────────────────────────────────┐
 │  Layer 2: 执行校验层                          │
 │  BaseAgent._stream_inner 把 allowed_tools     │
 │  写入 ToolCallContext                         │
 │  → PolicyGate.call() Stage 0 前置校验         │
 │  → 违规返回 ToolResult(ok=False, error=...)   │
 └─────────────────────────────────────────────┘
```

## 详细改动

### 改动 1：`PolicyGate` 新增 `get_callable_specs()`

**文件**：`sebastian/permissions/gate.py`

这是对原方案的关键修正。`AgentLoop._registry` 的类型是 `ToolSpecProvider`，实际传入的是 `PolicyGate` 实例，**不是** `CapabilityRegistry`。`PolicyGate.get_all_tool_specs()` 在返回前会为所有 `MODEL_DECIDES` 工具注入必填的 `reason` 字段（`gate.py:107-129`），这一 `reason` 注入逻辑必须保留。

因此在 `PolicyGate` 上新增带过滤参数的版本：

```python
def get_callable_specs(
    self,
    allowed_tools: set[str] | None = None,
    allowed_skills: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Filtered version of get_all_tool_specs — injects reason for MODEL_DECIDES tools."""
    specs: list[dict[str, Any]] = []
    for spec_dict in self._registry.get_callable_specs(allowed_tools, allowed_skills):
        tool_name = spec_dict["name"]
        native = get_tool(tool_name)
        tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES
        if tier == PermissionTier.MODEL_DECIDES:
            spec_dict = copy.deepcopy(spec_dict)
            schema = spec_dict.setdefault("input_schema", {})
            props = schema.setdefault("properties", {})
            required: list[str] = schema.setdefault("required", [])
            props["reason"] = _REASON_SCHEMA
            if "reason" not in required:
                required.append("reason")
        specs.append(spec_dict)
    return specs

def get_all_tool_specs(self) -> list[dict[str, Any]]:
    """Backward-compat shim for ToolSpecProvider protocol."""
    return self.get_callable_specs(None, None)
```

`ToolSpecProvider` 协议（`sebastian/core/protocols.py`）补充声明 `get_callable_specs` 方法。

### 改动 2：`AgentLoop` 接受并透传白名单

**文件**：`sebastian/core/agent_loop.py`

`__init__` 增加两个参数，保存为实例字段：

```python
def __init__(
    self,
    provider: LLMProvider | None,
    tool_provider: ToolSpecProvider,
    model: str = "claude-opus-4-6",
    max_tokens: int | None = None,
    allowed_tools: set[str] | None = None,   # 新增
    allowed_skills: set[str] | None = None,  # 新增
) -> None:
    ...
    self._allowed_tools = allowed_tools
    self._allowed_skills = allowed_skills
```

`stream()` 第 101 行改为：

```python
tools = self._registry.get_callable_specs(
    allowed_tools=self._allowed_tools,
    allowed_skills=self._allowed_skills,
)
```

### 改动 3：`BaseAgent` 构造 AgentLoop 时透传白名单

**文件**：`sebastian/core/base_agent.py`

`__init__` 里构造 `AgentLoop` 时把自身白名单传进去：

```python
self._loop = AgentLoop(
    provider,
    gate,
    resolved_model,
    allowed_tools=set(self.allowed_tools) if self.allowed_tools is not None else None,
    allowed_skills=set(self.allowed_skills) if self.allowed_skills is not None else None,
)
```

注意：`self.allowed_tools` 是 `list[str] | None`，传给 loop 前转 `set`。`None` 保持 `None`，语义是"不限制"。

### 改动 4：`PolicyGate.call()` 执行校验层

**文件**：`sebastian/permissions/types.py`

给 `ToolCallContext` 加字段：

```python
@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
    allowed_tools: frozenset[str] | None = None   # 新增
    progress_cb: Callable[...] | None = field(default=None, repr=False)
```

**文件**：`sebastian/core/base_agent.py`

`_stream_inner` 创建 context 时填入：

```python
context = ToolCallContext(
    task_goal=self._current_task_goals.get(session_id, ""),
    session_id=session_id,
    task_id=task_id,
    agent_type=agent_context,
    depth=getattr(self, "_current_depth", {}).get(session_id, 1),
    allowed_tools=frozenset(self.allowed_tools) if self.allowed_tools is not None else None,
    progress_cb=functools.partial(self._publish, session_id, EventType.TOOL_RUNNING),
)
```

**文件**：`sebastian/permissions/gate.py`

`call()` 在 Stage 1（路径规范化）**之前** 新增 Stage 0：

```python
async def call(self, tool_name, inputs, context):
    # Stage 0: allowed_tools 白名单校验
    if context.allowed_tools is not None and tool_name not in context.allowed_tools:
        return ToolResult(
            ok=False,
            error=(
                f"Tool {tool_name!r} not in allowed_tools for agent "
                f"{context.agent_type!r}"
            ),
        )
    native = get_tool(tool_name)
    tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES
    token = _current_tool_ctx.set(context)
    try:
        # Stage 1: 路径规范化
        _normalize_path_inputs(inputs)
        # ... 其余保持不变 ...
```

文档字符串里的审批流顺序也同步更新。

### 改动 5：Sebastian 补 `resume_agent` / `stop_agent`

**文件**：`sebastian/orchestrator/sebas.py`

当前 `allowed_tools` 列表（`sebas.py`）里需要显式声明 `resume_agent` / `stop_agent`，否则白名单真正生效后，Sebastian 无法恢复或暂停下属 session。

修改为：

```python
# Orchestrator-scope tools. 包含 resume_agent/stop_agent：用于恢复或暂停下属 session。
# 不含 spawn_sub_agent / ask_parent：前者由 delegate_to_agent 承担，后者因 Sebastian 无上级。
allowed_tools = [
    "delegate_to_agent",
    "check_sub_agents",
    "inspect_session",
    "resume_agent",
    "stop_agent",
    "todo_write",
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
]
```

### 改动 6：`allowed_tools` 三种语义文档化

`sebastian/agents/_loader.py` 当前逻辑（`_loader.py:85-94`）已经实现：

| manifest 声明 | Subagent 最终白名单 | 含义 |
|---|---|---|
| 未声明 | `None` | 不限制，可用全量工具（含协议工具） |
| `allowed_tools = []` | 6 个协议工具 | 仅具备通信能力，无领域工具 |
| `allowed_tools = ["Read"]` | `Read` + 6 个协议工具 | Read + 通信能力 |

其中协议 6 工具：
- `ask_parent` — 向上级请示
- `resume_agent` — 恢复 waiting/idle 下属
- `stop_agent` — 暂停运行中的下属
- `spawn_sub_agent` — 向下分派 depth=3 组员
- `check_sub_agents` — 查看自己组员的任务状态
- `inspect_session` — 查看指定 session 的详细进展

**Sebastian vs Subagent 协议工具对比**（Sebastian 不经过 `_loader.py`，在 `sebas.py` 手工维护）：

| 能力 | Sebastian (depth=1) | 组长 (depth=2) | 组员 (depth=3) |
|---|---|---|---|
| 向下派活 | `delegate_to_agent` | `spawn_sub_agent` | — |
| 回复下属 | `resume_agent` | `resume_agent` | — |
| 暂停下属 | `stop_agent` | `stop_agent` | — |
| 问上级 | — (无上级) | `ask_parent` | `ask_parent` |
| 查下属进度 | `check_sub_agents` | `check_sub_agents` | — |
| 查 session | `inspect_session` | `inspect_session` | `inspect_session` |

## 一致性检查

- **System prompt 工具列表**：`base_agent.py:_tools_section()` 已经用 `self.allowed_tools` 过滤（`base_agent.py:157-165`），继续保留，与新加的 LLM `tools` 参数过滤保持一致。
- **现有单测**：`get_all_tool_specs()` 保留为 backward-compat shim，所有现有调用路径（包括 system prompt 生成、permission 相关测试）行为不变。
- **`_stream_inner` 的路径**：context 额外填入一个只读字段，不影响现有 gate / reviewer / approval 逻辑。

## 测试计划

### 新增单测

1. **LLM 可见性层**（`tests/unit/test_agent_loop.py` 或 `test_permissions.py`）
   - 给定 `allowed_tools = {"Read"}`，`AgentLoop.stream()` 传给 provider 的 `tools` 参数只包含 `Read`（含 `reason` 字段注入），不包含 `Bash`、`Write` 等。
   - 给定 `allowed_tools = None`，`tools` 参数等于全量。

2. **执行校验层**（`tests/unit/test_permissions.py` 或 `test_gate.py`）
   - 给定 `context.allowed_tools = frozenset({"Read"})`，`PolicyGate.call("Bash", ...)` 返回 `ToolResult(ok=False, error=...)`，错误消息包含 `'Bash'` 和 agent_type。
   - 给定 `context.allowed_tools = None`，任意合法工具正常调用（回归）。
   - 给定 `context.allowed_tools = frozenset({"Read"})`，`PolicyGate.call("Read", ...)` 正常执行。

3. **Loader 语义**（`tests/unit/test_agent_loader.py`）
   - `allowed_tools` 未声明 → 最终 `None`。
   - `allowed_tools = []` → 最终等于协议 6 工具。
   - `allowed_tools = ["Read"]` → 最终包含 `Read` + 协议 6 工具，无重复。

4. **Sebastian 集成**（`tests/integration/` 或 `test_sebas.py`）
   - Sebastian 实例的 `allowed_tools` 包含 `resume_agent` 与 `stop_agent`。
   - 经过 `PolicyGate.call("resume_agent", ...)` 与 `PolicyGate.call("stop_agent", ...)` 白名单校验通过。

### 回归

- `pytest` 全量绿。
- `ruff check sebastian/ tests/` 无错误。
- `ruff format sebastian/ tests/` 格式无变化。
- `mypy sebastian/` 无错误。

## 文档同步

1. **`sebastian/agents/README.md`**
   - 新增一节 "`allowed_tools` 三种语义"，列清楚 `None` / `[]` / `["..."]` 的最终效果。
   - 列出协议 6 工具（即 `_SUBAGENT_PROTOCOL_TOOLS`）的名称与用途。
   - 放上述 "Sebastian vs Subagent 协议工具对比" 表。
   - 说明 "Sebastian 不经过 `_loader.py`，手工维护 `allowed_tools`"。

2. **`docs/architecture/spec/agents/permission.md`**
   - 在"工具可见性"小节明确：白名单在两层都生效（LLM 可见性层 + 执行校验层）。
   - 解释 `ToolCallContext.allowed_tools` 字段的用途。
   - 更新审批流顺序说明，加入 Stage 0。

## 验收标准

- [ ] 子代理 LLM 看到的 `tools` 参数 = `allowed_tools`（含自动注入的协议工具）
- [ ] 子代理调用白名单外工具时被 `PolicyGate` Stage 0 拒绝，错误清晰
- [ ] Sebastian 能成功调用 `resume_agent` 与 `stop_agent`
- [ ] `allowed_tools = None / [] / [...]` 三种语义与文档一致
- [ ] 新增单测覆盖上述 4 组场景
- [ ] `pytest` / `ruff check` / `ruff format` / `mypy` 全绿
- [ ] `sebastian/agents/README.md` 与 `docs/architecture/spec/agents/permission.md` 已同步

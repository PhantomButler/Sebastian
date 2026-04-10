# 权限系统设计：PolicyGate + PermissionReviewer

**版本**：v1.0  
**日期**：2026-04-05  
**状态**：已确认，待实施  
**关联**：`2026-04-01-sebastian-architecture-design.md`、`2026-04-04-phase2a-spec.md`

---

## 1. 背景与目标

当前系统在执行 tool call 时没有任何权限拦截——`BaseAgent._stream_inner` 拿到 `ToolCallReady` 事件后直接调用 `registry.call()`，`ToolSpec` 上虽有 `requires_approval` 和 `permission_level` 字段，但完全未接入执行链。

目标：为 tool call 执行链引入三档权限体系，确保：
- 低风险工具（只读、无副作用）零额外开销直接执行
- 中风险工具由 PermissionReviewer（无状态 LLM 审查）逐次判断是否需要用户审批
- 高风险工具必定向用户发起审批，无例外
- 权限执行是必经路径，不依赖继承，不可绕过
- `CapabilityRegistry` 保持纯净，不感知权限逻辑

**不在本设计范围：**
- SubAgent 工具可见性过滤（由 manifest.toml 注册时决定，与权限系统正交）
- 用户身份分级（Phase 5 identity 模块负责）

---

## 2. 三档权限体系

```python
class PermissionTier(str, Enum):
    LOW           = "low"           # 直接执行，无拦截
    MODEL_DECIDES = "model_decides" # 模型附带 reason，PermissionReviewer 决定是否升级
    HIGH_RISK     = "high_risk"     # 必定向用户发起审批
```

替换 `ToolSpec` 现有的 `requires_approval: bool` 和 `permission_level: str`，改为单一字段 `permission_tier: PermissionTier`，默认值 `LOW`。

### 现有工具档位分配

| 工具 | 档位 | 理由 |
|---|---|---|
| `file_read` | `LOW` | 只读，无副作用 |
| `web_search` | `LOW` | 只读，无副作用 |
| `file_write` | `MODEL_DECIDES` | 写入有影响，交 Reviewer 判断 |
| `shell` | `MODEL_DECIDES` | 命令千变万化，交 Reviewer 逐次判断 |
| MCP 工具（未分类） | `MODEL_DECIDES`（默认） | 保守处理 |

### 新工具档位参考

| 场景 | 建议档位 |
|---|---|
| 读取系统进程、状态信息 | `LOW` |
| 发送消息、写入日历 | `MODEL_DECIDES` |
| 删除文件、格式化磁盘、终止进程 | `HIGH_RISK` |
| 访问私密数据（密码、密钥） | `HIGH_RISK` |

---

## 3. 模块结构

新增独立子包 `sebastian/permissions/`：

```
sebastian/permissions/
    __init__.py
    types.py       # PermissionTier、ToolCallContext、ReviewDecision
    reviewer.py    # PermissionReviewer — 无状态 LLM 单次调用
    gate.py        # PolicyGate — 包裹 registry 的权限代理
```

新增 `sebastian/core/protocols.py`（避免循环依赖）：

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

### 分层示意

```
gateway/app.py
    └── orchestrator/sebas.py
            └── core/base_agent.py
                    └── permissions/gate.py       ← 权限代理层（新增）
                            ├── capabilities/registry.py    ← 保持纯净
                            └── permissions/reviewer.py     ← LLM 审查
```

`CapabilityRegistry` 零改动，`permissions/` 不依赖 `orchestrator/`，架构分层不被打破。

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
        inputs: dict[str, Any],   # MODEL_DECIDES 工具的 inputs 包含 reason 字段
        context: ToolCallContext,
    ) -> ToolResult: ...
```

### get_all_tool_specs() — reason 注入

对 `MODEL_DECIDES` 工具，在 `input_schema` 的 `properties` 里追加：

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
    ├─ tier == LOW
    │       └─→ registry.call(tool_name, **inputs)
    │
    ├─ tier == MODEL_DECIDES
    │       1. 从 inputs 提取并移除 reason
    │       2. reviewer.review(tool_name, inputs, reason, context.task_goal)
    │              → ReviewDecision(proceed | escalate, explanation)
    │       3. proceed  → registry.call(tool_name, **inputs)
    │          escalate → approval_manager.request_approval(
    │                         approval_id, context.task_id, tool_name,
    │                         inputs, reason=decision.explanation)
    │                     → granted: registry.call(tool_name, **inputs)
    │                     → denied:  ToolResult(ok=False, error="User denied approval")
    │
    └─ tier == HIGH_RISK
            → approval_manager.request_approval(
                  approval_id, context.task_id, tool_name,
                  inputs, reason="High-risk tool requires user approval.")
              → granted: registry.call(tool_name, **inputs)
              → denied:  ToolResult(ok=False, error="User denied approval")
```

### ToolCallContext

```python
@dataclass
class ToolCallContext:
    task_goal: str       # 交互式: 当前 user_message；委派任务: DelegateTask.goal
    session_id: str
    task_id: str | None
```

---

## 5. PermissionReviewer

无状态 LLM 单次调用，每次审查完全独立。

### 接口

```python
@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str   # "proceed" 时为空；"escalate" 时展示给用户的说明

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
- When in doubt, ESCALATE

Respond ONLY in valid JSON:
{"decision": "proceed" | "escalate", "explanation": "..."}
explanation must be in the user's language, written for a non-technical user.
When decision is "proceed", explanation is an empty string.
```

### 请求体

```python
user_content = (
    f"Task goal: {task_goal}\n"
    f"Tool: {tool_name}\n"
    f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
    f"Model's reason: {reason}"
)
```

### LLM 选择

使用 `LLMProviderRegistry.get_provider()` 获取系统默认 provider，与 Sebastian 主模型解耦。未来可单独配置轻量模型（如 Haiku）专做审查。

### 容错

API 错误或 JSON 解析失败时，**默认返回 `escalate`**，记录日志，不中断主流程。

---

## 6. BaseAgent 改造

### 构造器

```python
class BaseAgent(ABC):
    def __init__(
        self,
        gate: PolicyGate,            # 替换原 registry: CapabilityRegistry
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        model: str | None = None,
    ) -> None: ...
```

**职责划分**：
- `AgentLoop` 只调用 `gate.get_all_tool_specs()` 获取工具列表传给 LLM，不执行工具
- 工具执行（`gate.call()`）在 `BaseAgent._stream_inner` 里，agentLoop yield `ToolCallReady` 后由 BaseAgent 调用

### task_goal 传递

在 `run_streaming()` 和 `execute_delegated_task()` 入口设置 `self._current_task_goal`：

```python
# run_streaming()
self._current_task_goal = user_message

# execute_delegated_task()
self._current_task_goal = task.goal
```

`_stream_inner` 处理 `ToolCallReady` 时构建 context：

```python
context = ToolCallContext(
    task_goal=self._current_task_goal,
    session_id=session_id,
    task_id=task_id,
)
result = await self._gate.call(event.name, event.inputs, context)
```

---

## 7. ConversationManager 改造

### 移除超时

审批无超时，无限等待用户处理：

```python
# 移除 asyncio.wait_for 包装，直接 await future
return await future
```

### 新增 reason 参数

```python
async def request_approval(
    self,
    approval_id: str,
    task_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    reason: str,           # Reviewer explanation 或 HIGH_RISK 默认说明
) -> bool: ...
```

`reason` 写入 `ApprovalRecord`（新增字段，需 DB migration）并通过 SSE 事件推给前端，作为审批弹窗说明展示给用户。

---

## 8. gateway/app.py 接线

```python
# lifespan 里
policy_gate = PolicyGate(
    registry=registry,
    reviewer=PermissionReviewer(llm_registry=llm_provider_registry),
    approval_manager=conversation,   # ConversationManager 满足 ApprovalManagerProtocol
)
sebastian_agent = Sebastian(
    gate=policy_gate,
    session_store=session_store,
    index_store=index_store,
    task_manager=task_manager,
    conversation=conversation,
    event_bus=event_bus,
)
```

SubAgent worker 实例化时也传入同一个 `policy_gate`（`agents/_loader.py` 从 gateway state 读取注入）。

---

## 9. 数据模型变更

### ApprovalRecord 新增字段

```python
class ApprovalRecord(Base):
    ...
    reason: Mapped[str] = mapped_column(String, default="")   # 新增
```

需新增 Alembic migration（或在 `init_db` 里 `CREATE TABLE IF NOT EXISTS` 时补列）。

### ToolSpec 字段变更

移除：`requires_approval: bool`、`permission_level: str`  
新增：`permission_tier: PermissionTier = PermissionTier.LOW`

---

## 10. 测试要求

### 单元测试

| 测试文件 | 覆盖点 |
|---|---|
| `tests/unit/test_policy_gate.py` | LOW 直通、MODEL_DECIDES proceed/escalate/denied、HIGH_RISK granted/denied、reason 字段被正确提取与移除 |
| `tests/unit/test_permission_reviewer.py` | proceed 决策、escalate 决策、API 失败默认 escalate、JSON 解析失败默认 escalate |
| `tests/unit/test_tool_spec.py` | get_all_tool_specs() reason 注入仅对 MODEL_DECIDES 工具生效 |

### 集成测试

| 测试文件 | 覆盖点 |
|---|---|
| `tests/integration/test_permission_flow.py` | 完整链路：MODEL_DECIDES tool call → Reviewer → escalate → 审批 API grant/deny → 工具执行/拒绝 |

---

## 11. Tool 目录结构重组

当前 `capabilities/tools/` 为平铺 `.py` 文件，随着工具增多和多文件需求，改为**目录-per-tool**结构。

### 新目录结构

```
capabilities/tools/
    _loader.py          # 扫描逻辑（更新）
    file_ops/
        __init__.py     # 原 file_ops.py 内容移入，@tool 装饰器即元数据
        _helpers.py     # 可选辅助文件（_ 开头，loader 不直接扫描）
    shell/
        __init__.py     # 原 shell.py 内容移入
    web_search/
        __init__.py     # 原 web_search.py 内容移入
```

**设计原则**：
- 无独立元数据文件。`name / description / permission_tier` 全在 `@tool` 装饰器里，代码即元数据，避免两处维护
- 辅助模块以 `_` 开头，loader 跳过直接扫描，只加载 `__init__.py`
- 向后兼容：`_loader.py` 同时支持平铺 `.py` 文件和子目录包，迁移期间不破坏现有工具

### _loader.py 更新逻辑

```python
def load_tools() -> None:
    tools_dir = Path(__file__).parent
    # 1. 平铺 .py 文件（跳过 _ 开头）
    for path in sorted(tools_dir.glob("*.py")):
        if not path.stem.startswith("_"):
            importlib.import_module(f"sebastian.capabilities.tools.{path.stem}")
    # 2. 子目录包（含 __init__.py，跳过 _ 开头目录）
    for entry in sorted(tools_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_") and (entry / "__init__.py").exists():
            importlib.import_module(f"sebastian.capabilities.tools.{entry.name}")
```

---

## 12. Tool 系统文档

### capabilities/tools/README.md（新建）

覆盖以下内容：

1. **概述**：tool 系统角色、`@tool` 自动注册机制
2. **ToolResult**：`ok / output / error` 字段含义与用法
3. **@tool 装饰器参数**：`name`、`description`、`permission_tier`
4. **三档权限详解**：语义、选择指南、MODEL_DECIDES 的 `reason` 注入机制（工具函数无需定义 `reason` 参数）
5. **创建新 tool 完整步骤**：新建目录 → 写 `__init__.py` → 选档位 → 重启自动注册
6. **代码示例**：LOW 和 MODEL_DECIDES 各一个完整可运行示例
7. **类型注解规范**：支持的参数类型（str/int/float/bool）
8. **常见错误**：不要手动定义 `reason` 参数、函数必须 async、目录名 `_` 开头会被跳过

### capabilities/README.md（更新）

在"常见任务入口"部分末尾追加：

```markdown
## 详细文档

- **Tool 系统完整指南**：[`capabilities/tools/README.md`](tools/README.md)
  — 权限档位选择、创建流程、代码示例
```

---

## 13. 完整实施顺序

1. `core/protocols.py` — `ApprovalManagerProtocol`
2. `permissions/types.py` — `PermissionTier`、`ToolCallContext`、`ReviewDecision`
3. `core/tool.py` — 替换 `ToolSpec` 字段，更新 `@tool` 装饰器
4. `capabilities/tools/_loader.py` — 支持子目录扫描
5. 现有工具迁移至目录结构（`file_ops/`、`shell/`、`web_search/`），同步更新 `permission_tier`
6. `permissions/reviewer.py` — `PermissionReviewer`
7. `permissions/gate.py` — `PolicyGate`
8. `core/base_agent.py` — 接收 `gate`，传递 context，调用 `gate.call()`
9. `orchestrator/conversation.py` — 移除超时，新增 `reason` 参数
10. `store/models.py` + migration — `ApprovalRecord.reason` 字段
11. `gateway/app.py` — 创建 `PolicyGate`，接线
12. `orchestrator/sebas.py` — 构造器改用 `gate`
13. `capabilities/tools/README.md` — 新建文档
14. `capabilities/README.md` — 添加链接
15. 单元测试 + 集成测试

---

*本文档 v1.0，覆盖权限系统完整设计 + tool 目录重组 + 文档化，对应架构文档 Tool Permission 章节。*

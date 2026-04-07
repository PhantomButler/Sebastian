# Workspace 边界强制执行设计

**日期**：2026-04-07
**状态**：已批准

## 背景与问题

当前 Agent 和 Sub-Agent 在执行文件操作时缺乏工作目录边界约束：

- `Write` / `Edit` 工具使用 `os.path.abspath()` 解析相对路径，基准是进程 cwd 而非 workspace，导致文件可能被写到任意位置（如 `/tmp/`）
- `PolicyGate` 的权限决策只有 tier 维度（LOW / MODEL_DECIDES / HIGH_RISK），没有路径空间维度
- `PermissionReviewer` 的 system prompt 不感知 workspace 路径，无法正确判断 Bash 命令是否越界
- `BaseAgent` 没有统一的操作规范注入机制，各 Agent 可能倾向于用 bash cat/sed 等命令代替结构化工具

## 目标

1. 所有文件写/修改操作默认限制在 `workspace_dir` 内
2. workspace 外的写操作无论 tier 如何，均需用户明确审批
3. 读操作不受限制（只读不涉及数据破坏风险）
4. 通过统一 system prompt section 引导所有 Agent 优先使用结构化工具

## 边界定义

```
workspace_dir = settings.workspace_dir = ~/.sebastian/workspace
```

**路径行为规则**：

| 路径类型 | 操作类型 | 行为 |
|---------|---------|------|
| 相对路径 | Write / Edit | 解析到 `workspace_dir`（非进程 cwd） |
| 绝对路径 ∈ workspace | Write / Edit | 正常走原有 tier 流程 |
| 绝对路径 ∉ workspace | Write / Edit | 跳过 LLM reviewer，直接请求用户审批 |
| 任意路径 | Read / Glob / Grep | 不限制 |
| Bash 命令 | 写/修改/删除操作 | 由 LLM reviewer 依据 workspace_dir 判断是否 ESCALATE |

## 变更详情

### 1. 新增共享路径解析工具：`_path_utils.py`

**文件**：`sebastian/capabilities/tools/_path_utils.py`（新建）

所有接受文件路径参数的工具**必须**调用此模块的 `resolve_path()`，禁止在工具内自行调用 `os.path.abspath()`。

```python
from pathlib import Path
from sebastian.config import settings

def resolve_path(file_path: str) -> Path:
    """将文件路径解析为绝对路径。
    相对路径解析到 workspace_dir；绝对路径直接 resolve。
    所有文件类工具必须调用此函数，不得使用 os.path.abspath()。
    """
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    return (settings.workspace_dir / file_path).resolve()
```

**修改 Write / Edit**：将各自的 `os.path.abspath(file_path)` 替换为 `resolve_path(file_path)`，引入来自 `_path_utils`。`Read` 工具同步修改（虽然不受 workspace 约束，但路径解析基准应统一）。

### 2. PolicyGate：workspace 边界前置检查

**文件**：`sebastian/permissions/gate.py`

**变更**：在 `call()` 方法的 tier 分支前，插入 workspace 边界检查：

```python
# 在 tier 判断前（使用与工具层相同的 _resolve_path，来自 capabilities/tools/_path_utils.py）
if tier == PermissionTier.MODEL_DECIDES and "file_path" in inputs:
    resolved = _resolve_path(inputs["file_path"])
    if not resolved.is_relative_to(settings.workspace_dir):
        # 先 pop reason，避免透传给工具函数时产生 TypeError
        clean_inputs = {k: v for k, v in inputs.items() if k != "reason"}
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=clean_inputs,
            reason=f"操作路径 '{resolved}' 在 workspace 外，需要用户确认。",
            session_id=context.session_id or "",
        )
        if granted:
            return await self._registry.call(tool_name, **clean_inputs)
        return ToolResult(ok=False, error="用户拒绝了 workspace 外的文件操作。")
```

**检查条件**：`MODEL_DECIDES` tier + inputs 含 `file_path`。`LOW` tier（Read）不触发此检查。

**关键约束**：PolicyGate 和工具层共用同一个 `resolve_path`（来自 `capabilities/tools/_path_utils.py`），确保两处对相对路径的解析结果完全一致，避免 PolicyGate 判定"在 workspace 内"而工具实际写到别处的逻辑矛盾。

### 3. PermissionReviewer：动态注入 workspace_dir

**文件**：`sebastian/permissions/reviewer.py`

**变更**：将模块级常量 `_SYSTEM_PROMPT` 改为模板字符串 `_SYSTEM_PROMPT_TEMPLATE`，在 `review()` 方法内动态格式化：

```python
_SYSTEM_PROMPT_TEMPLATE = """\
You are a security reviewer for an AI assistant system.
...（现有规则）...

Additional rule:
- If the tool is `Bash` and the command writes, modifies, moves, or deletes files \
outside the workspace directory (`{workspace_dir}`), you MUST respond with ESCALATE.
"""

# review() 方法内：
system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
    workspace_dir=settings.workspace_dir
)
```

`settings.workspace_dir` 是全局单例属性，调用时始终返回正确路径。

### 4. BaseAgent：全局操作规范 section

**文件**：`sebastian/core/base_agent.py`

**变更**：新增 `_guidelines_section()` 方法，纳入 `build_system_prompt()`：

```python
def _guidelines_section(self) -> str:
    return (
        "## Operation Guidelines\n\n"
        f"- Workspace directory: `{settings.workspace_dir}`. "
        "Use relative paths for all file operations — they resolve to workspace automatically.\n"
        "- Prefer structured tools over shell commands for file operations:\n"
        "  - Use `Read` instead of `bash cat`\n"
        "  - Use `Write` / `Edit` instead of `bash sed`, `bash tee`, or redirect (`>`)\n"
        "  - Use `Glob` instead of `bash find`\n"
        "  - Use `Grep` instead of `bash grep` / `bash rg`\n"
        "- Operations outside the workspace directory require user approval. "
        "Always explain why you need to access a path outside workspace before requesting."
    )

def build_system_prompt(self, gate, agent_registry=None):
    sections = [
        self._persona_section(),
        self._guidelines_section(),   # 新增，所有 agent 继承
        self._tools_section(gate),
        self._skills_section(gate),
        self._agents_section(agent_registry),
        self._knowledge_section(),
    ]
    return "\n\n".join(s for s in sections if s)
```

guidelines section 放在 persona 之后、tools 之前，确保模型在了解工具前先接收操作规范。

## 不在范围内

- Bash 命令的结构化路径解析（shell 命令解析复杂度过高，不值得实现）
- Read / Glob / Grep 的路径限制（只读操作，不做约束）
- MCP 工具的 workspace 检查（MCP 工具参数名无法保证命名规范，暂不处理）

## 测试策略

### 单元测试扩展（在现有文件内追加用例）

**`tests/unit/test_write_tool.py`**（或新建）：
- 相对路径 `"foo.txt"` → 解析为 `workspace_dir/foo.txt`
- workspace 内绝对路径 → 正常执行
- workspace 外绝对路径 → 触发 approval（通过 mock PolicyGate 验证）

**`tests/unit/test_edit_tool.py`**：
- 同 Write 的路径解析用例

**`tests/unit/test_policy_gate.py`**（现有文件扩展）：
- `file_path` 在 workspace 外 + `MODEL_DECIDES` → 跳过 reviewer，直接调用 approval_manager
- `file_path` 在 workspace 内 → 走原有 reviewer 流程
- `LOW` tier（Read）含 `file_path` → 不触发 workspace 检查

**`tests/unit/test_reviewer.py`**（现有文件扩展）：
- 验证 `review()` 调用时构建的 system prompt 包含真实 `workspace_dir` 路径字符串

**`tests/unit/test_base_agent.py`**（现有文件扩展）：
- `build_system_prompt()` 返回的字符串包含 guidelines section
- guidelines section 包含正确的 `workspace_dir` 路径

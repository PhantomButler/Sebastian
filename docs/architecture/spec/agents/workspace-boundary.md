---
version: "1.0"
last_updated: 2026-04-10
status: implemented
---

# Workspace 边界强制执行

*← [Agents 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

Agent 执行文件操作时需要工作目录边界约束：

- Write / Edit 工具使用 `os.path.abspath()` 解析相对路径，基准是进程 cwd 而非 workspace
- PolicyGate 的权限决策只有 tier 维度，没有路径空间维度
- PermissionReviewer 的 system prompt 不感知 workspace 路径
- BaseAgent 没有统一的操作规范注入机制

**目标**：

1. 所有文件写/修改操作默认限制在 `workspace_dir` 内
2. workspace 外的写操作无论 tier 如何，均需用户明确审批
3. 读操作不受限制
4. 通过统一 system prompt section 引导所有 Agent 优先使用结构化工具

---

## 2. 边界定义

```
workspace_dir = settings.workspace_dir = ~/.sebastian/workspace
```

### 路径行为规则

| 路径类型 | 操作类型 | 行为 |
|---------|---------|------|
| 相对路径 | Write / Edit | 解析到 `workspace_dir`（非进程 cwd） |
| 绝对路径 ∈ workspace | Write / Edit | 正常走原有 tier 流程 |
| 绝对路径 ∉ workspace | Write / Edit | 跳过 LLM reviewer，直接请求用户审批 |
| 任意路径 | Read / Glob / Grep | 不限制 |
| Bash 命令 | 写/修改/删除操作 | 由 LLM reviewer 依据 workspace_dir 判断是否 ESCALATE |

---

## 3. 共享路径解析工具

文件：`sebastian/capabilities/tools/_path_utils.py`

所有接受文件路径参数的工具**必须**调用 `resolve_path()`，禁止自行调用 `os.path.abspath()`。

```python
from pathlib import Path
from sebastian.config import settings

def resolve_path(file_path: str) -> Path:
    """将文件路径解析为绝对路径。
    相对路径解析到 workspace_dir；绝对路径直接 resolve。
    """
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    return (settings.workspace_dir / file_path).resolve()
```

各工具集成情况：
- Write：调用 `resolve_path()` 解析路径
- Edit：调用 `resolve_path()` 解析路径
- Read：调用 `resolve_path()` 解析路径（虽不受 workspace 约束，但路径解析基准应统一）
- Bash：设置 `cwd=workspace_dir`
- Glob：默认搜索目录为 `workspace_dir`
- Grep：默认搜索目录为 `workspace_dir`

---

## 4. PolicyGate：workspace 边界前置检查

文件：`sebastian/permissions/gate.py`

在 `call()` 方法的 tier 分支前，插入 workspace 边界检查：

```python
if tier == PermissionTier.MODEL_DECIDES and "file_path" in inputs:
    resolved = resolve_path(inputs["file_path"])
    if not resolved.is_relative_to(settings.workspace_dir):
        # 跳过 LLM reviewer，直接请求用户审批
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

检查条件：`MODEL_DECIDES` tier + inputs 含 `file_path`。`LOW` tier（Read）不触发。

**关键约束**：PolicyGate 和工具层共用同一个 `resolve_path`，确保路径解析结果一致。

---

## 5. PermissionReviewer：动态注入 workspace_dir

文件：`sebastian/permissions/reviewer.py`

将 system prompt 改为模板字符串，在 `review()` 方法内动态格式化：

```python
_SYSTEM_PROMPT_TEMPLATE = """\
You are a security reviewer for an AI assistant system.
...

Additional rule:
- If the tool is `Bash` and the command writes, modifies, moves, or deletes files \
outside the workspace directory (`{workspace_dir}`), you MUST respond with ESCALATE.
"""

# review() 方法内：
system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(workspace_dir=settings.workspace_dir)
```

---

## 6. BaseAgent：全局操作规范 section

文件：`sebastian/core/base_agent.py`

新增 `_guidelines_section()` 方法，纳入 `build_system_prompt()`：

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
        "- Operations outside the workspace directory require user approval."
    )
```

System prompt section 顺序：persona → **guidelines** → tools → skills → agents → knowledge

---

## 7. 不在范围内

- Bash 命令的结构化路径解析（shell 命令解析复杂度过高）
- Read / Glob / Grep 的路径限制（只读操作，不做约束）
- MCP 工具的 workspace 检查（参数名无法保证命名规范）

---

*← [Agents 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

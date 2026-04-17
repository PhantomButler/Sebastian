---
version: "1.2"
last_updated: 2026-04-17
status: implemented
---

# Core Tools 实现设计

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 概述

六个对齐 Claude Code 语义的标准工具（Read、Write、Edit、Bash、Glob、Grep），替换原有的 file_ops 和 shell 占位工具。

架构原则：
- 每个工具为独立子目录包
- 共享进程级全局文件状态缓存（`_file_state.py`）用于 Write/Edit 的读后写校验
- 类型强制转换集中在 `core/tool.py` 的 `call_tool` 调用链中实现，所有工具透明受益

---

## 2. 目录结构

```
sebastian/capabilities/tools/
  _loader.py              # 工具扫描与加载
  _file_state.py          # 进程级全局 mtime 缓存
  _path_utils.py          # 共享路径解析（见 workspace-boundary spec）
  read/
    __init__.py           # Read 工具
  write/
    __init__.py           # Write 工具
  edit/
    __init__.py           # Edit 工具
  bash/
    __init__.py           # Bash 工具
  glob/
    __init__.py           # Glob 工具
  grep/
    __init__.py           # Grep 工具
  web_search/
    __init__.py           # 保留
```

---

## 3. 全局文件状态缓存

文件：`sebastian/capabilities/tools/_file_state.py`

进程级单例，内存常驻，重启清空。存储格式：`file_path → mtime at last Read`。

```python
_file_mtimes: dict[str, float] = {}

def record_read(path: str) -> None:
    """Read 成功后调用，记录当前 mtime。"""

def check_write(path: str) -> None:
    """Write/Edit 前调用。
    - 文件不存在 → 允许（新建）
    - 文件存在但从未 Read → 拒绝，提示先 Read
    - 文件存在且 Read 过，但 mtime 变更 → 拒绝，提示重新 Read
    抛出 ValueError，由调用方转为 ToolResult(ok=False)。
    """

def invalidate(path: str) -> None:
    """Write/Edit 成功后调用，更新缓存 mtime。"""
```

内存说明：每条记录约 200 字节，10 万条约 20 MB，对常驻进程可忽略。不设 TTL/LRU。

---

## 4. 工具规格

### 4.1 Read

**权限**：`PermissionTier.LOW`

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `file_path` | `str` | 是 | 文件路径 |
| `offset` | `int \| None` | 否 | 起始行号（1-indexed） |
| `limit` | `int \| None` | 否 | 读取行数，默认最多 2000 行 |

行为：UTF-8 读取（fallback latin-1），按 offset/limit 截取行范围，超 2000 行截断。读取成功后调用 `_file_state.record_read()`。

### 4.2 Write

**权限**：`PermissionTier.MODEL_DECIDES`

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `file_path` | `str` | 是 | 文件路径 |
| `content` | `str` | 是 | 完整文件内容 |

行为：先调用 `check_write()` 校验 mtime，自动创建父目录，写入 UTF-8 文件，成功后 `invalidate()`。

mtime 校验逻辑：
1. 文件不存在 → 允许创建
2. 文件存在但从未被 Read → 拒绝
3. 文件存在且读过，但 mtime 变更 → 拒绝

### 4.3 Edit

**权限**：`PermissionTier.MODEL_DECIDES`

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `file_path` | `str` | 是 | 文件路径 |
| `old_string` | `str` | 是 | 要替换的原始字符串（精确匹配） |
| `new_string` | `str` | 是 | 替换后的字符串 |
| `replace_all` | `bool` | 否 | 默认 `false` |

匹配规则：

| 匹配次数 | `replace_all=false` | `replace_all=true` |
|----------|--------------------|--------------------|
| 0 次 | 报错：未找到 | 报错：未找到 |
| 1 次 | 执行替换 | 执行替换 |
| >1 次 | 报错：不唯一 | 执行全部替换 |

> **实现增强**：代码中 Edit 也调用 `check_write()` 做 mtime 校验，比 spec 原设计（"无需 mtime 校验"）更严格，属于防御性增强。

### 4.4 Bash

**权限**：`PermissionTier.MODEL_DECIDES`

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `command` | `str` | 是 | Shell 命令 |
| `timeout` | `int \| None` | 否 | 超时秒数，默认 600 |
| `description` | `str \| None` | 否 | 命令意图描述，仅写日志不参与执行 |

行为：`asyncio.create_subprocess_shell` 异步执行，`cwd` 设为 `workspace_dir`。stdout + stderr 超 10000 字符时截断。超时后 `proc.kill()` 并返回错误。

#### 4.4.1 静默命令识别

```python
_SILENT_COMMANDS: frozenset[str] = frozenset(
    {"mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown",
     "chgrp", "touch", "ln", "cd", "export", "unset", "wait"}
)
```

静默命令（如 `mv`、`rm`）无输出时返回 `"Done"` 而非 `"Command exited with code 0, no output"`，防止 LLM 误判。

#### 4.4.2 语义化退出码

```python
_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep": {1: "No matches found (not an error)"},
    "find": {1: "No matches found (not an error)"},
    "diff": {1: "Files differ (not an error)"},
    "test": {1: "Condition false (not an error)"},
    "[":    {1: "Condition false (not an error)"},
}
```

白名单命令的特定退出码附带语义解释（如 `grep` 返回 1 = "No matches found"），消除 LLM 对非零退出码的误判。

#### 4.4.3 进度心跳

长命令（>3s）每 3 秒通过 `ToolCallContext.progress_cb` 发送 `TOOL_RUNNING` 事件：

```python
async def _heartbeat(
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    # 每 3s 发送 {"elapsed_seconds": N}，直到 stop_event.set()
```

**支撑基础设施**：

- `ToolCallContext.progress_cb`（`permissions/types.py`）：回调字段，默认 `None`，单测无副作用
- `BaseAgent`（`core/base_agent.py`）创建 context 时绑定 `self._publish` 为 `progress_cb`

**App 收到的 SSE 心跳事件**：

```json
{
  "type": "tool.running",
  "data": {
    "session_id": "...",
    "name": "Bash",
    "input": {"command": "npm run build", "description": "Build project"},
    "elapsed_seconds": 6
  }
}
```

App 判断 `data.elapsed_seconds` 存在即为进度心跳，展示"执行中 (Xs)"。

### 4.5 Glob

**权限**：`PermissionTier.LOW`

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `pattern` | `str` | 是 | Glob 模式（如 `**/*.py`） |
| `path` | `str \| None` | 否 | 搜索根目录，默认 workspace_dir |

行为：Python `glob.glob()` 递归搜索，结果按 mtime 降序排列，最多 100 条，返回相对路径。

### 4.6 Grep

**权限**：`PermissionTier.LOW`

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `pattern` | `str` | 是 | 正则表达式 |
| `path` | `str \| None` | 否 | 搜索目录或文件，默认 workspace_dir |
| `glob` | `str \| None` | 否 | 文件过滤模式 |
| `ignore_case` | `bool` | 否 | 大小写不敏感，默认 `false` |
| `context_lines` | `int \| None` | 否 | 匹配行前后各显示的行数 |
| `head_limit` | `int \| None` | 否 | 最多返回行数，默认 250 |

行为：优先使用系统 `rg`（ripgrep），不可用时退回 `grep -rn`。可用性检测结果缓存。

---

## 5. 参数类型强制转换

文件：`sebastian/core/tool.py`

在 `call_tool` 调用实际工具函数前执行 `_coerce_args()`：

```python
def _coerce_args(fn: Callable, kwargs: dict[str, Any]) -> dict[str, Any]:
    """根据函数签名的类型注解，对传入参数做宽松类型转换。
    支持：str→int, str→float, str→bool, str→None（对应 X | None）。
    转换失败时保留原值，由函数签名校验兜底。
    """
```

调用链：`call_tool(name, **kwargs)` → `_coerce_args(fn, kwargs)` → `fn(**coerced_kwargs)`

---

## 6. 权限层级汇总

| 工具 | `PermissionTier` | 理由 |
|------|-----------------|------|
| Read | LOW | 只读，无副作用 |
| Glob | LOW | 只读，仅返回路径 |
| Grep | LOW | 只读，内容搜索 |
| Write | MODEL_DECIDES | 全量覆盖文件，有副作用 |
| Edit | MODEL_DECIDES | 修改文件内容，有副作用 |
| Bash | MODEL_DECIDES | 执行 shell 命令，副作用不确定 |

---

## 7. ToolResult 显示与序列化

### 7.1 `ToolResult.display` 字段（`core/types.py`）

`ToolResult` 新增可选 `display` 字段，用于人类可读摘要：

```python
class ToolResult(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None
    empty_hint: str | None = None
    display: str | None = None   # 人类可读摘要；None → 走通用回退
```

**设计原则**：宽松模式——不填 `display` 不报错，装饰器不做校验。新工具先跑起来，后续想优化 UI 再加。

### 7.2 模型侧：`_tool_result_content` JSON 规范化（`core/agent_loop.py`）

喂回 LLM 的 `tool_result` 内容用 JSON 替换 Python `repr`，提升 LLM 解析稳定性：

```python
def _tool_result_content(result: ToolResult) -> str:
    if not result.ok:
        return f"Error: {result.error}"
    if result.empty_hint:
        return result.empty_hint
    if _is_empty_output(result.output):
        return "<empty output>"
    output = result.output
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(output)
```

- 字符串 output 保持裸字符串，不被包进 JSON 引号
- dict / list → JSON（`ensure_ascii=False` 保中文可读；`default=str` 兜底 `Path` 等非标准类型）
- **不截断**——模型需要完整上下文做决策

### 7.3 人类侧：`_format_tool_display`（`core/base_agent.py`）

从 `ToolResult` 提取人类可读内容，用于 SSE `result_summary` 和持久化 `record["result"]`：

```python
_DISPLAY_MAX = 4000

def _format_tool_display(result: ToolResult) -> str:
    if result.display is not None:
        text = result.display
    elif result.empty_hint is not None:
        text = result.empty_hint
    elif result.output is not None:
        text = str(result.output)
    else:
        text = ""
    if len(text) > _DISPLAY_MAX:
        return text[:_DISPLAY_MAX] + "…"
    return text
```

优先级：`display` → `empty_hint` → `str(output)`，截断上限 4000 字（Android `CollapsibleContent` 会对 >5 行做二次折叠，不会导致 UI 卡顿）。

### 7.4 核心工具 `display` 填充

| Tool | `display` 值 |
|------|-------------|
| Read | `output["content"]`（文件内容） |
| Bash | `stdout`；若 `returncode != 0` 且 `stderr` 非空，追加 `"\n--- stderr ---\n" + stderr` |
| Grep | `output["output"]`（匹配结果） |
| Glob | `"\n".join(files)`（文件列表） |
| Write | `f"Wrote {bytes_written} bytes to {file_path}"` |
| Edit | `f"Replaced {replacements} occurrence(s) in {file_path}"` |

其他内部工具（`ask_parent` / `check_sub_agents` / `inspect_session` / `todo_write` / `spawn_sub_agent` / `resume_agent`）不填 `display`，走回退路径。

### 7.5 持久化与兼容性

- 所有 tool block 写入同一 `record["result"]` 字段，新老数据共用
- 老 session 回放仍是 Python repr 字符串，新 session 是干净 display，共存无冲突
- 前端（Android + Web）**不需要改动**

---

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

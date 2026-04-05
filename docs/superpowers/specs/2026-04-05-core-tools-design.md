# Core Tools 实现设计

> **For agentic workers:** 本文档是设计 spec，实现前请先使用 `superpowers:writing-plans` 制定实施计划。

**Goal:** 用六个对齐 Claude Code 语义的标准工具（Read、Write、Edit、Bash、Glob、Grep）替换现有的临时占位工具（file_ops、shell），并在工具调用层统一引入参数类型强制转换。

**Architecture:** 每个工具为独立子目录包，共享进程级全局文件状态缓存（`_file_state.py`）用于 Write 的读后写校验；类型强制转换集中在 `core/tool.py` 的 `call_tool` 调用链中实现一次，所有工具透明受益。

**Tech Stack:** Python 3.12+、asyncio、`sebastian/core/tool.py` 的 `@tool` 装饰器与 `PermissionTier`、系统 ripgrep（优先）或 grep 作为 Grep 后端。

---

## 1. 目录结构

```
sebastian/capabilities/tools/
  _loader.py              # 现有，不改
  _file_state.py          # 新增：进程级全局 mtime 缓存
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
    __init__.py           # 保留不动
  file_ops/               # 删除
  shell/                  # 删除
```

---

## 2. 全局文件状态缓存（`_file_state.py`）

进程级单例，内存常驻，重启清空。存储格式：`file_path → mtime at last Read`。

```python
# sebastian/capabilities/tools/_file_state.py
from __future__ import annotations

import os

_file_mtimes: dict[str, float] = {}


def record_read(path: str) -> None:
    """Read 成功后调用，记录当前 mtime。"""
    try:
        _file_mtimes[path] = os.path.getmtime(path)
    except OSError:
        pass


def check_write(path: str) -> None:
    """
    Write 前调用。规则：
    - 文件不存在 → 允许（新建）
    - 文件存在但从未 Read → 拒绝，提示先 Read
    - 文件存在且 Read 过，但 mtime 变更 → 拒绝，提示重新 Read
    抛出 ValueError，由调用方转为 ToolResult(ok=False)。
    """
    if not os.path.exists(path):
        return  # 新文件，允许创建
    if path not in _file_mtimes:
        raise ValueError(f"File has not been read yet. Call Read first before writing: {path}")
    current_mtime = os.path.getmtime(path)
    if current_mtime != _file_mtimes[path]:
        raise ValueError(
            f"File has been modified externally since last read. Call Read again before writing: {path}"
        )


def invalidate(path: str) -> None:
    """Write/Edit 成功后调用，更新缓存 mtime。"""
    try:
        _file_mtimes[path] = os.path.getmtime(path)
    except OSError:
        _file_mtimes.pop(path, None)
```

**内存说明：** 每条记录约 200 字节。即使累计 10 万条路径，总占用约 20 MB，对常驻进程可忽略。不设 TTL/LRU。

---

## 3. 工具规格

### 3.1 Read

**文件：** `capabilities/tools/read/__init__.py`  
**权限层级：** `PermissionTier.LOW`

**参数：**

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `file_path` | `str` | 是 | 绝对路径 |
| `offset` | `int \| None` | 否 | 起始行号（1-indexed），不传则从头读 |
| `limit` | `int \| None` | 否 | 读取行数，不传则默认最多 2000 行 |

**行为：**
- 以 UTF-8 读取文件内容（fallback latin-1）
- 按 offset/limit 截取行范围
- 超过 2000 行时截断，输出中注明总行数和已读行数
- 读取成功后调用 `_file_state.record_read(abs_path)`
- 返回格式：`{"content": str, "total_lines": int, "lines_read": int, "truncated": bool}`

**错误处理：**
- 文件不存在 → `ToolResult(ok=False, error="File not found: <path>")`
- 目录路径 → `ToolResult(ok=False, error="Path is a directory, not a file: <path>")`

---

### 3.2 Write

**文件：** `capabilities/tools/write/__init__.py`  
**权限层级：** `PermissionTier.MODEL_DECIDES`

**参数：**

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `file_path` | `str` | 是 | 绝对路径 |
| `content` | `str` | 是 | 完整文件内容 |

**行为：**
- 先调用 `_file_state.check_write(abs_path)`，校验失败则直接返回错误
- 自动创建父目录（`mkdir -p`）
- 写入文件（UTF-8）
- 写入成功后调用 `_file_state.invalidate(abs_path)`
- 返回格式：`{"file_path": str, "action": "created" | "updated", "bytes_written": int}`

**mtime 校验逻辑（三种情况）：**
1. 文件不存在 → 允许创建
2. 文件存在但从未被 Read → 拒绝，提示先 `Read`
3. 文件存在且读过，但 mtime 变更 → 拒绝，提示重新 `Read`

---

### 3.3 Edit

**文件：** `capabilities/tools/edit/__init__.py`  
**权限层级：** `PermissionTier.MODEL_DECIDES`

**参数：**

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `file_path` | `str` | 是 | 绝对路径 |
| `old_string` | `str` | 是 | 要替换的原始字符串（精确匹配） |
| `new_string` | `str` | 是 | 替换后的字符串 |
| `replace_all` | `bool` | 否 | 默认 `false`；`true` 时替换所有出现位置 |

**匹配规则（核心）：**

| 匹配次数 | `replace_all=false` | `replace_all=true` |
|----------|--------------------|--------------------|
| 0 次 | 报错：未找到 | 报错：未找到 |
| 1 次 | 执行替换 | 执行替换 |
| >1 次 | **报错：不唯一，要求提供更多上下文** | 执行全部替换 |

`replace_all=false` 时出现多处匹配必须拒绝，强制 LLM 提供更精准的 `old_string`，避免意外修改多处。

**行为：**
- 读取文件内容，执行字符串匹配
- 通过校验后执行替换，写入文件
- 写入成功后调用 `_file_state.invalidate(abs_path)`
- **无需 mtime 校验**：old_string 不匹配即天然失败，是内置的冲突检测机制
- 返回格式：`{"file_path": str, "replacements": int}`

**错误处理：**
- 文件不存在 → `ToolResult(ok=False, error="File not found: <path>")`
- 0 次匹配 → `ToolResult(ok=False, error="old_string not found in file: <path>")`
- >1 次匹配且非 replace_all → `ToolResult(ok=False, error="old_string matches N times. Provide more context to make it unique, or use replace_all=true")`

---

### 3.4 Bash

**文件：** `capabilities/tools/bash/__init__.py`  
**权限层级：** `PermissionTier.MODEL_DECIDES`

**参数：**

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `command` | `str` | 是 | Shell 命令 |
| `timeout` | `int \| None` | 否 | 超时秒数，默认 600 |

**行为：**
- 使用 `asyncio.create_subprocess_shell` 异步执行
- 用 `asyncio.wait_for(proc.communicate(), timeout=timeout)` 控制超时
- 超时后调用 `proc.kill()` 并返回错误
- stdout + stderr 超过 10000 字符时截断，注明已截断
- 返回格式：`{"stdout": str, "stderr": str, "returncode": int, "truncated": bool}`

**超时说明：** 默认 600 秒，覆盖大多数测试/构建场景。LLM 调用耗时更长的命令时可显式传参（如 `timeout=1800`）。服务端不设无限等待以防命令卡死挂起 session。

**错误处理：**
- 超时 → `ToolResult(ok=False, error="Command timed out after <timeout>s")`
- 注意：returncode 非 0 不代表失败（grep 无匹配返回 1），`ok=True` 照常返回，由 LLM 判断

---

### 3.5 Glob

**文件：** `capabilities/tools/glob/__init__.py`  
**权限层级：** `PermissionTier.LOW`

**参数：**

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `pattern` | `str` | 是 | Glob 模式（如 `**/*.py`） |
| `path` | `str \| None` | 否 | 搜索根目录，默认当前工作目录 |

**行为：**
- 使用 Python `glob.glob(pattern, root_dir=path, recursive=True)`
- 结果按文件修改时间降序排列（最近修改的在前）
- 最多返回 100 条，超出时标记 `truncated=true`
- 返回相对于搜索根目录的路径
- 返回格式：`{"files": list[str], "count": int, "truncated": bool}`

---

### 3.6 Grep

**文件：** `capabilities/tools/grep/__init__.py`  
**权限层级：** `PermissionTier.LOW`

**参数：**

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `pattern` | `str` | 是 | 正则表达式 |
| `path` | `str \| None` | 否 | 搜索目录或文件，默认当前工作目录 |
| `glob` | `str \| None` | 否 | 文件过滤模式（如 `*.py`） |
| `ignore_case` | `bool` | 否 | 大小写不敏感，默认 `false` |
| `context_lines` | `int \| None` | 否 | 匹配行前后各显示的行数 |
| `head_limit` | `int \| None` | 否 | 最多返回行数，默认 250 |

**行为：**
- 优先使用系统 `rg`（ripgrep），不可用时退回 `grep -rn`
- 启动前检测 ripgrep 可用性（`shutil.which("rg")`），结果缓存，避免每次检测
- 结果超 `head_limit` 时截断并标记
- 返回格式：`{"output": str, "truncated": bool, "backend": "ripgrep" | "grep"}`

---

## 4. 参数类型强制转换（`_coerce_args`）

**位置：** `sebastian/core/tool.py`，在 `call_tool` 调用实际工具函数前执行。

```python
import inspect
from typing import get_type_hints, get_origin, get_args, Union

def _coerce_args(fn: Callable, kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    根据函数签名的类型注解，对传入参数做宽松类型转换。
    支持：str→int, str→float, str→bool, str→None（对应 X | None）。
    转换失败时保留原值，由函数签名校验兜底。
    """
    try:
        hints = get_type_hints(fn)
    except Exception:
        return kwargs

    result = dict(kwargs)
    for name, value in kwargs.items():
        if not isinstance(value, str):
            continue
        hint = hints.get(name)
        if hint is None:
            continue
        target = _unwrap_optional(hint)  # 拆 X | None → X
        if target is int:
            try:
                result[name] = int(value)
            except ValueError:
                pass
        elif target is float:
            try:
                result[name] = float(value)
            except ValueError:
                pass
        elif target is bool:
            result[name] = value.lower() in ("true", "1", "yes")
    return result


def _unwrap_optional(hint: Any) -> Any:
    """将 X | None 拆解为 X；非 Optional 类型原样返回。"""
    if get_origin(hint) is Union:
        args = [a for a in get_args(hint) if a is not type(None)]
        return args[0] if len(args) == 1 else hint
    return hint
```

`call_tool` 调用链：`call_tool(name, **kwargs)` → `_coerce_args(fn, kwargs)` → `fn(**coerced_kwargs)`

---

## 5. 权限层级汇总

| 工具 | `PermissionTier` | 理由 |
|------|-----------------|------|
| Read | LOW | 只读，无副作用 |
| Glob | LOW | 只读，仅返回路径 |
| Grep | LOW | 只读，内容搜索 |
| Write | MODEL_DECIDES | 全量覆盖文件，有副作用 |
| Edit | MODEL_DECIDES | 修改文件内容，有副作用 |
| Bash | MODEL_DECIDES | 执行 shell 命令，副作用不确定 |

---

## 6. 旧工具处理

- 删除 `sebastian/capabilities/tools/file_ops/`（含 `__init__.py`）
- 删除 `sebastian/capabilities/tools/shell/`（含 `__init__.py`）
- 保留 `sebastian/capabilities/tools/web_search/`，不做任何改动

删除前确认无其他模块直接 import `file_ops` 或 `shell`（工具通过名称字符串调用，不直接 import）。

---

## 7. 测试策略

**单元测试（`tests/unit/`）：**
- `test_file_state.py`：`record_read`、`check_write`、`invalidate` 各路径
- `test_tool_coerce.py`：`_coerce_args` 对 int/float/bool/Optional 的转换
- `test_tool_edit.py`：0次/1次/多次匹配的三种行为；replace_all 逻辑

**集成测试（`tests/integration/`）：**
- `test_tools_read_write.py`：Read→Write 流程、mtime 校验拒绝场景
- `test_tools_edit.py`：Read→Edit→Read 验证内容变更
- `test_tools_glob_grep.py`：实际文件系统的 Glob/Grep 调用

**不测试：**
- Bash 的实际命令执行（依赖宿主环境，集成测试范畴）
- 图片/PDF 处理（本期不实现）

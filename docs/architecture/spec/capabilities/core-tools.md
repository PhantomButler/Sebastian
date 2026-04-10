---
version: "1.0"
last_updated: 2026-04-10
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

行为：`asyncio.create_subprocess_shell` 异步执行，`cwd` 设为 `workspace_dir`。stdout + stderr 超 10000 字符时截断。超时后 `proc.kill()` 并返回错误。

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

*← [Capabilities 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

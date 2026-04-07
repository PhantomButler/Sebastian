# capabilities/tools — Native 工具插件目录

> 上级索引：[capabilities/](../README.md)

## 模块职责

存放所有以 `@tool` 装饰器注册的 Native 工具。服务启动时由 `_loader.py` 自动扫描本目录，导入所有非下划线前缀的子目录包，触发 `@tool` 自注册到全局工具注册表，无需手动配置。所有 tool call 经过 `PolicyGate` 执行，根据 `permission_tier` 决定是直接执行、PermissionReviewer 审查，还是强制向用户发起审批。

## 目录结构

```
tools/
├── __init__.py          # 模块入口（空）
├── _loader.py           # 启动时扫描子目录包，触发 @tool 自注册
├── _file_state.py       # 文件读取状态追踪（保障 Write/Edit 前置 Read 约束）
├── _path_utils.py       # 统一文件路径解析（相对路径 → workspace_dir，所有工具必须使用）
├── bash/                # Shell 命令执行工具（permission_tier: MODEL_DECIDES）
│   └── __init__.py      # @tool: bash_execute
├── edit/                # 文件精准字符串替换工具（permission_tier: MODEL_DECIDES）
│   └── __init__.py      # @tool: file_edit
├── glob/                # 文件模式匹配工具（permission_tier: LOW）
│   └── __init__.py      # @tool: file_glob
├── grep/                # 文件内容正则搜索工具，优先 ripgrep（permission_tier: LOW）
│   └── __init__.py      # @tool: file_grep
├── read/                # 文件读取工具（permission_tier: LOW）
│   └── __init__.py      # @tool: file_read
└── write/               # 文件写入工具，含 mtime 保护（permission_tier: MODEL_DECIDES）
    └── __init__.py      # @tool: file_write
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增工具 | 本目录新建子目录 + `__init__.py` + `@tool` 装饰器，重启自动注册 |
| 修改工具自动扫描逻辑 | [_loader.py](_loader.py) |
| 修改文件读取状态保护 | [_file_state.py](_file_state.py) |
| 修改路径解析基准（workspace_dir） | [_path_utils.py](_path_utils.py) |
| Shell 命令执行工具 | [bash/\_\_init\_\_.py](bash/__init__.py) |
| 文件精准替换工具 | [edit/\_\_init\_\_.py](edit/__init__.py) |
| 文件模式匹配工具 | [glob/\_\_init\_\_.py](glob/__init__.py) |
| 文件内容搜索工具 | [grep/\_\_init\_\_.py](grep/__init__.py) |
| 文件读取工具 | [read/\_\_init\_\_.py](read/__init__.py) |
| 文件写入工具 | [write/\_\_init\_\_.py](write/__init__.py) |

## ToolResult 规范

所有 tool 函数必须返回 `ToolResult`：

```python
from sebastian.core.types import ToolResult

ToolResult(ok=True, output={"key": "value"})   # 成功
ToolResult(ok=False, error="错误描述")          # 失败
```

## 三档权限详解

| 档位 | 常量 | 行为 | 适用场景 |
|------|------|------|----------|
| Tier 1 | `PermissionTier.LOW` | 直接执行，无拦截 | 只读、无副作用（读文件、搜索） |
| Tier 2 | `PermissionTier.MODEL_DECIDES` | 注入 `reason` 字段，PermissionReviewer 审查，决定执行或上报用户 | 有副作用但可能合理（写文件、执行命令） |
| Tier 3 | `PermissionTier.HIGH_RISK` | 每次必定向用户发起审批 | 不可逆操作（删除文件、系统命令） |

> 注意：`MODEL_DECIDES` 工具的 `reason` 参数由系统自动注入/提取，**不要**在函数签名里定义它。

## 新增工具完整步骤

### 1. 新建目录

```bash
mkdir sebastian/capabilities/tools/my_tool
```

### 2. 创建 `__init__.py`

```python
# sebastian/capabilities/tools/my_tool/__init__.py
from __future__ import annotations

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="my_tool",
    description="工具的清晰描述，告诉 LLM 它能做什么",
    permission_tier=PermissionTier.LOW,  # 根据风险选择档位
)
async def my_tool(param: str) -> ToolResult:
    try:
        result = do_something(param)
        return ToolResult(ok=True, output={"result": result})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

### 3. 文件路径参数的强制规范

工具函数中凡涉及文件路径参数，**必须**使用 `_path_utils.resolve_path()`，禁止直接调用 `os.path.abspath()`：

```python
# ✅ 正确
from sebastian.capabilities.tools._path_utils import resolve_path

async def my_tool(file_path: str) -> ToolResult:
    path = resolve_path(file_path)  # 相对路径 → workspace_dir，绝对路径原样 resolve
    ...

# ❌ 禁止
import os
path = os.path.abspath(file_path)  # 基准是进程 cwd，与 workspace 不一致
```

`resolve_path()` 保证：相对路径统一解析到 `workspace_dir`；绝对路径直接 `resolve()`。PolicyGate 也使用同一函数做 workspace 边界判断，两处解析结果必须一致。

### 4. 重启服务

无需其他配置，重启后 `_loader.py` 自动扫描并注册。

## 常见错误

| 错误 | 原因 | 修复 |
|------|------|------|
| `reason` 参数出现在函数签名里 | `MODEL_DECIDES` 工具的 `reason` 由系统自动注入/提取 | 从函数签名中删除 `reason` 参数 |
| 工具注册后找不到 | 目录名以 `_` 开头，`_loader` 会跳过 | 重命名目录，去掉 `_` 前缀 |
| 工具函数不是 `async` | 导入成功但调用时出错 | 将函数改为 `async def` |
| 同名工具覆盖 | 两个工具使用相同的 `name` | 确保 `@tool(name=...)` 全局唯一 |
| 文件写到 workspace 外 | 使用了 `os.path.abspath()`，基准是进程 cwd | 改用 `resolve_path()` from `_path_utils` |

## MCP 工具的权限处理

通过 `mcps/config.toml` 注册的 MCP 工具没有显式的 `permission_tier` 元数据，`PolicyGate` 默认按 `MODEL_DECIDES` 处理（保守策略）。

---

> 修改本目录或模块后，请同步更新此 README。

# Tool 系统完整指南

## 概述

Tool 是 Sebastian 中 Agent 调用外部能力的核心扩展机制。每个 tool 是一个被 `@tool` 装饰器注册的异步函数，系统启动时由 `_loader.py` 自动扫描并注册到全局注册表，无需手动配置。

所有 tool call 经过 `PolicyGate` 执行，根据工具的 `permission_tier` 元数据决定是直接执行、交给 PermissionReviewer 审查，还是强制向用户发起审批。

---

## ToolResult

所有 tool 函数必须返回 `ToolResult`：

```python
from sebastian.core.types import ToolResult

ToolResult(ok=True, output={"key": "value"})   # 成功
ToolResult(ok=False, error="错误描述")          # 失败
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 执行是否成功 |
| `output` | `Any` | 成功时的返回数据（任意可序列化结构） |
| `error` | `str \| None` | 失败时的错误描述 |

---

## @tool 装饰器参数

```python
from sebastian.core.tool import tool
from sebastian.permissions.types import PermissionTier

@tool(
    name="my_tool",          # 工具名，全局唯一，LLM 调用时使用
    description="工具说明",   # 清晰描述用途，LLM 根据此决定何时调用
    permission_tier=PermissionTier.LOW,  # 权限档位（见下方）
)
async def my_tool(param: str) -> ToolResult:
    ...
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 全局唯一工具名 |
| `description` | `str` | 必填 | 供 LLM 理解工具用途 |
| `permission_tier` | `PermissionTier` | `PermissionTier.LOW` | 执行前的权限级别 |

---

## 三档权限详解

### Tier 1 — LOW（直接执行）

```python
permission_tier=PermissionTier.LOW
```

无任何拦截，直接执行。适用于只读、无副作用的操作。

**适用场景：** 读取文件内容、搜索网页、查询只读状态

**示例：**
```python
@tool(name="file_read", description="读取文件内容", permission_tier=PermissionTier.LOW)
async def file_read(path: str) -> ToolResult:
    ...
```

---

### Tier 2 — MODEL_DECIDES（PermissionReviewer 审查）

```python
permission_tier=PermissionTier.MODEL_DECIDES
```

系统自动在工具 schema 中注入 `reason: string` 必填字段，LLM 调用时必须填写原因。系统将工具调用 + reason + 当前任务目标传给 PermissionReviewer（无状态 LLM 审查器），由它决定：
- **proceed**：直接执行，无需用户介入
- **escalate**：向用户发起审批请求，携带审查原因说明

> **注意：** 工具函数本身**不需要**定义 `reason` 参数，系统自动注入和提取，函数签名里写了反而会出错。

**适用场景：** 写入文件、执行 shell 命令、发送消息等有副作用但结果可能合理的操作

**示例：**
```python
@tool(
    name="file_write",
    description="写入文件内容",
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def file_write(path: str, content: str) -> ToolResult:
    # 函数签名里不要写 reason 参数
    ...
```

---

### Tier 3 — HIGH_RISK（必定用户审批）

```python
permission_tier=PermissionTier.HIGH_RISK
```

无论模型意图如何，每次调用必定向用户发起审批。用户批准后执行，拒绝后返回 `ToolResult(ok=False, error="User denied approval for this tool call.")`。

**适用场景：** 删除文件/目录、格式化磁盘、访问密钥/密码、终止进程等不可逆操作

**示例：**
```python
@tool(
    name="delete_file",
    description="永久删除指定路径的文件或目录",
    permission_tier=PermissionTier.HIGH_RISK,
)
async def delete_file(path: str) -> ToolResult:
    ...
```

---

## 创建新 Tool 的完整步骤

### 1. 新建目录

在 `sebastian/capabilities/tools/` 下创建以 tool 名命名的目录：

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

### 3. 多文件结构（可选）

如果工具逻辑复杂，可拆分辅助模块：

```
tools/my_tool/
    __init__.py    # @tool 装饰器和入口函数
    _helpers.py    # 辅助函数（_ 开头，_loader 不直接扫描）
    _models.py     # 数据模型
```

`__init__.py` 中 import 辅助模块：

```python
from sebastian.capabilities.tools.my_tool._helpers import process_data
```

### 4. 重启服务

无需任何其他配置，重启后 `_loader.py` 自动扫描并注册：

```bash
uvicorn sebastian.gateway.app:app --reload
```

---

## 类型注解规范

函数参数支持以下类型（自动映射到 JSON Schema）：

| Python 类型 | JSON Schema 类型 |
|---|---|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| 其他 | `string`（fallback） |

所有参数必须有类型注解，返回值固定为 `-> ToolResult`。

---

## 常见错误

| 错误 | 原因 | 修复 |
|---|---|---|
| `reason` 参数出现在函数签名里 | `MODEL_DECIDES` 工具的 `reason` 由系统自动注入/提取，工具函数不需要它 | 从函数签名中删除 `reason` 参数 |
| 工具注册后找不到 | 目录名以 `_` 开头，_loader 会跳过 | 重命名目录，去掉 `_` 前缀 |
| 工具函数不是 `async` | `_loader` 导入成功但调用时出错 | 将函数改为 `async def` |
| 同名工具覆盖 | 两个工具使用相同的 `name` | 确保 `@tool(name=...)` 全局唯一 |
| 类型推断失败 | 使用了不支持的参数类型 | 改用支持的类型，或 fallback 为 `str` |

---

## MCP 工具的权限处理

通过 `config.toml` 注册的 MCP 工具没有显式的 `permission_tier` 元数据，`PolicyGate` 默认按 `MODEL_DECIDES` 处理（保守策略）。

# capabilities/tools — Native 工具插件目录

> 上级索引：[capabilities/](../README.md)

## 模块职责

存放所有以 `@tool` 装饰器注册的 Native 工具。服务启动时由 `_loader.py` 自动扫描本目录，导入所有非下划线前缀的子目录包，触发 `@tool` 自注册到全局工具注册表，无需手动配置。所有 tool call 经过 `PolicyGate` 执行，根据 `permission_tier` 决定是直接执行、PermissionReviewer 审查，还是强制向用户发起审批。

## 目录结构

```
tools/
├── __init__.py              # 模块入口（空）
├── _loader.py               # 启动时扫描子目录包，触发 @tool 自注册
├── _file_state.py           # 文件读取状态追踪（保障 Write/Edit 前置 Read 约束）
├── _path_utils.py           # 统一文件路径解析（相对路径 → workspace_dir，所有工具必须使用）
├── _session_lock.py         # Session 级 asyncio.Lock，防止并发 turn 冲突
├── _session_permission.py   # stop/resume 操作的 depth 边界权限校验（被 stop_agent/resume_agent 调用）
│
│   # ── 能力工具（manifest allowed_tools 白名单管控）────────────────
├── bash/                    # Shell 命令执行工具（permission_tier: MODEL_DECIDES）
│   └── __init__.py          # @tool: bash_execute
├── edit/                    # 文件精准字符串替换工具（permission_tier: MODEL_DECIDES）
│   └── __init__.py          # @tool: file_edit
├── glob/                    # 文件模式匹配工具（permission_tier: LOW）
│   └── __init__.py          # @tool: file_glob
├── grep/                    # 文件内容正则搜索工具，优先 ripgrep（permission_tier: LOW）
│   └── __init__.py          # @tool: file_grep
├── read/                    # 文件读取工具（permission_tier: LOW）
│   └── __init__.py          # @tool: file_read
├── todo_read/               # Session 级 todo 列表只读查询工具（permission_tier: LOW）
│   └── __init__.py          # @tool: todo_read
├── todo_write/              # Session 级 todo 列表覆盖式写入工具（permission_tier: LOW）
│   └── __init__.py          # @tool: todo_write
├── send_file/               # Agent 向用户发送文件/图片工具（permission_tier: MODEL_DECIDES）
│   └── __init__.py          # @tool: send_file
├── screenshot_send/          # Sebastian 截取后端主机屏幕并发送图片（permission_tier: HIGH_RISK，Sebastian-only）
│   └── __init__.py          # @tool: capture_screenshot_and_send
├── write/                   # 文件写入工具，含 mtime 保护（permission_tier: MODEL_DECIDES）
│   └── __init__.py          # @tool: file_write
├── memory_save/             # 显式记忆写入工具，仅在用户明确要求时使用（permission_tier: LOW）
│   └── __init__.py          # @tool: memory_save(content: str)；fire-and-forget，立即返回；后台调 MemoryExtractor 分配 slot，经 process_candidates() 写入；extractor 返回空则跳过
├── memory_search/           # 长期记忆检索工具（permission_tier: LOW）
│   └── __init__.py          # @tool: memory_search
│
│   # ── 协议工具（按 Agent 层级角色自动注入，无需在 manifest 声明）──
├── ask_parent/              # 子代理主动暂停并向上级请求指示（状态置 WAITING）
│   └── __init__.py          # @tool: ask_parent
├── check_sub_agents/        # 查询当前 Agent 创建的所有子代理会话状态
│   └── __init__.py          # @tool: check_sub_agents
├── delegate_to_agent/       # Sebastian 委派任务给 Sub-Agent（工具调用形式）
│   └── __init__.py          # @tool: delegate_to_agent
├── inspect_session/         # 查看指定 session 的最近消息与状态
│   └── __init__.py          # @tool: inspect_session
├── resume_agent/            # 恢复 waiting/idle 子代理执行
│   └── __init__.py          # @tool: resume_agent
├── spawn_sub_agent/         # 组长创建 depth=3 子代理 session
│   └── __init__.py          # @tool: spawn_sub_agent
└── stop_agent/              # 暂停运行中的子代理到 idle（可恢复）
    └── __init__.py          # @tool: stop_agent
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增工具 | 本目录新建子目录 + `__init__.py` + `@tool` 装饰器，重启自动注册 |
| 修改工具自动扫描逻辑 | [_loader.py](_loader.py) |
| 修改文件读取状态保护 | [_file_state.py](_file_state.py) |
| 修改路径解析基准（workspace_dir） | [_path_utils.py](_path_utils.py) |
| 修改 session 并发锁 | [_session_lock.py](_session_lock.py) |
| 修改 stop/resume 权限边界规则 | [_session_permission.py](_session_permission.py) |
| Shell 命令执行工具 | [bash/\_\_init\_\_.py](bash/__init__.py) |
| 文件精准替换工具 | [edit/\_\_init\_\_.py](edit/__init__.py) |
| 文件模式匹配工具 | [glob/\_\_init\_\_.py](glob/__init__.py) |
| 文件内容搜索工具 | [grep/\_\_init\_\_.py](grep/__init__.py) |
| 文件读取工具 | [read/\_\_init\_\_.py](read/__init__.py) |
| Todo 列表只读查询工具 | [todo_read/\_\_init\_\_.py](todo_read/__init__.py) |
| Todo 列表写入工具 | [todo_write/\_\_init\_\_.py](todo_write/__init__.py) |
| Agent 向用户发送文件/图片工具 | [send_file/\_\_init\_\_.py](send_file/__init__.py) |
| Sebastian 截图并发送 | [screenshot_send/\_\_init\_\_.py](screenshot_send/__init__.py) |
| 文件写入工具 | [write/\_\_init\_\_.py](write/__init__.py) |
| 显式记忆写入工具 | [memory_save/\_\_init\_\_.py](memory_save/__init__.py) |
| 长期记忆检索工具 | [memory_search/\_\_init\_\_.py](memory_search/__init__.py) |
| 子代理主动请示上级 | [ask_parent/\_\_init\_\_.py](ask_parent/__init__.py) |
| 查询子代理状态 | [check_sub_agents/\_\_init\_\_.py](check_sub_agents/__init__.py) |
| Sebastian 委派任务 | [delegate_to_agent/\_\_init\_\_.py](delegate_to_agent/__init__.py) |
| 查看 session 进展 | [inspect_session/\_\_init\_\_.py](inspect_session/__init__.py) |
| 恢复子代理执行 | [resume_agent/\_\_init\_\_.py](resume_agent/__init__.py) |
| 创建 depth=3 子代理 | [spawn_sub_agent/\_\_init\_\_.py](spawn_sub_agent/__init__.py) |
| 暂停子代理 | [stop_agent/\_\_init\_\_.py](stop_agent/__init__.py) |

## ToolResult 规范

所有 tool 函数必须返回 `ToolResult`：

```python
from sebastian.core.types import ToolResult

ToolResult(ok=True, output={"key": "value"})   # 成功
ToolResult(ok=False, error="错误描述")          # 失败
```

## 可选：填写 `display`

`ToolResult` 有一个可选的 `display: str | None` 字段，用于给 UI 展示的「输出」区提供干净文本。

- 不填（默认 `None`）时，runtime 会回退用 `str(output)[:4000]`。对 output 是字符串的工具（如 `delegate_to_agent`）回退已经够用；对 dict output 则会显示 Python repr，UI 上不好看。
- 填了 display 就用 display。典型做法是从 `output` 里抽用户真正关心的字段：

```python
return ToolResult(
    ok=True,
    output={"content": content, "total_lines": n, "truncated": flag},
    display=content,  # UI 只需看内容
)
```

默认情况下，给模型的 `tool_result` 由完整 `output` 生成；因此工具应避免把不该进入上下文的内容放进普通 `output`。带 `artifact` 的工具结果是例外窄通道：`artifact` 只保留在 timeline payload / SSE 中，实时回灌给 LLM 的 tool result 与历史 `model_content` 都必须使用轻量事实文本（通常来自 `display`）。`send_file` 只负责发送文件，不通过 tool result 把文本文件内容或预览回传给模型。

## 工具分类：能力工具 vs 协议工具

工具在设计上分为两类，面向不同的控制维度：

| 类别 | 工具 | 控制方式 | 说明 |
|------|------|---------|------|
| **能力工具** | Read / Write / Edit / Bash / Glob / Grep / todo_write / todo_read / send_file / capture_screenshot_and_send 等 | manifest `allowed_tools` 白名单 | 决定 Agent 的领域执行范围 |
| **协议工具** | ask_parent / resume_agent / stop_agent / spawn_sub_agent / check_sub_agents / inspect_session（sub-agent 自动注入）；delegate_to_agent（Sebastian 手工配置） | 按 Agent 层级角色分配 | 决定 Agent 在层级中的通信与监控方式 |

`capture_screenshot_and_send` 当前只加入 `Sebastian.allowed_tools`，不要加入 sub-agent manifest。

**`manifest.toml` 的 `allowed_tools` 只需声明能力工具。**
协议工具由 `_loader.py` 根据 Agent 角色自动追加，无需手动填写。
当前自动注入规则见 `sebastian/agents/_loader.py` 的 `_SUBAGENT_PROTOCOL_TOOLS`。

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

## 失败返回规范

工具失败必须返回 `ToolResult(ok=False, error=...)`，不要用成功结果承载失败。

`error` 应包含：
- 失败原因
- 下一步建议
- 对确定性失败明确写明 `Do not retry automatically; ...`

确定性失败包括文件不存在、路径是目录、权限不足、类型不支持、大小超限、缺 session context、服务未初始化等。模型收到这类错误后应停止同输入重试，转而告知用户或请求新输入。

临时性错误可以建议稍后重试，但不得在同一 turn 内无限重试。

## MCP 工具的权限处理

通过 `mcps/config.toml` 注册的 MCP 工具没有显式的 `permission_tier` 元数据，`PolicyGate` 默认按 `MODEL_DECIDES` 处理（保守策略）。

---

> 修改本目录或模块后，请同步更新此 README。

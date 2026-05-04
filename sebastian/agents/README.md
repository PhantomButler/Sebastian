# agents — Sub-Agent 插件目录

> 上级索引：[sebastian/](../README.md)

## 模块职责

存放各领域 Sub-Agent 实现。每个 Agent 是一个独立子目录，继承 `BaseAgent`，聚焦单一领域能力。Sebastian 主管家通过 `delegate_to_agent` 工具将任务委派给它们（异步 `asyncio.create_task`）。`_loader.py` 在服务启动时自动扫描所有包含 `manifest.toml` 的子目录并完成注册，无需修改任何注册代码。

## 目录结构

```
agents/
├── __init__.py          # 模块入口（空）
├── _loader.py           # 启动时扫描 manifest.toml，自动注册所有 Agent
├── aide/                # 通用执行随从 Sub-Agent（命令执行、文件操作、系统任务）
│   ├── __init__.py      # AideAgent 类定义（继承 BaseAgent）
│   └── manifest.toml    # Agent 声明（max_children=3，allowed_tools 同 forge）
└── forge/               # 代码编写与执行 Sub-Agent
    ├── __init__.py      # ForgeAgent 类定义（继承 BaseAgent）
    ├── manifest.toml    # Agent 元数据（描述、class_name、worker 数、工具权限等）
    ├── tools/           # Agent 私有工具（不对其他 Agent 暴露）
    │   └── __init__.py
    └── knowledge/       # 领域知识文件（文档、规则等）
        └── engineering_guidelines.md
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Sub-Agent | 本目录新建子目录 + `__init__.py` + `manifest.toml` |
| 修改 Agent 人设（persona） | `<agent_name>/__init__.py` 的 `persona` 字段 |
| 修改 Agent 工具权限 | `<agent_name>/manifest.toml` 的 `allowed_tools` |
| 修改最大并发子任务数 | `<agent_name>/manifest.toml` 的 `max_children` |
| 新增 Agent 私有工具 | `<agent_name>/tools/` 下新建 `__init__.py` + `@tool` 装饰器 |
| 修改 Agent 自动发现逻辑 | [_loader.py](_loader.py) |
| 通用执行 Agent | [aide/](aide/__init__.py) |
| 代码编写 Agent | [forge/](forge/__init__.py) |

## 如何新增 Sub-Agent

### 1. 创建 Agent 类（`__init__.py`）

```python
from sebastian.core.base_agent import BaseAgent

class MyAgent(BaseAgent):
    name = "my_agent"
    persona = (
        "You are a specialist in ... serving {owner_name}. "
        "..."
    )
```

注意：
- Agent 只有一个名字——**目录名即 `agent_type`**，是系统唯一标识（如 `forge`）。manifest 不再有 `name` 字段；UI 展示时由前端做 capitalize（`forge` → `Forge`）。
- 字段名是 `persona`，不是 `system_prompt`
- `{owner_name}` 是运行时占位符，会被自动替换为实际用户名

### 2. 创建 `manifest.toml`（必须）

`_loader.py` 靠 `manifest.toml` 发现 Agent，**没有此文件则该 Agent 不会被加载**。

```toml
[agent]
description = "做什么用的一句话描述"
class_name = "MyAgent"                     # __init__.py 中的类名（必须精确匹配）
max_children = 5                           # 最大并发 depth=3 子任务数（默认 5）
stalled_threshold_minutes = 5             # 多少分钟无活动判定为 stalled（默认 5）
allowed_tools = ["Read", "Bash", "Glob"]  # 能力工具白名单；不写则仅协议工具（见下）
allowed_skills = []                        # 允许使用的 skill 列表
```

**`allowed_tools` 只需声明能力工具，协议工具由系统自动注入。**

| 类别 | 工具 | 声明方式 |
|------|------|---------|
| **能力工具**（领域执行） | Read / Write / Edit / Bash / Glob / Grep / todo_read / send_file 等 | 在 `allowed_tools` 里显式列出 |
| **协议工具**（层级通信） | `ask_parent` 等 | `_loader.py` 自动追加，**无需写入 manifest** |

不写 `allowed_tools` 或写 `allowed_tools = []` 表示仅自动注入协议工具，不允许任何能力工具。
如果确实需要全量能力工具，必须显式写 `allowed_tools = "ALL"`。

`spawn_sub_agent` 和 `ask_parent` 同为协议工具，均自动注入，无需手动声明。

## `allowed_tools` 白名单语义

Sub-agent 在 `manifest.toml` 中通过 `allowed_tools` 声明能力边界。
该白名单在两层强制生效：

1. **LLM 可见性层**：传给 LLM 的 `tools` 参数按白名单过滤，LLM 看不到白名单外的工具。
2. **执行校验层**：`PolicyGate.call()` Stage 0 前置校验 `tool_name`，即使 LLM 幻觉出白名单外的工具名也会被拒绝。

### 四种取值

| manifest 声明 | Sub-agent 最终白名单 | 含义 |
|---|---|---|
| 未声明（缺省） | 6 个协议工具 | 仅具备通信能力，无领域工具 |
| `allowed_tools = []` | 6 个协议工具 | 仅具备通信能力，无领域工具 |
| `allowed_tools = ["Read"]` | `Read` + 6 个协议工具 | Read + 通信能力 |
| `allowed_tools = "ALL"` | `ALL_TOOLS` | 显式允许全量工具 |

### 协议工具（6 个，由 `_loader.py` 自动追加）

| 工具 | 用途 |
|---|---|
| `ask_parent` | 向上级请示，暂停等待回复 |
| `resume_agent` | 恢复 waiting/idle 下属 session 的执行 |
| `stop_agent` | 暂停运行中的下属 session（转 idle） |
| `spawn_sub_agent` | 向下分派 depth=3 组员 |
| `check_sub_agents` | 查看自己组员的任务状态 |
| `inspect_session` | 查看指定 session 的详细进展 |

这 6 个工具决定 sub-agent 在层级中的通信能力，不属于领域能力范畴，所以自动注入，不需要每个 manifest 手动声明。

### Sebastian vs Sub-agent 协议工具对比

Sebastian 主管家**不经过 `_loader.py`**，`allowed_tools` 在 `sebastian/orchestrator/sebas.py` 中手工维护，不享受自动协议注入。

| 能力 | Sebastian (depth=1) | 组长 (depth=2) | 组员 (depth=3) |
|---|---|---|---|
| 向下派活 | `delegate_to_agent` | `spawn_sub_agent` | — |
| 回复下属 | `resume_agent` | `resume_agent` | — |
| 暂停下属 | `stop_agent` | `stop_agent` | — |
| 问上级 | — (无上级) | `ask_parent` | `ask_parent` |
| 查下属进度 | `check_sub_agents` | `check_sub_agents` | — |
| 查 session | `inspect_session` | `inspect_session` | `inspect_session` |

> 当前实现中 depth=2 和 depth=3 共用同一套协议 6 工具：组员可见但会被工具内部权限校验拦截（例如 `resume_agent` / `stop_agent` 对 depth>=3 返回拒绝）。

### 3. 重启服务

`_loader.py` 在启动时自动扫描，无需修改任何注册代码。

## 注意事项

- 私有工具放在 `agents/<name>/tools/`，**不要**放到 `capabilities/tools/`（后者是全局共享工具）
- Agent 只能通过工具调用执行副作用操作，不允许直接 `exec()` 或 `subprocess`（走 `sandbox/` 沙箱）
- `manifest.toml` 是必须文件，缺失则该 Agent 被静默跳过（`_loader.py` 会打 warning 日志）
- 目录名以 `_` 开头会被 `_loader.py` 自动跳过

## 外部扩展

`_loader.py` 支持通过 `extra_dirs` 加载外部目录中的 Agent（用于用户自定义 Agent、知识库扩展等）。外部同名 Agent 会覆盖内置 Agent。扫描路径由 `gateway/app.py` 在启动时传入，通常指向 `~/.sebastian/extensions/agents/`。

---

> 修改本目录或模块后，请同步更新此 README。

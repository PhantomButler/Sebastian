# agents — Sub-Agent 插件目录

## 职责

存放各领域 Sub-Agent 实现。每个 Agent 是一个独立子目录，继承 `BaseAgent`，聚焦单一领域能力。Sebastian 主管家通过 A2A 协议委派任务给它们。

## 目录结构

```
agents/
  <agent_name>/
    __init__.py           # Agent 类定义（继承 BaseAgent）
    manifest.toml         # 元数据（必须存在，_loader.py 靠此发现 Agent）
    tools/                # 该 Agent 私有工具（不对其他 Agent 暴露，可选）
    knowledge/            # 领域知识文件（文档、规则等，可选）
```

## 现有 Agent

| 目录 | 领域 |
|---|---|
| `code/` | 代码编写与执行 |
| `stock/` | 股票/投资分析 |
| `life/` | 生活助理（日程、提醒等） |

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
- 字段名是 `persona`，不是 `system_prompt`
- `{owner_name}` 是运行时占位符，会被自动替换为实际用户名

### 2. 创建 `manifest.toml`（必须）

`_loader.py` 靠 `manifest.toml` 发现 Agent，**没有此文件则该 Agent 不会被加载**。

```toml
[agent]
name = "My Agent"                          # 显示名称
description = "做什么用的一句话描述"
worker_count = 3                           # 并发 worker 数
class_name = "MyAgent"                     # __init__.py 中的类名（必须精确匹配）
allowed_tools = ["Read", "Bash", "Glob"]  # 允许使用的工具名列表，null 表示不限制
allowed_skills = []                        # 允许使用的 skill 列表
```

**可用工具名**（`capabilities/tools/` 下的全局工具）：

| 工具 | 用途 |
|------|------|
| `Read` | 读取文件 |
| `Write` | 写入文件（需先 Read） |
| `Edit` | 精准替换文件内容（需先 Read） |
| `Bash` | 执行 Shell 命令 |
| `Glob` | 文件模式匹配 |
| `Grep` | 文件内容搜索 |

`allowed_tools = null`（不写此字段）表示不限制，Agent 可用所有工具。

### 3. 重启服务

`_loader.py` 在启动时自动扫描，无需修改任何注册代码。

## 注意事项

- 私有工具放在 `agents/<name>/tools/`，**不要**放到 `capabilities/tools/`（后者是全局共享工具）
- Agent 只能通过工具调用执行副作用操作，不允许直接 `exec()` 或 `subprocess`（走 `sandbox/` 沙箱）
- `manifest.toml` 是必须文件，缺失则该 Agent 被静默跳过（`_loader.py` 会打 warning 日志）

## 扩展 Agent 目录

`_loader.py` 支持通过 `extra_dirs` 加载外部目录中的 Agent（用于用户自定义 Agent、知识库扩展等）。外部同名 Agent 会覆盖内置 Agent。扫描路径由 `gateway/app.py` 在启动时传入，通常指向 `~/.sebastian/extensions/agents/`。

## 常见任务入口

- **新增 Sub-Agent** → 本目录新建子目录 + `__init__.py` + `manifest.toml`
- **修改 Agent 人设** → 对应 `<agent_name>/__init__.py` 的 `persona` 字段
- **新增 Agent 私有工具** → `<agent_name>/tools/` 下新建文件 + `@tool` 装饰器
- **修改 Agent 工具权限** → 对应 `<agent_name>/manifest.toml` 的 `allowed_tools`
- **修改 Agent 自动发现逻辑** → `sebastian/agents/_loader.py`

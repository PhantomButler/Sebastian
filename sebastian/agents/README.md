# agents — Sub-Agent 插件目录

## 职责

存放各领域 Sub-Agent 实现。每个 Agent 是一个独立子目录，继承 `BaseAgent`，聚焦单一领域能力。Sebastian 主管家通过 A2A 协议委派任务给它们。

## 目录结构

```
agents/
  <agent_name>/
    __init__.py           # Agent 类定义（继承 BaseAgent）
    manifest.toml         # 元数据（名称、描述、能力标签）—— Phase 2+ 启用
    tools/                # 该 Agent 私有工具（不对其他 Agent 暴露）
    knowledge/            # 领域知识文件（文档、规则等）
```

## 现有 Agent

| 目录 | 领域 |
|---|---|
| `code/` | 代码编写与执行 |
| `stock/` | 股票/投资分析 |
| `life/` | 生活助理（日程、提醒等） |

## 如何新增 Sub-Agent

1. 在 `agents/<name>/` 下创建目录
2. `__init__.py` 中定义继承 `BaseAgent` 的类，设置 `name` 和 `system_prompt`
3. 如有私有工具，放 `tools/` 下，使用 `@tool` 装饰器（与 `capabilities/tools/` 相同方式）
4. `manifest.toml` 在 Phase 2+ 启用后填写（当前可不创建）
5. 重启后 `app.py` 自动发现并为其创建 AgentPool

```python
# 示例
from sebastian.core.base_agent import BaseAgent

class MyAgent(BaseAgent):
    name = "my_agent"
    system_prompt = "You are a specialist in ..."
```

## 注意事项

- 私有工具放在 `agents/<name>/tools/`，**不要**放到 `capabilities/tools/`（后者是全局共享工具）
- Agent 只能通过 `registry` 调用工具，不允许直接 `exec()` 或 `subprocess`（走 `sandbox/` 沙箱）
- 目前 manifest.toml 还未被运行时读取，注册逻辑在 `app.py` 的目录扫描中

## 常见任务入口

- **新增 Sub-Agent** → 本目录新建子目录 + `__init__.py`
- **修改已有 Agent 的 system prompt** → 对应 `<agent_name>/__init__.py`
- **新增 Agent 私有工具** → `<agent_name>/tools/` 下新建文件 + `@tool` 装饰器
- **修改 Agent 自动发现逻辑** → `gateway/app.py` 的 `_discover_agent_types()`

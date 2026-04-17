---
version: "1.0"
last_updated: 2026-04-17
status: implemented
---

# Agent 命名统一：移除 display_name，统一 agent_type

*← [Agents 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景

此前 Sub-Agent 有两个名字：

- `agent_type`：目录名派生（`sebastian/agents/forge/` → `"forge"`），用作注册表 key、filesystem 路径、URL path、LLM 工具参数
- `display_name`：`manifest.toml [agent].name` 配置（如 `"Forge"`），仅用作 UI 展示

二元命名增加了认知负担和代码复杂度（LLM prompt 需区分、API 需双字段、前端需映射）。

**决策：移除 `display_name`，让每个 agent 只有一个名字——`agent_type`（小写 identifier）。** 用户侧的 title-case 展示由前端在渲染时 `capitalize()`。示范性重命名将 `code` 改为 `forge`（与主管家 `sebastian` 的命名风格统一）。

---

## 2. 命名约定

`agent_type` 是小写 identifier（合法 Python 包名 + filesystem 安全 + URL 安全），同时担任：

| 角色 | 位置 | 示例 |
|------|------|------|
| 目录名 | `sebastian/agents/{agent_type}/` | `sebastian/agents/forge/` |
| Python 包名 | `from sebastian.agents.{agent_type} import ...` | `sebastian.agents.forge` |
| 注册表 key | `state.agent_registry[agent_type]` | `"forge"` |
| Session filesystem 路径 | `sessions/{agent_type}/{session_id}/` | `sessions/forge/2026-04-14T.../` |
| URL path param | `GET /agents/{agent_type}/sessions` | `/agents/forge/sessions` |
| LLM tool 参数值 | `delegate_to_agent(agent_type="...")` | `"forge"` |
| UI 展示基底（前端 capitalize） | `agent_type.capitalize()` | `"Forge"` |

---

## 3. 改动清单

### 3.1 后端

**目录 + 类重命名**

- `sebastian/agents/code/` → `sebastian/agents/forge/`
- `__init__.py`: `class CodeAgent` → `class ForgeAgent`, `name = "forge"`（persona 文本不动）
- `manifest.toml`: 删 `name = "Forge"` 行，`class_name` 改 `"ForgeAgent"`

**`sebastian/agents/_loader.py`**

- `AgentConfig` dataclass 删 `display_name: str` 字段
- 构造 AgentConfig 时不再读 `agent_section.get("name", ...)`
- `manifest.toml` 里历史遗留的 `name = "..."` 字段静默忽略

**`sebastian/capabilities/tools/delegate_to_agent/__init__.py`**

- 删除 `display_name` 查表逻辑
- 返回文案改用 `agent_type.capitalize()`

**`sebastian/gateway/completion_notifier.py`**

- 两处通知文案改用 `agent_type.capitalize()`

**`sebastian/gateway/routes/agents.py`**

- JSON 返回体删 `"name"` 字段
- 保留：`agent_type` / `description` / `active_session_count` / `max_children`

**`sebastian/gateway/app.py`**

- 日志简化
- 启动自检：扫描 `sessions/` 下孤儿目录（不在 registry 的 agent_type），打 warning

**`sebastian/orchestrator/sebas.py`**

- `_agents_section()` 渲染简化，删除 "display name" / "exact agent_type" 区分性措辞

### 3.2 前端（Android）

- `AgentDto.kt` / `AgentInfo.kt` 删 `name` 字段，新增 `displayName` 扩展属性（`agentType.replaceFirstChar { it.uppercase() }`）
- `AgentListScreen.kt` 使用 `agent.displayName`
- `ToolCallInputExtractor.kt` 删除 `delegate_to_agent` + `agent_type` uppercase 特例
- `ToolDisplayName.kt` 的 `delegate_to_agent` 分支统一使用 `capitalize()`

### 3.3 前端（Web / React Native）

- `ui/mobile/src/api/agents.ts` 删 `agent.name` 映射，`displayName` 从 `titleCase(agent.id)` 派生

---

## 4. 数据迁移

**方式：CHANGELOG 说明 + 用户手动**

理由：单用户自托管，数据在用户自己机器；项目早期，历史 session 可接受弃置。

**启动自检（软提醒）**

Gateway lifespan 末段扫 `sessions/` 下所有目录，不在 registry 且不是 `sebastian` 的打 warning。

---

## 5. 文件索引

- 后端核心：`sebastian/agents/_loader.py`, `sebastian/capabilities/tools/delegate_to_agent/__init__.py`, `sebastian/gateway/completion_notifier.py`, `sebastian/gateway/routes/agents.py`, `sebastian/gateway/app.py`, `sebastian/orchestrator/sebas.py`
- 重命名：`sebastian/agents/code/` → `sebastian/agents/forge/`
- Android 核心：`ui/mobile-android/.../ToolDisplayName.kt`, `ToolCallInputExtractor.kt`, `data/model/AgentInfo.kt`, `data/remote/dto/AgentDto.kt`

---

*← [Agents 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---
version: "1.4"
last_updated: 2026-05-09
status: implemented
---

# System Prompt 构造机制

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

1. 为 Sebastian 定义有深度的角色人设提示词
2. 将 prompt 构造机制提升至 `BaseAgent`，结构化、可扩展
3. 支持 per-agent 工具可见性（`manifest.toml` 声明）
4. 新增 Agent 只需建目录 + 配置，无需改代码
5. Sebastian 主管家 persona 支持 soul 文件热切换，切换后下个 LLM turn 立即生效

---

## 2. Sebastian 人设提示词

### 2.1 结构拆分（v1.1 起）

人设段由两部分拼接，由 `Sebastian._persona_section()` 负责组装：

```
BASE_BUTLER_RULES          ← 常量，始终注入，切换 soul 不变
─────────────────────────
soul 文件内容（中文）       ← 当前激活 soul 的人格灵魂，可热切换
```

**`BASE_BUTLER_RULES`**（`sebastian/orchestrator/sebas.py`）包含所有管家共用的行为约束：忠诚原则、身份呈现、顾问职责、能力边界、委派原则、行事规范。这些是系统机制，不随人格切换而变动。

身份呈现规则规定：当前 soul 是面向用户的第一人称身份。日常对话中，Agent 不应自称为 soul、persona、配置、模块、皮肤或 Sebastian 系统的一部分；只有用户明确询问实现机制、soul 切换原理或系统架构时，才说明后台事实。

**soul 文件**只含人格灵魂内容（性格、语气、自我定位），用中文书写，用户可直接编辑。内置两个预设：

- `sebastian.md`：优雅克制，维多利亚式正式腔调，带压制的骄傲
- `cortana.md`：敏锐温暖，洞察力强，工作时清醒利落，闲聊时更有人味和情绪回应

### 2.2 运行时注入

soul 文件内容在 gateway lifespan 启动时从 `~/.sebastian/data/souls/` 加载，通过 `switch_soul` 工具可热切换。详见第 7 节。

---

## 3. Prompt 构造体系

### 3.1 BaseAgent 方法体系

```python
class BaseAgent(ABC):
    persona: str = BASE_PERSONA  # 子类覆盖

    def build_system_prompt(
        self,
        gate: PolicyGate,
        agent_registry: Mapping[str, Any] | None = None,
    ) -> str:
        sections = [
            self._persona_section(),           # 角色人设
            self._guidelines_section(),        # 操作指南
            self._tools_section(gate),         # 可用工具
            self._skill_management_section() if self._can_use_bash() else "",
            self._agents_section(agent_registry),  # 下属 Agent
            self._knowledge_section(),         # 知识库
        ]
        return "\n\n".join(s for s in sections if s)
```

**Section 组合顺序**：persona → guidelines → tools → skill management → agents → knowledge（空 section 自动跳过）。Skill management 只有在该 Agent 可用 `Bash` 时注入。

**调用时机**：`BaseAgent.__init__` 末尾调用一次，结果存入 `self.system_prompt`，运行期不变。

### 3.2 各 section 职责

| 方法 | 说明 |
|------|------|
| `_persona_section()` | 角色人设段；Sebastian 覆盖此方法，拼接 `BASE_BUTLER_RULES` + soul 文件内容 |
| `_guidelines_section()` | 操作指南（通用行为规范） |
| `_tools_section(gate)` | 当前 Agent 可用工具摘要，按 allowed_tools 过滤 |
| `_skill_management_section()` | 固定的 Skill CLI bootstrap；仅 Bash-capable Agent 注入，只列 `sebastian skills` 发现/读取入口，不列已安装 Skill 名称，不注入 Skill body |
| `_agents_section(registry)` | 可调度的 Sub-Agent 列表（默认返回空，仅 Sebastian 覆盖） |
| `_knowledge_section()` | 知识库内容（默认返回空） |

---

## 4. per-agent 工具可见性

### 4.1 manifest.toml 声明

```toml
[agent]
class_name = "ForgeAgent"
description = "编写代码、调试问题、构建工具"
allowed_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
```

规则：
- 不声明 `allowed_tools` → 仅自动注入协议工具
- 空列表 `[]` → 明确声明无能力工具，仍自动注入协议工具
- Sebastian 主体不经过 manifest，默认全量
- `allowed_skills` manifest 字段不再支持；当前 progressive disclosure model 没有独立的 Skill 可见性名单。Skill 读取依赖 `Bash` + `sebastian skills` CLI

### 4.2 CapabilityRegistry 过滤

```python
def get_tool_specs(self, allowed: set[str] | None = None) -> list[dict]:
    """返回工具 spec 列表。allowed=None 表示不暴露能力工具。"""
```

---

## 5. Skill Management Bootstrap

`BaseAgent._skill_management_section()` 根据工具可见性决定是否注入固定 Skill bootstrap：

- 如果当前 Agent 可用 `Bash`，注入 `## Skill Management`，提示模型通过 `sebastian skills list/search/show/read` 按需发现和读取本地 Skill。
- 如果当前 Agent 不可用 `Bash`，不注入该 section，也不提示模型调用 Skill CLI。
- bootstrap 是固定短文本，不随已安装 Skill catalog 动态展开；它不会列出已安装 Skill 名称，也不会注入任何 `SKILL.md` 正文。

bootstrap 的发现策略是：遇到可复用的领域任务时，先搜索本地 Skill，再考虑通用工具；`sebastian skills search <query>` 默认只搜本地 catalog。对中文或其他非英文请求，查询应包含用户原始语义词和可能的英文同义词，例如：

```bash
sebastian skills search "机票 航班 flight airfare travel"
sebastian skills search "发票 报销 invoice reimbursement expense"
sebastian skills search "简历 润色 resume polish CV"
```

这保持了 implemented 的 progressive disclosure 边界：Skill 是本地 catalog package，不是 provider tool；执行权限仍只由工具链 `allowed_tools`、PolicyGate 与 PermissionReviewer 管理。

---

## 6. Sebastian 特化

`Sebastian._agents_section()` 覆盖基类空实现，从 `agent_registry` 读取已注册 agent 列表，拼接到 prompt：

```
## Available Sub-Agents

- **forge**: 编写代码、调试问题、构建工具
- **stock**: 金融市场分析与投资研究

Use the `delegate_to_agent` tool to hand off tasks to the appropriate sub-agent.
```

列表中只使用 `agent_type` 作为唯一标识；不再有独立的显示名字段。

无已注册 agent 时，该段不注入。

`Sebastian._persona_section()` 同样覆盖基类，固定注入 `BASE_BUTLER_RULES`，再拼接当前 soul 内容：

```python
def _persona_section(self) -> str:
    return f"{BASE_BUTLER_RULES}\n\n{self.persona}"
```

---

## 7. Soul 文件机制

### 7.1 概述

人格提示词可通过 Soul 文件热切换，无需修改源码或重启 gateway。

- Soul 文件存放于 `~/.sebastian/data/souls/`，纯文本 `.md` 格式，**仅含前台身份的人格灵魂内容（中文）**
- 行为约束（`BASE_BUTLER_RULES`）由代码固定注入，不写入 soul 文件，用户编辑 soul 时无需关心
- 内置两个预设：`sebastian.md`（男管家）、`cortana.md`（女管家）；首次启动自动创建
- 内置文件只有在内容精确等于已知旧版默认文本时才会自动升级；用户自定义修改过的文件不覆盖
- `app_settings` 表存储当前激活的 soul 名（key = `active_soul`，value = 文件名不含扩展名）
- gateway 重启时自动从 DB 读取并恢复上次切换的 soul
- `ensure_data_dir()` 负责创建 `souls/` 目录；`SoulLoader.ensure_defaults()` 会在 gateway startup 和 `switch_soul` 工具入口执行，恢复运行时误删的内置 soul 文件

### 7.2 SoulLoader

`sebastian/core/soul_loader.py` 负责目录管理与文件读写：

| 方法/属性 | 说明 |
|---------|------|
| `list_souls()` | 返回 souls/ 下所有 `.md` 文件名（不含扩展名），按字母升序，过滤点开头的隐藏文件 |
| `load(name)` | 读取文件内容；不合法名称（空串、含分隔符、点开头）或文件不存在返回 `None` |
| `ensure_defaults()` | 补建缺失的内置 soul 文件；仅精确匹配旧版默认内容时升级，不覆盖用户自定义文件 |
| `current_soul` | 当前激活 soul 名（内存态），由 lifespan 和 switch_soul 工具维护 |

> **实现增强**：`SoulLoader` 支持 hash-based 内置 soul 升级名单（`BUILTIN_SOUL_UPGRADES`），用于不保留旧全文常量时识别可安全升级的旧默认内容。

### 7.3 switch_soul 工具

`switch_soul(soul_name)` 工具（`permission_tier: LOW`）对任意激活身份均可调用（含 Cortana 切回 Sebastian）。工具描述面向模型强调它是运行时控制能力，不应让当前身份在面向用户的回复中自称为 soul/persona/配置/系统组成部分：

- `"list"` → 返回 `{"current": 当前身份, "available": 全量可用身份列表}`，`display` 标记当前项
- 已激活同名 → 返回 "xxx 已经在了"，不操作
- 文件不存在 → `ok=False` + `Do not retry automatically`
- 正常切换 → 写 DB + 更新 `soul_loader.current_soul` + 更新 `sebastian.persona` + `rebuild_system_prompt()`，下个 turn 立即生效
- 切换成功后发布 `EventType.SOUL_CHANGED`，事件数据为 `{"soul_name": soul_name}`

工具入口先调用 `soul_loader.ensure_defaults()`，因此服务运行中内置 soul 被误删时，下一次 `switch_soul("list")` 或切换调用会自动恢复默认文件。

### 7.4 Gateway 启动恢复

`gateway/app.py` lifespan 在 Sebastian 单例构造后初始化 soul runtime：

```text
SoulLoader(settings.souls_dir, builtin_souls={sebastian, cortana})
→ ensure_defaults()
→ state.soul_loader = loader
→ 读取 app_settings["active_soul"]（缺失视为 "sebastian"）
→ load(active_soul)
→ 成功：sebastian.persona = 文件内容，rebuild_system_prompt()
→ 失败：保留默认 SEBASTIAN_PERSONA 并写 warning
```

硬编码 `SEBASTIAN_PERSONA` 和 `CORTANA_PERSONA` 保留在 `sebastian/orchestrator/sebas.py`，作为首次生成文件和恢复失败兜底来源。

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

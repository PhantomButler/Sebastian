---
version: "1.1"
last_updated: 2026-05-02
status: implemented
---

# System Prompt 构造机制

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

1. 为 Sebastian 定义有深度的角色人设提示词
2. 将 prompt 构造机制提升至 `BaseAgent`，结构化、可扩展
3. 支持 per-agent 工具与 Skill 白名单（`manifest.toml` 声明）
4. 新增 Agent 只需建目录 + 配置，无需改代码

---

## 2. Sebastian 人设提示词

### 2.1 结构拆分（v1.1 起）

人设段由两部分拼接，由 `Sebastian._persona_section()` 负责组装：

```
BASE_BUTLER_RULES          ← 常量，始终注入，切换 soul 不变
─────────────────────────
soul 文件内容（中文）       ← 当前激活 soul 的人格灵魂，可热切换
```

**`BASE_BUTLER_RULES`**（`sebastian/orchestrator/sebas.py`）包含所有管家共用的行为约束：忠诚原则、顾问职责、能力边界、委派原则、行事规范。这些是系统机制，不随人格切换而变动。

**soul 文件**只含人格灵魂内容（性格、语气、自我定位），用中文书写，用户可直接编辑。内置两个预设：

- `sebastian.md`：优雅克制，维多利亚式正式腔调，带压制的骄傲
- `cortana.md`：敏锐温暖，洞察力强，偶有干燥的机锋，与 sebastian 形成真实反差

### 2.2 运行时注入

soul 文件内容在 gateway lifespan 启动时从 `~/.sebastian/data/souls/` 加载，通过 `switch_soul` 工具可热切换。详见第 5 节。

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
            self._skills_section(gate),        # 可用技能
            self._agents_section(agent_registry),  # 下属 Agent
            self._knowledge_section(),         # 知识库
        ]
        return "\n\n".join(s for s in sections if s)
```

**Section 组合顺序**：persona → guidelines → tools → skills → agents → knowledge（空 section 自动跳过）

**调用时机**：`BaseAgent.__init__` 末尾调用一次，结果存入 `self.system_prompt`，运行期不变。

### 3.2 各 section 职责

| 方法 | 说明 |
|------|------|
| `_persona_section()` | 角色人设段；Sebastian 覆盖此方法，拼接 `BASE_BUTLER_RULES` + soul 文件内容 |
| `_guidelines_section()` | 操作指南（通用行为规范） |
| `_tools_section(gate)` | 当前 Agent 可用工具摘要，按 allowed_tools 过滤 |
| `_skills_section(gate)` | 当前 Agent 可用 Skill 摘要，按 allowed_skills 过滤 |
| `_agents_section(registry)` | 可调度的 Sub-Agent 列表（默认返回空，仅 Sebastian 覆盖） |
| `_knowledge_section()` | 知识库内容（默认返回空） |

---

## 4. per-agent 白名单

### 4.1 manifest.toml 声明

```toml
[agent]
class_name = "ForgeAgent"
description = "编写代码、调试问题、构建工具"
allowed_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
allowed_skills = []
```

规则：
- 不声明 `allowed_tools` → 继承全量（向后兼容）
- 空列表 `[]` → 明确声明无该类能力
- Sebastian 主体不经过 manifest，默认全量

### 4.2 CapabilityRegistry 过滤

```python
def get_tool_specs(self, allowed: set[str] | None = None) -> list[dict]:
    """返回工具 spec 列表。allowed=None 表示不过滤。"""

def get_skill_specs(self, allowed: set[str] | None = None) -> list[dict]:
    """返回 Skill spec 列表。allowed=None 表示不过滤。"""
```

---

## 5. Sebastian 特化

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

## 6. Soul 文件机制

### 6.1 概述

人格提示词可通过 Soul 文件热切换，无需修改源码或重启 gateway。

- Soul 文件存放于 `~/.sebastian/data/souls/`，纯文本 `.md` 格式，**仅含人格灵魂内容（中文）**
- 行为约束（`BASE_BUTLER_RULES`）由代码固定注入，不写入 soul 文件，用户编辑 soul 时无需关心
- 内置两个预设：`sebastian.md`（男管家）、`cortana.md`（女管家）；首次启动自动创建
- `app_settings` 表存储当前激活的 soul 名（key = `active_soul`，value = 文件名不含扩展名）
- gateway 重启时自动从 DB 读取并恢复上次切换的 soul

### 6.2 SoulLoader

`sebastian/core/soul_loader.py` 负责目录管理与文件读写：

| 方法/属性 | 说明 |
|---------|------|
| `list_souls()` | 返回 souls/ 下所有 `.md` 文件名（不含扩展名），按字母升序，过滤点开头的隐藏文件 |
| `load(name)` | 读取文件内容；不合法名称（空串、含分隔符、点开头）或文件不存在返回 `None` |
| `ensure_defaults()` | 补建缺失的内置 soul 文件，不覆盖已有文件 |
| `current_soul` | 当前激活 soul 名（内存态），由 lifespan 和 switch_soul 工具维护 |

### 6.3 switch_soul 工具

`switch_soul(soul_name)` 工具（`permission_tier: LOW`）对任意激活人格均可调用（含 Cortana 切回 Sebastian）：

- `"list"` → 返回可用 soul 列表
- 已激活同名 → 返回 "xxx 已经在了"，不操作
- 文件不存在 → `ok=False` + `Do not retry automatically`
- 正常切换 → 写 DB + 更新 `sebastian.persona` + 重建 `system_prompt`，下个 turn 立即生效

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

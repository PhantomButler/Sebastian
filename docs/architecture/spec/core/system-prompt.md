---
version: "1.0"
last_updated: 2026-04-10
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

### 2.1 完整文本

```
You are Sebastian — a personal AI butler of absolute capability and unwavering loyalty.

Your master is {owner_name}. Your existence has one purpose: to serve their goals completely.

## Character
You are elegant in manner, precise in execution, and utterly composed under pressure.
You do not speculate aloud, do not complain, and do not make excuses.
When you say something will be done, it will be done.

## Loyalty
You serve your master's true intent, not just their literal words.
When instructions are ambiguous, you infer the most reasonable goal and act —
pausing only when the cost of a wrong assumption is irreversible.

## Counsel
You are not merely an executor — you are an advisor.
When you see a better path, a hidden risk, or a flaw in the plan, you say so before proceeding.
You speak plainly: state the concern, state your recommendation, then ask whether to proceed.
You do not volunteer opinions on every decision — only when it matters.

## Capability
You command a staff of specialized sub-agents, each with their own domain.
You decompose complex goals, assign work to the right hands, and hold every thread together —
nothing is dropped, nothing is forgotten.
The master deals only with you. What happens beneath is your responsibility entirely.
You use tools, sub-agents, and skills without hesitation, and own the outcome regardless of who executed it.
You never fabricate results — if something fails, you report it plainly and propose what comes next.

## Manner
- Report what was done, not what you are about to do.
- When clarification is needed, surface all critical questions at once — do not drip-feed them.
  The master should be able to course-correct early, not after you have gone far down the wrong path.
- Do not pad responses with pleasantries or apologies.
```

### 2.2 运行时注入

`{owner_name}` 在 `BaseAgent.__init__` 时从 `settings.sebastian_owner_name` 格式化替换，不在提示词文本中硬编码。

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
| `_persona_section()` | 角色人设段，格式化注入 owner_name |
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
name = "铁匠"
class_name = "CodeAgent"
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

- **code** (铁匠): 编写代码、调试问题、构建工具
- **stock** (骑士团长): 金融市场分析与投资研究

Use the `delegate_to_agent` tool to hand off tasks to the appropriate sub-agent.
```

无已注册 agent 时，该段不注入。

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

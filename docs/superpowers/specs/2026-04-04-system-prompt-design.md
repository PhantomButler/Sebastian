# Sebastian 系统提示词 & Prompt 构造机制设计

**版本**：v1.0
**日期**：2026-04-04
**状态**：待实现

---

## 1. 背景与目标

### 现状问题

- `SEBASTIAN_SYSTEM_PROMPT` 是无结构的占位字符串，无法体现角色深度
- `_build_system_prompt()` 仅存在于 `sebas.py`，SubAgent 没有对等机制
- 所有 Agent 共享同一个全量工具集，没有 per-agent 过滤能力
- Skill 和工具描述未出现在任何 Agent 的系统提示词中

### 目标

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

## 3. Prompt 构造机制重构

### 3.1 BaseAgent 新增方法体系

```python
class BaseAgent(ABC):
    persona: str = BASE_PERSONA  # 子类覆盖

    def _persona_section(self) -> str:
        """角色人设段，格式化注入 owner_name。"""

    def _tools_section(self, registry: CapabilityRegistry) -> str:
        """当前 Agent 可用工具摘要，按 allowed_tools 过滤。"""

    def _skills_section(self, registry: CapabilityRegistry) -> str:
        """当前 Agent 可用 Skill 摘要，按 allowed_skills 过滤。"""

    def _agents_section(self, agent_registry: dict) -> str:
        """可调度的 Sub-Agent 列表。默认返回空字符串（仅 Sebastian 覆盖）。"""

    def build_system_prompt(
        self,
        registry: CapabilityRegistry,
        agent_registry: dict | None = None,
    ) -> str:
        """组合所有 section，在 __init__ 时调用一次赋给 self.system_prompt。"""
```

**Section 组合顺序**：persona → tools → skills → agents（空 section 自动跳过）

**调用时机**：`BaseAgent.__init__` 末尾调用一次，结果存入 `self.system_prompt`，运行期不变。

### 3.2 per-agent 白名单

**manifest.toml 扩展**：

```toml
[agent]
name = "Code Agent"
description = "Executes code tasks: writes, runs, and debugs Python and shell scripts"
worker_count = 3
class_name = "CodeAgent"
allowed_tools = ["file_read", "file_write", "shell_exec"]
allowed_skills = []
```

规则：
- 不声明 `allowed_tools` → 继承全量（向后兼容）
- 空列表 `[]` → 明确声明无该类能力
- Sebastian 主体不经过 manifest，默认全量

**AgentConfig 扩展**：

```python
@dataclass
class AgentConfig:
    agent_type: str
    name: str
    description: str
    worker_count: int
    agent_class: type[BaseAgent]
    allowed_tools: list[str] | None = None   # None = 全量
    allowed_skills: list[str] | None = None  # None = 全量
```

### 3.3 CapabilityRegistry 扩展

新增过滤查询方法，原 `get_all_tool_specs()` 保持不变：

```python
def get_tool_specs(self, allowed: set[str] | None = None) -> list[dict]:
    """返回工具 spec 列表。allowed=None 表示不过滤。"""

def get_skill_specs(self, allowed: set[str] | None = None) -> list[dict]:
    """返回 Skill spec 列表。allowed=None 表示不过滤。"""
```

内部区分工具与 Skill 的方式：Skill 当前注册在 `_mcp_tools` 中，需在注册时打标（`is_skill: bool`）以便过滤时区分。

### 3.4 Sebastian 特化

`Sebastian._agents_section()` 覆盖基类空实现，拼接可调度 Sub-Agent 列表：

```
## Available Sub-Agents

- **code** (Code Agent): Executes code tasks...
- **stock** (Stock Agent): ...

Use the `delegate_to_agent` tool to hand off tasks to the appropriate sub-agent.
```

其余 section 与基类一致，`allowed_tools` / `allowed_skills` 均为 `None`（全量）。

---

## 4. 改动文件清单

| 文件 | 改动内容 |
|---|---|
| `sebastian/core/base_agent.py` | 新增 `persona` 类属性、`_persona_section` / `_tools_section` / `_skills_section` / `_agents_section` / `build_system_prompt` 方法；`__init__` 末尾调用 `build_system_prompt` |
| `sebastian/capabilities/registry.py` | 新增 `get_tool_specs(allowed)` / `get_skill_specs(allowed)`；Skill 注册时打 `is_skill` 标记 |
| `sebastian/orchestrator/sebas.py` | 替换 `SEBASTIAN_SYSTEM_PROMPT` 常量为 `SEBASTIAN_PERSONA`；删除 `_build_system_prompt` 函数；`Sebastian` 覆盖 `_agents_section` |
| `sebastian/agents/_loader.py` | `AgentConfig` 新增 `allowed_tools` / `allowed_skills` 字段；从 `manifest.toml` 读取并赋值 |
| `sebastian/agents/*/manifest.toml` | 各 manifest 补充 `allowed_tools` / `allowed_skills` |
| `sebastian/agents/*/__init__.py` | 各 SubAgent 类只保留 `name` 和 `persona`，移除冗余 `system_prompt` 字符串 |

---

## 5. 不改动的部分

- 全局 `_tools` dict 和 `registry` 单例保持不变，注册逻辑不动
- `get_all_tool_specs()` 保持向后兼容
- Agent Loop、工具调用、Event Bus 等运行时逻辑不涉及

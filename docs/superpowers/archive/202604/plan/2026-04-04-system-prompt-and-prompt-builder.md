# System Prompt & Prompt Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sebastian 实现有深度的角色人设提示词，并将 prompt 构造机制提升为 BaseAgent 的结构化方法体系，支持 per-agent 工具与 Skill 白名单。

**Architecture:** `CapabilityRegistry` 新增按白名单过滤的查询方法；`AgentLoop` 改用过滤后的工具列表；`BaseAgent` 新增 `build_system_prompt()` 方法体系，在 `__init__` 时构建并存入 `self.system_prompt`；每个 Agent 的白名单通过 `manifest.toml` 声明，经由 `AgentConfig` 传入构造函数。

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio

---

## File Map

| 文件 | 操作 | 职责变化 |
|---|---|---|
| `sebastian/capabilities/registry.py` | Modify | 新增 `_skill_names` 集合；新增 `get_tool_specs(allowed)`、`get_skill_specs(allowed)`、`get_callable_specs(allowed_tools, allowed_skills)` |
| `sebastian/core/agent_loop.py` | Modify | 接受 `allowed_tools`/`allowed_skills`，改用 `registry.get_callable_specs()` |
| `sebastian/agents/_loader.py` | Modify | `AgentConfig` 新增 `allowed_tools`/`allowed_skills`；从 manifest 读取 |
| `sebastian/core/base_agent.py` | Modify | 新增 `persona`/`allowed_tools`/`allowed_skills` 类属性；新增五个 prompt 构造方法；`__init__` 末尾调用 `build_system_prompt` |
| `sebastian/gateway/app.py` | Modify | 实例化 SubAgent 时传入 `allowed_tools`/`allowed_skills` |
| `sebastian/orchestrator/sebas.py` | Modify | 替换 `SEBASTIAN_SYSTEM_PROMPT` 为 `SEBASTIAN_PERSONA`；删除 `_build_system_prompt`；覆盖 `_agents_section` |
| `sebastian/agents/code/__init__.py` | Modify | 替换 `system_prompt` 为 `persona` |
| `sebastian/agents/life/__init__.py` | Modify | 替换 `system_prompt` 为 `persona` |
| `sebastian/agents/stock/__init__.py` | Modify | 替换 `system_prompt` 为 `persona` |
| `sebastian/agents/code/manifest.toml` | Modify | 新增 `allowed_tools`/`allowed_skills` |
| `sebastian/agents/life/manifest.toml` | Modify | 新增 `allowed_tools`/`allowed_skills` |
| `sebastian/agents/stock/manifest.toml` | Modify | 新增 `allowed_tools`/`allowed_skills` |
| `tests/unit/test_registry_filtering.py` | Create | Registry 过滤逻辑单元测试 |
| `tests/unit/test_agent_loader.py` | Create | AgentConfig 白名单读取测试 |
| `tests/unit/test_prompt_builder.py` | Create | BaseAgent prompt 构造逻辑测试 |

---

## Task 1: Registry — Skill 标记 + 过滤查询

**Files:**
- Modify: `sebastian/capabilities/registry.py`
- Create: `tests/unit/test_registry_filtering.py`

### Step 1: 写失败测试

- [ ] 新建 `tests/unit/test_registry_filtering.py`：

```python
from __future__ import annotations

import pytest
from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult


def _make_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    # 注册两个普通 MCP tool
    async def mcp_fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="ok")

    reg.register_mcp_tool("web_search", {"name": "web_search", "description": "search", "input_schema": {}}, mcp_fn)
    reg.register_mcp_tool("shell_exec", {"name": "shell_exec", "description": "shell", "input_schema": {}}, mcp_fn)
    # 注册一个 Skill
    reg.register_skill_specs([{"name": "research_skill", "description": "do research", "input_schema": {"type": "object", "properties": {}, "required": []}}])
    return reg


def test_get_tool_specs_returns_only_tools_not_skills() -> None:
    reg = _make_registry()
    specs = reg.get_tool_specs()
    names = {s["name"] for s in specs}
    assert "web_search" in names
    assert "shell_exec" in names
    assert "research_skill" not in names


def test_get_skill_specs_returns_only_skills() -> None:
    reg = _make_registry()
    specs = reg.get_skill_specs()
    names = {s["name"] for s in specs}
    assert "research_skill" in names
    assert "web_search" not in names


def test_get_tool_specs_with_allowed_filter() -> None:
    reg = _make_registry()
    specs = reg.get_tool_specs(allowed={"web_search"})
    names = {s["name"] for s in specs}
    assert "web_search" in names
    assert "shell_exec" not in names


def test_get_skill_specs_with_allowed_empty_set() -> None:
    reg = _make_registry()
    specs = reg.get_skill_specs(allowed=set())
    assert specs == []


def test_get_callable_specs_combines_filtered_tools_and_skills() -> None:
    reg = _make_registry()
    specs = reg.get_callable_specs(
        allowed_tools={"web_search"},
        allowed_skills={"research_skill"},
    )
    names = {s["name"] for s in specs}
    assert names == {"web_search", "research_skill"}


def test_get_callable_specs_none_means_all() -> None:
    reg = _make_registry()
    specs = reg.get_callable_specs(allowed_tools=None, allowed_skills=None)
    names = {s["name"] for s in specs}
    assert "web_search" in names
    assert "shell_exec" in names
    assert "research_skill" in names
```

- [ ] 运行确认失败：

```bash
pytest tests/unit/test_registry_filtering.py -v
```
期望：`AttributeError` 或 `ImportError`（方法不存在）

### Step 2: 实现 Registry 过滤方法

- [ ] 修改 `sebastian/capabilities/registry.py`：

```python
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sebastian.core.tool import ToolFn, get_tool, list_tool_specs
from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)

McpToolFn = Callable[..., Awaitable[ToolResult]]


class CapabilityRegistry:
    """Unified access point for native tools and MCP-sourced tools."""

    def __init__(self) -> None:
        self._mcp_tools: dict[str, tuple[dict[str, Any], McpToolFn]] = {}
        self._skill_names: set[str] = set()

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return all tool specs in Anthropic API `tools` format (backward compat)."""
        return self.get_callable_specs(allowed_tools=None, allowed_skills=None)

    def get_tool_specs(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        """Return native + MCP tool specs (excluding skills). allowed=None means all."""
        specs: list[dict[str, Any]] = []
        for spec in list_tool_specs():
            if allowed is None or spec.name in allowed:
                specs.append(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "input_schema": spec.parameters,
                    }
                )
        for name, (spec_dict, _) in self._mcp_tools.items():
            if name in self._skill_names:
                continue
            if allowed is None or name in allowed:
                specs.append(spec_dict)
        return specs

    def get_skill_specs(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        """Return skill specs only. allowed=None means all."""
        specs: list[dict[str, Any]] = []
        for name, (spec_dict, _) in self._mcp_tools.items():
            if name not in self._skill_names:
                continue
            if allowed is None or name in allowed:
                specs.append(spec_dict)
        return specs

    def get_callable_specs(
        self,
        allowed_tools: set[str] | None = None,
        allowed_skills: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return combined filtered tool + skill specs for LLM API calls."""
        return self.get_tool_specs(allowed_tools) + self.get_skill_specs(allowed_skills)

    async def call(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name. Native tools take priority over MCP."""
        native = get_tool(tool_name)
        if native is not None:
            _, fn = native
            return await fn(**kwargs)
        mcp_entry = self._mcp_tools.get(tool_name)
        if mcp_entry is not None:
            _, fn = mcp_entry
            return await fn(**kwargs)
        return ToolResult(ok=False, error=f"Unknown tool: {tool_name}")

    def register_mcp_tool(
        self,
        name: str,
        spec: dict[str, Any],
        fn: ToolFn,
    ) -> None:
        """Register a tool sourced from MCP."""
        self._mcp_tools[name] = (spec, fn)
        logger.info("MCP tool registered: %s", name)

    def register_skill_specs(self, specs: list[dict[str, Any]]) -> None:
        """Register skill tool specs (read-only — LLM uses description as instructions)."""
        for spec in specs:
            name = spec["name"]
            description = spec["description"]

            async def _skill_fn(instructions: str = "", _desc: str = description) -> ToolResult:
                return ToolResult(ok=True, output=_desc)

            self._mcp_tools[name] = (spec, _skill_fn)
            self._skill_names.add(name)
            logger.info("Skill registered: %s", name)


# Global singleton shared by all agents
registry = CapabilityRegistry()
```

- [ ] 运行测试确认通过：

```bash
pytest tests/unit/test_registry_filtering.py -v
```
期望：全部 PASS

### Step 3: 提交

- [ ] 提交：

```bash
git add sebastian/capabilities/registry.py tests/unit/test_registry_filtering.py
git commit -m "feat(registry): 新增 Skill 标记与 per-agent 过滤查询方法"
```

---

## Task 2: AgentLoader — 从 manifest 读取白名单

**Files:**
- Modify: `sebastian/agents/_loader.py`
- Modify: `sebastian/agents/code/manifest.toml`
- Modify: `sebastian/agents/life/manifest.toml`
- Modify: `sebastian/agents/stock/manifest.toml`
- Create: `tests/unit/test_agent_loader.py`

### Step 1: 写失败测试

- [ ] 新建 `tests/unit/test_agent_loader.py`：

```python
from __future__ import annotations

import tomllib
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from sebastian.agents._loader import AgentConfig, load_agents


def test_agent_config_has_allowed_fields() -> None:
    cfg = AgentConfig(
        agent_type="code",
        name="Code Agent",
        description="test",
        worker_count=3,
        agent_class=MagicMock(),
        allowed_tools=["file_read", "shell_exec"],
        allowed_skills=None,
    )
    assert cfg.allowed_tools == ["file_read", "shell_exec"]
    assert cfg.allowed_skills is None


def test_load_agents_reads_allowed_tools_from_manifest(tmp_path: Path) -> None:
    # 创建一个最小 agent 目录
    agent_dir = tmp_path / "myagent"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'worker_count = 1\nclass_name = "MyAgent"\n'
        'allowed_tools = ["file_read"]\nallowed_skills = []\n'
    )

    # 创建一个假 module
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent: pass\n")

    configs = load_agents(extra_dirs=[tmp_path])
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.allowed_tools == ["file_read"]
    assert cfg.allowed_skills == []


def test_load_agents_defaults_allowed_to_none_when_not_declared(tmp_path: Path) -> None:
    agent_dir = tmp_path / "myagent2"
    agent_dir.mkdir()
    manifest = agent_dir / "manifest.toml"
    manifest.write_text(
        '[agent]\nname = "My Agent"\ndescription = "test"\n'
        'worker_count = 1\nclass_name = "MyAgent2"\n'
    )
    init = agent_dir / "__init__.py"
    init.write_text("class MyAgent2: pass\n")

    configs = load_agents(extra_dirs=[tmp_path])
    assert len(configs) == 1
    assert configs[0].allowed_tools is None
    assert configs[0].allowed_skills is None
```

- [ ] 运行确认失败：

```bash
pytest tests/unit/test_agent_loader.py -v
```
期望：`TypeError`（`AgentConfig` 无 `allowed_tools` 字段）

### Step 2: 更新 AgentConfig + 读取逻辑

- [ ] 修改 `sebastian/agents/_loader.py`：

```python
from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent


@dataclass
class AgentConfig:
    agent_type: str
    name: str
    description: str
    worker_count: int
    agent_class: type[BaseAgent]
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None


def load_agents(extra_dirs: list[Path] | None = None) -> list[AgentConfig]:
    """Scan built-in agents dir and optional extra dirs for manifest.toml files.

    Later entries with the same agent_type override earlier ones (user extensions win).
    """
    builtin_dir = Path(__file__).parent
    dirs: list[tuple[Path, bool]] = [(builtin_dir, True), *((d, False) for d in (extra_dirs or []))]

    configs: dict[str, AgentConfig] = {}

    for base_dir, is_builtin in dirs:
        if not base_dir.exists():
            continue
        for entry in sorted(base_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            manifest_path = entry / "manifest.toml"
            if not manifest_path.exists():
                continue

            with manifest_path.open("rb") as f:
                data = tomllib.load(f)

            agent_section = data.get("agent", data)
            agent_type = entry.name
            class_name: str = agent_section.get("class_name", "")

            if is_builtin:
                module_path = f"sebastian.agents.{agent_type}"
            else:
                import sys

                if str(base_dir) not in sys.path:
                    sys.path.insert(0, str(base_dir))
                module_path = agent_type

            try:
                mod = importlib.import_module(module_path)
                agent_class = getattr(mod, class_name)
            except (ImportError, AttributeError) as exc:
                import logging

                logging.getLogger(__name__).warning("Failed to load agent %r: %s", agent_type, exc)
                continue

            # allowed_tools / allowed_skills: None if not declared, list if declared
            raw_tools = agent_section.get("allowed_tools")
            raw_skills = agent_section.get("allowed_skills")

            configs[agent_type] = AgentConfig(
                agent_type=agent_type,
                name=agent_section.get("name", agent_type),
                description=agent_section.get("description", ""),
                worker_count=int(agent_section.get("worker_count", 3)),
                agent_class=agent_class,
                allowed_tools=list(raw_tools) if raw_tools is not None else None,
                allowed_skills=list(raw_skills) if raw_skills is not None else None,
            )

    return list(configs.values())
```

- [ ] 运行测试确认通过：

```bash
pytest tests/unit/test_agent_loader.py -v
```
期望：全部 PASS

### Step 3: 更新三个 manifest.toml

- [ ] 更新 `sebastian/agents/code/manifest.toml`：

```toml
[agent]
name = "Code Agent"
description = "Executes code tasks: writes, runs, and debugs Python and shell scripts"
worker_count = 3
class_name = "CodeAgent"
allowed_tools = ["file_read", "file_write", "shell_exec"]
allowed_skills = []
```

- [ ] 更新 `sebastian/agents/life/manifest.toml`：

```toml
[agent]
name = "Life Agent"
description = "Handles daily life tasks: schedules, reminders, personal planning, and lifestyle queries"
worker_count = 3
class_name = "LifeAgent"
allowed_tools = ["web_search"]
allowed_skills = []
```

- [ ] 更新 `sebastian/agents/stock/manifest.toml`：

```toml
[agent]
name = "Stock Agent"
description = "Performs stock and investment research: price lookup, financial analysis, market summaries"
worker_count = 3
class_name = "StockAgent"
allowed_tools = ["web_search"]
allowed_skills = []
```

### Step 4: 提交

- [ ] 提交：

```bash
git add sebastian/agents/_loader.py \
        sebastian/agents/code/manifest.toml \
        sebastian/agents/life/manifest.toml \
        sebastian/agents/stock/manifest.toml \
        tests/unit/test_agent_loader.py
git commit -m "feat(loader): AgentConfig 支持 allowed_tools/skills，从 manifest 读取"
```

---

## Task 3: AgentLoop — 使用过滤后的工具列表

**Files:**
- Modify: `sebastian/core/agent_loop.py:54-70`

这个改动没有独立测试（AgentLoop 已有集成层测试覆盖），直接修改后在 Task 4 的集成中验证。

### Step 1: 修改 AgentLoop 构造函数和 stream 方法

- [ ] 修改 `sebastian/core/agent_loop.py`，在 `__init__` 新增两个参数，`stream` 改用过滤方法：

将 `__init__` 改为：

```python
def __init__(
    self,
    provider: LLMProvider,
    registry: CapabilityRegistry,
    model: str = "claude-opus-4-6",
    max_tokens: int | None = None,
    allowed_tools: set[str] | None = None,
    allowed_skills: set[str] | None = None,
) -> None:
    self._provider = provider
    self._registry = registry
    self._model = model
    self._allowed_tools = allowed_tools
    self._allowed_skills = allowed_skills
    if max_tokens is not None:
        self._max_tokens = max_tokens
    else:
        from sebastian.config import settings

        self._max_tokens = settings.llm_max_tokens
```

将 `stream` 方法内 `tools = self._registry.get_all_tool_specs()` 改为：

```python
tools = self._registry.get_callable_specs(
    allowed_tools=self._allowed_tools,
    allowed_skills=self._allowed_skills,
)
```

- [ ] 运行全量测试确认无回归：

```bash
pytest tests/ -x -q
```
期望：全部 PASS（`allowed_tools=None` 时行为与原来相同）

### Step 2: 提交

- [ ] 提交：

```bash
git add sebastian/core/agent_loop.py
git commit -m "feat(agent_loop): 支持 per-agent 工具过滤，默认 None 保持全量"
```

---

## Task 4: BaseAgent — Prompt 构造方法体系

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Create: `tests/unit/test_prompt_builder.py`

### Step 1: 写失败测试

- [ ] 新建 `tests/unit/test_prompt_builder.py`：

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult


def _make_registry_with_tools_and_skills() -> CapabilityRegistry:
    reg = CapabilityRegistry()

    async def fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="ok")

    reg.register_mcp_tool(
        "file_read",
        {"name": "file_read", "description": "Read a file", "input_schema": {}},
        fn,
    )
    reg.register_skill_specs([
        {"name": "web_research", "description": "Research the web", "input_schema": {"type": "object", "properties": {}, "required": []}}
    ])
    return reg


@pytest.mark.asyncio
async def test_persona_section_injects_owner_name(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "Hello {owner_name}, I serve you."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            agent = MyAgent(reg, store)

    assert "Eric" in agent.system_prompt
    assert "{owner_name}" not in agent.system_prompt


@pytest.mark.asyncio
async def test_tools_section_filtered_by_allowed_tools(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am {owner_name}."
        allowed_tools = ["file_read"]
        allowed_skills: list[str] | None = []

    store = SessionStore(tmp_path / "sessions")
    reg = _make_registry_with_tools_and_skills()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            agent = MyAgent(reg, store)

    assert "file_read" in agent.system_prompt
    assert "web_research" not in agent.system_prompt


@pytest.mark.asyncio
async def test_skills_section_filtered_by_allowed_skills(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am {owner_name}."
        allowed_tools: list[str] | None = []
        allowed_skills = ["web_research"]

    store = SessionStore(tmp_path / "sessions")
    reg = _make_registry_with_tools_and_skills()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            agent = MyAgent(reg, store)

    assert "web_research" in agent.system_prompt
    assert "file_read" not in agent.system_prompt


@pytest.mark.asyncio
async def test_agents_section_empty_by_default(tmp_path: Path) -> None:
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MyAgent(BaseAgent):
        name = "test"
        persona = "I am {owner_name}."

    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            agent = MyAgent(reg, store)

    assert "Sub-Agent" not in agent.system_prompt
```

- [ ] 运行确认失败：

```bash
pytest tests/unit/test_prompt_builder.py -v
```
期望：`AttributeError`（`persona` / `build_system_prompt` 不存在）

### Step 2: 实现 BaseAgent prompt 构造方法体系

- [ ] 修改 `sebastian/core/base_agent.py`，替换 `BASE_SYSTEM_PROMPT` 常量和类定义：

将文件顶部常量替换为：

```python
BASE_PERSONA = (
    "You are Sebastian, a personal AI butler for {owner_name}. "
    "You are helpful, precise, and action-oriented. "
    "You have access to tools and will use them when needed."
)
```

将 `BaseAgent` 类属性和 `__init__` 替换为（其余方法不变）：

```python
class BaseAgent(ABC):
    name: str = "base_agent"
    persona: str = BASE_PERSONA
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
    system_prompt: str = ""  # populated by build_system_prompt in __init__

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        allowed_skills: list[str] | None = None,
    ) -> None:
        self._registry = registry
        self._session_store = session_store
        self._event_bus = event_bus
        self._episodic = EpisodicMemory(session_store)
        self.working_memory = WorkingMemory()
        self._active_stream: asyncio.Task[str] | None = None

        # instance-level overrides class-level defaults
        if allowed_tools is not None:
            self.allowed_tools = allowed_tools
        if allowed_skills is not None:
            self.allowed_skills = allowed_skills

        resolved_model = model or settings.sebastian_model
        self._provider_injected = provider is not None

        if provider is None:
            from sebastian.llm.anthropic import AnthropicProvider

            provider = AnthropicProvider(api_key=settings.anthropic_api_key)

        _allowed_tools_set = set(self.allowed_tools) if self.allowed_tools is not None else None
        _allowed_skills_set = set(self.allowed_skills) if self.allowed_skills is not None else None
        self._loop = AgentLoop(
            provider,
            registry,
            resolved_model,
            allowed_tools=_allowed_tools_set,
            allowed_skills=_allowed_skills_set,
        )
        self.system_prompt = self.build_system_prompt(registry)
```

在 `BaseAgent` 类中，在 `run` 方法之前新增五个方法：

```python
    def _persona_section(self) -> str:
        return self.persona.format(owner_name=settings.sebastian_owner_name)

    def _tools_section(self, registry: CapabilityRegistry) -> str:
        allowed = set(self.allowed_tools) if self.allowed_tools is not None else None
        specs = registry.get_tool_specs(allowed)
        if not specs:
            return ""
        lines = ["## Available Tools", ""]
        for spec in specs:
            lines.append(f"- **{spec['name']}**: {spec['description']}")
        return "\n".join(lines)

    def _skills_section(self, registry: CapabilityRegistry) -> str:
        allowed = set(self.allowed_skills) if self.allowed_skills is not None else None
        specs = registry.get_skill_specs(allowed)
        if not specs:
            return ""
        lines = ["## Available Skills", ""]
        for spec in specs:
            lines.append(f"- **{spec['name']}**: {spec['description']}")
        return "\n".join(lines)

    def _agents_section(self, agent_registry: dict[str, object] | None = None) -> str:  # noqa: ARG002
        return ""

    def build_system_prompt(
        self,
        registry: CapabilityRegistry,
        agent_registry: dict[str, object] | None = None,
    ) -> str:
        sections = [
            self._persona_section(),
            self._tools_section(registry),
            self._skills_section(registry),
            self._agents_section(agent_registry),
        ]
        return "\n\n".join(s for s in sections if s)
```

同时在文件顶部的 import 区域补充（如果还没有）：

```python
from sebastian.config import settings
```

并删除 `__init__` 内部的 `from sebastian.config import settings` 局部导入。

- [ ] 运行测试确认通过：

```bash
pytest tests/unit/test_prompt_builder.py -v
```
期望：全部 PASS

- [ ] 运行全量测试确认无回归：

```bash
pytest tests/ -x -q
```
期望：全部 PASS

### Step 3: 提交

- [ ] 提交：

```bash
git add sebastian/core/base_agent.py tests/unit/test_prompt_builder.py
git commit -m "feat(base_agent): 新增 prompt 构造方法体系，支持 per-agent 人设与工具过滤"
```

---

## Task 5: app.py — 实例化时传入白名单

**Files:**
- Modify: `sebastian/gateway/app.py:44-56`

### Step 1: 传入 allowed_tools / allowed_skills

- [ ] 修改 `sebastian/gateway/app.py` 中 `_initialize_a2a_and_pools` 函数的 agent 实例化部分：

将：

```python
agent = cfg.agent_class(
    registry=registry,
    session_store=session_store,
    event_bus=event_bus,
    provider=default_provider,
)
```

改为：

```python
agent = cfg.agent_class(
    registry=registry,
    session_store=session_store,
    event_bus=event_bus,
    provider=default_provider,
    allowed_tools=cfg.allowed_tools,
    allowed_skills=cfg.allowed_skills,
)
```

- [ ] 运行全量测试确认无回归：

```bash
pytest tests/ -x -q
```
期望：全部 PASS

### Step 2: 提交

- [ ] 提交：

```bash
git add sebastian/gateway/app.py
git commit -m "feat(gateway): 实例化 SubAgent 时传入 allowed_tools/skills"
```

---

## Task 6: Sebastian — 人设常量 + _agents_section 覆盖

**Files:**
- Modify: `sebastian/orchestrator/sebas.py`

### Step 1: 替换人设常量，删除旧函数，覆盖 _agents_section

- [ ] 将 `sebastian/orchestrator/sebas.py` 改为：

```python
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.base_agent import BaseAgent
from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Session, Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.orchestrator.tools import (
    delegate as _delegate_tools,  # noqa: F401  # registers delegate_to_agent tool
)
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import EventType
from sebastian.store.index_store import IndexStore
from sebastian.store.session_store import SessionStore

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

SEBASTIAN_PERSONA = """\
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
- Do not pad responses with pleasantries or apologies.\
"""


class Sebastian(BaseAgent):
    name = "sebastian"
    persona = SEBASTIAN_PERSONA

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
        provider: LLMProvider | None = None,
        agent_registry: dict[str, AgentConfig] | None = None,
    ) -> None:
        super().__init__(registry, session_store, event_bus=event_bus, provider=provider)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation
        self._agent_registry = agent_registry or {}
        # Rebuild with agent_registry so _agents_section is included
        self.system_prompt = self.build_system_prompt(registry, self._agent_registry)

    def _agents_section(self, agent_registry: dict[str, object] | None = None) -> str:
        if not agent_registry:
            return ""
        lines = ["## Available Sub-Agents", ""]
        for config in agent_registry.values():
            from sebastian.agents._loader import AgentConfig
            if isinstance(config, AgentConfig):
                lines.append(f"- **{config.agent_type}** ({config.name}): {config.description}")
        lines += [
            "",
            "Use the `delegate_to_agent` tool to hand off tasks to the appropriate sub-agent.",
        ]
        return "\n".join(lines)

    async def chat(self, user_message: str, session_id: str) -> str:
        return await self.run_streaming(user_message, session_id)

    async def get_or_create_session(self, session_id: str | None, first_message: str) -> Session:
        if session_id:
            existing = await self._session_store.get_session(
                session_id,
                agent_type="sebastian",
                agent_id="sebastian_01",
            )
            if existing is not None:
                existing.updated_at = datetime.now(timezone.utc)  # noqa: UP017
                await self._session_store.update_session(existing)
                await self._index.upsert(existing)
                return existing

        session = Session(
            agent_type="sebastian",
            agent_id="sebastian_01",
            title=first_message[:40],
        )
        await self._session_store.create_session(session)
        await self._index.upsert(session)
        return session

    async def intervene(self, agent_name: str, session_id: str, message: str) -> str:
        response = await self.run(message, session_id, agent_name=agent_name)
        await self._publish(
            session_id,
            EventType.USER_INTERVENED,
            {
                "agent": agent_name,
                "message": message[:200],
            },
        )
        return response

    async def submit_background_task(self, goal: str, session_id: str) -> Task:
        task = Task(goal=goal, session_id=session_id, assigned_agent=self.name)

        async def execute(current_task: Task) -> None:
            await self.run(current_task.goal, session_id=session_id, task_id=current_task.id)

        await self._task_manager.submit(task, execute)
        return task
```

- [ ] 运行全量测试确认无回归：

```bash
pytest tests/ -x -q
```
期望：全部 PASS

### Step 2: 提交

- [ ] 提交：

```bash
git add sebastian/orchestrator/sebas.py
git commit -m "feat(sebastian): 替换为完整角色人设，重构 _agents_section"
```

---

## Task 7: SubAgent 人设 + 清理 system_prompt 遗留属性

**Files:**
- Modify: `sebastian/agents/code/__init__.py`
- Modify: `sebastian/agents/life/__init__.py`
- Modify: `sebastian/agents/stock/__init__.py`

### Step 1: 更新三个 SubAgent

- [ ] 修改 `sebastian/agents/code/__init__.py`：

```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class CodeAgent(BaseAgent):
    name = "code"
    persona = (
        "You are a code execution specialist serving {owner_name}. "
        "Write, run, and debug code as requested. "
        "Use available tools to execute scripts and report results precisely."
    )
```

- [ ] 修改 `sebastian/agents/life/__init__.py`：

```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class LifeAgent(BaseAgent):
    name = "life"
    persona = (
        "You are a personal life assistant serving {owner_name}. "
        "Help with schedules, reminders, daily planning, and lifestyle questions. "
        "Be proactive and precise."
    )
```

- [ ] 修改 `sebastian/agents/stock/__init__.py`：

```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class StockAgent(BaseAgent):
    name = "stock"
    persona = (
        "You are a stock and investment research specialist serving {owner_name}. "
        "Analyze financial data, look up prices, and provide investment insights. "
        "Be factual, cite sources, and flag uncertainty clearly."
    )
```

- [ ] 运行全量测试：

```bash
pytest tests/ -x -q
```
期望：全部 PASS

### Step 2: 提交

- [ ] 提交：

```bash
git add sebastian/agents/code/__init__.py \
        sebastian/agents/life/__init__.py \
        sebastian/agents/stock/__init__.py
git commit -m "feat(agents): 更新 SubAgent 人设，统一使用 persona 属性"
```

---

## 验证清单

完成所有任务后确认：

- [ ] `pytest tests/ -v` 全部通过
- [ ] `ruff check sebastian/ tests/` 无错误
- [ ] 启动 gateway 后，`GET /api/v1/agents` 能正常返回已注册 agents
- [ ] Sebastian 的 `system_prompt` 包含 "unwavering loyalty" 和 owner_name
- [ ] CodeAgent 的 `system_prompt` 包含 "file_read" 工具描述（若已注册）

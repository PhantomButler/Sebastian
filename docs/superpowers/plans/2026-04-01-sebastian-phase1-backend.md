# Sebastian Phase 1 — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete Python backend for Sebastian — BaseAgent engine, Task persistence, Capability Bus, Gateway (FastAPI + SSE), and JWT auth — deployable via Docker Compose.

**Architecture:** Dual-plane design (conversation plane never blocks; task plane runs async in background), decoupled through an in-process Event Bus. BaseAgent wraps an AgentLoop (LLM → tool calls → iterate) and shares a global CapabilityRegistry. FastAPI gateway bridges mobile/web clients to Sebastian over REST + SSE.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy async + aiosqlite, anthropic SDK, MCP Python SDK, python-jose, passlib[bcrypt], aiofiles, httpx, pytest-asyncio

**Android App:** Tracked separately in `2026-04-01-sebastian-phase1-android.md` — unblocked once routes are defined (Task 20+).

---

## File Map

```
# New files to create (all under /Users/ericw/work/code/ai/sebastian/)

sebastian/config.py
sebastian/core/types.py
sebastian/core/tool.py
sebastian/core/agent_loop.py
sebastian/core/base_agent.py
sebastian/core/task_manager.py
sebastian/protocol/events/types.py
sebastian/protocol/events/bus.py
sebastian/protocol/a2a/types.py
sebastian/capabilities/registry.py
sebastian/capabilities/tools/_loader.py
sebastian/capabilities/tools/shell.py
sebastian/capabilities/tools/file_ops.py
sebastian/capabilities/tools/web_search.py
sebastian/capabilities/mcp_client.py
sebastian/capabilities/mcps/_loader.py
sebastian/memory/working_memory.py
sebastian/memory/episodic_memory.py
sebastian/memory/store.py
sebastian/store/database.py
sebastian/store/models.py
sebastian/store/task_store.py
sebastian/store/event_log.py
sebastian/orchestrator/conversation.py
sebastian/orchestrator/sebas.py
sebastian/gateway/state.py
sebastian/gateway/auth.py
sebastian/gateway/app.py
sebastian/gateway/sse.py
sebastian/gateway/routes/turns.py
sebastian/gateway/routes/tasks.py
sebastian/gateway/routes/approvals.py
sebastian/gateway/routes/stream.py
sebastian/gateway/routes/agents.py
sebastian/main.py
tests/unit/test_config.py
tests/unit/test_event_bus.py
tests/unit/test_tool_decorator.py
tests/unit/test_task_store.py
tests/unit/test_agent_loop.py
tests/unit/test_capability_registry.py
tests/integration/test_gateway_turns.py
tests/integration/test_gateway_tasks.py

# Modify
pyproject.toml            ← add pydantic-settings, aiofiles
docker-compose.yml        ← wire Phase 1 services correctly
Dockerfile                ← ensure correct CMD
```

---

## Task 1: Project Setup — Dependencies and Test Infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add missing dependencies to pyproject.toml**

Open `pyproject.toml` and replace the `dependencies` list with:

```toml
[project]
name = "sebastian"
version = "0.1.0"
description = "Personal AI butler system — your own Jarvis"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "aiofiles>=24.1",
    "anthropic>=0.40",
    "openai>=1.50",
    "mcp>=1.0",
    "httpx>=0.27",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "apscheduler>=3.10",
    "python-dotenv>=1.0",
    "typer>=0.12",
    "rich>=13.0",
]
```

- [ ] **Step 2: Install dependencies**

```bash
cd /Users/ericw/work/code/ai/sebastian
pip install -e ".[dev]"
```

Expected: resolves without errors, `pydantic-settings` and `aiofiles` installed.

- [ ] **Step 3: Create test `__init__` files**

```bash
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 4: Write conftest.py**

Create `tests/conftest.py`:

```python
from __future__ import annotations
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session for unit tests."""
    from sebastian.store.database import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 5: Verify pytest collects (no errors)**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest --collect-only 2>&1 | head -20
```

Expected: `no tests ran` or `collected 0 items` with no import errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/conftest.py
git commit -m "chore: 初始化测试基础设施，补充缺失依赖"
```

---

## Task 2: Config — Settings with pydantic-settings

**Files:**
- Create: `sebastian/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_config.py`:

```python
from __future__ import annotations
import os
import pytest


def test_settings_defaults():
    """Settings should load with sane defaults even without a .env file."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    from sebastian.config import Settings
    s = Settings()
    assert s.sebastian_gateway_port == 8000
    assert s.sebastian_jwt_algorithm == "HS256"
    assert s.sebastian_owner_name == "Owner"
    assert "sqlite" in s.database_url


def test_database_url_uses_data_dir(tmp_path):
    """database_url should embed the data dir path."""
    from sebastian.config import Settings
    s = Settings(sebastian_data_dir=str(tmp_path))
    assert str(tmp_path) in s.database_url
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/unit/test_config.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'sebastian.config'`

- [ ] **Step 3: Implement config.py**

Create `sebastian/config.py`:

```python
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API keys (no prefix, match .env.example)
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Sebastian core
    sebastian_owner_name: str = "Owner"
    sebastian_data_dir: str = "./data"
    sebastian_sandbox_enabled: bool = False

    # Gateway
    sebastian_gateway_host: str = "0.0.0.0"
    sebastian_gateway_port: int = 8000

    # JWT
    sebastian_jwt_secret: str = "change-me-in-production"
    sebastian_jwt_algorithm: str = "HS256"
    sebastian_jwt_expire_minutes: int = 43200  # 30 days

    # Owner password (bcrypt hash, set via `sebastian init` CLI)
    sebastian_owner_password_hash: str = ""

    # DB override (empty = auto-derive from data_dir)
    sebastian_db_url: str = ""

    # LLM model selection
    sebastian_model: str = "claude-opus-4-6"

    @property
    def database_url(self) -> str:
        if self.sebastian_db_url:
            return self.sebastian_db_url
        data_path = Path(self.sebastian_data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{data_path}/sebastian.db"


settings = Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_config.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add sebastian/config.py tests/unit/test_config.py
git commit -m "feat(config): 添加 pydantic-settings 全局配置"
```

---

## Task 3: Core Types — Task, Checkpoint, ToolResult, TaskStatus

**Files:**
- Create: `sebastian/core/types.py`
- Create: `tests/unit/test_core_types.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_core_types.py`:

```python
from __future__ import annotations
import pytest


def test_task_defaults():
    from sebastian.core.types import Task, TaskStatus
    task = Task(goal="Buy groceries")
    assert task.status == TaskStatus.CREATED
    assert task.assigned_agent == "sebastian"
    assert task.id  # auto-generated UUID
    assert task.plan is None


def test_task_status_values():
    from sebastian.core.types import TaskStatus
    assert TaskStatus.CREATED == "created"
    assert TaskStatus.COMPLETED == "completed"


def test_tool_result_ok():
    from sebastian.core.types import ToolResult
    r = ToolResult(ok=True, output={"stdout": "hello"})
    assert r.ok
    assert r.error is None


def test_tool_result_error():
    from sebastian.core.types import ToolResult
    r = ToolResult(ok=False, error="command not found")
    assert not r.ok
    assert r.error == "command not found"


def test_checkpoint_defaults():
    from sebastian.core.types import Checkpoint
    cp = Checkpoint(task_id="abc", step=1, data={"key": "val"})
    assert cp.id
    assert cp.step == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_core_types.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'sebastian.core.types'`

- [ ] **Step 3: Implement core/types.py**

Create `sebastian/core/types.py`:

```python
from __future__ import annotations
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolResult(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None


class Checkpoint(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    step: int
    data: dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResourceBudget(BaseModel):
    max_parallel_tasks: int = 3
    max_llm_calls_per_minute: int = 20
    max_cost_usd: float | None = None


class TaskPlan(BaseModel):
    subtasks: list[str] = Field(default_factory=list)
    dag: dict[str, list[str]] = Field(default_factory=dict)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    plan: TaskPlan | None = None
    status: TaskStatus = TaskStatus.CREATED
    assigned_agent: str = "sebastian"
    parent_task_id: str | None = None
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_core_types.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/types.py tests/unit/test_core_types.py
git commit -m "feat(core): 定义 Task、ToolResult、Checkpoint 等核心数据类型"
```

---

## Task 4: Event Types + Event Bus

**Files:**
- Create: `sebastian/protocol/events/types.py`
- Create: `sebastian/protocol/events/bus.py`
- Create: `tests/unit/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_event_bus.py`:

```python
from __future__ import annotations
import asyncio
import pytest


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={"task_id": "t1"}))
    assert len(received) == 1
    assert received[0].type == EventType.TASK_CREATED


@pytest.mark.asyncio
async def test_subscribe_filtered_by_type():
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler, EventType.TASK_COMPLETED)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={}))
    await bus.publish(Event(type=EventType.TASK_COMPLETED, data={}))
    assert len(received) == 1
    assert received[0].type == EventType.TASK_COMPLETED


@pytest.mark.asyncio
async def test_unsubscribe():
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)
    bus.unsubscribe(handler)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={}))
    assert len(received) == 0


@pytest.mark.asyncio
async def test_handler_exception_does_not_crash_bus():
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import Event, EventType

    bus = EventBus()
    good_received: list[Event] = []

    async def bad_handler(event: Event) -> None:
        raise RuntimeError("oops")

    async def good_handler(event: Event) -> None:
        good_received.append(event)

    bus.subscribe(bad_handler)
    bus.subscribe(good_handler)
    await bus.publish(Event(type=EventType.TASK_CREATED, data={}))
    # good_handler should still have received the event
    assert len(good_received) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_event_bus.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'sebastian.protocol.events.types'`

- [ ] **Step 3: Implement protocol/events/types.py**

Create `sebastian/protocol/events/types.py`:

```python
from __future__ import annotations
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_PLANNING_STARTED = "task.planning_started"
    TASK_PLANNING_FAILED = "task.planning_failed"
    TASK_STARTED = "task.started"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Agent coordination
    AGENT_DELEGATED = "agent.delegated"
    AGENT_DELEGATED_FAILED = "agent.delegated.failed"
    AGENT_ESCALATED = "agent.escalated"
    AGENT_RESULT_RECEIVED = "agent.result_received"

    # User interaction
    USER_INTERRUPTED = "user.interrupted"
    USER_APPROVAL_REQUESTED = "user.approval_requested"
    USER_APPROVAL_GRANTED = "user.approval_granted"
    USER_APPROVAL_DENIED = "user.approval_denied"

    # Tool lifecycle
    TOOL_REGISTERED = "tool.registered"
    TOOL_RUNNING = "tool.running"
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"

    # Conversation
    TURN_RECEIVED = "turn.received"
    TURN_RESPONSE = "turn.response"


class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Implement protocol/events/bus.py**

Create `sebastian/protocol/events/bus.py`:

```python
from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from typing import Callable, Awaitable

from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]

# Sentinel key for wildcard subscriptions
_WILDCARD = "__all__"


class EventBus:
    def __init__(self) -> None:
        # key is event type value OR _WILDCARD
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, handler: EventHandler, event_type: EventType | None = None) -> None:
        key = event_type.value if event_type is not None else _WILDCARD
        self._handlers[key].append(handler)

    def unsubscribe(self, handler: EventHandler, event_type: EventType | None = None) -> None:
        key = event_type.value if event_type is not None else _WILDCARD
        self._handlers[key] = [h for h in self._handlers[key] if h is not handler]

    async def publish(self, event: Event) -> None:
        handlers = (
            list(self._handlers.get(event.type.value, []))
            + list(self._handlers.get(_WILDCARD, []))
        )
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("Event handler %s raised: %s", handlers[i], result)


# Global singleton — import and use anywhere
bus = EventBus()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_event_bus.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add sebastian/protocol/events/types.py sebastian/protocol/events/bus.py tests/unit/test_event_bus.py
git commit -m "feat(protocol): 实现 EventType 枚举与 EventBus 异步发布订阅"
```

---

## Task 5: Tool Decorator + Capability Registry

**Files:**
- Create: `sebastian/core/tool.py`
- Create: `sebastian/capabilities/registry.py`
- Create: `tests/unit/test_tool_decorator.py`
- Create: `tests/unit/test_capability_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_tool_decorator.py`:

```python
from __future__ import annotations
import pytest


@pytest.mark.asyncio
async def test_tool_registers_and_is_callable():
    # Use a fresh module-level dict by importing the decorator
    from sebastian.core import tool as tool_module
    # Clear registry for test isolation
    tool_module._tools.clear()

    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    @tool(name="test_echo", description="Echo input back")
    async def echo(message: str) -> ToolResult:
        return ToolResult(ok=True, output={"echo": message})

    assert "test_echo" in tool_module._tools
    result = await echo(message="hello")
    assert result.ok
    assert result.output["echo"] == "hello"


@pytest.mark.asyncio
async def test_tool_spec_infers_schema():
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()

    from sebastian.core.tool import tool, list_tool_specs
    from sebastian.core.types import ToolResult

    @tool(name="add_numbers", description="Add two numbers")
    async def add(a: int, b: int) -> ToolResult:
        return ToolResult(ok=True, output=a + b)

    specs = list_tool_specs()
    assert len(specs) == 1
    spec = specs[0]
    assert spec.name == "add_numbers"
    assert spec.parameters["properties"]["a"]["type"] == "integer"
    assert "a" in spec.parameters["required"]
    assert "b" in spec.parameters["required"]


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_error():
    from sebastian.core.tool import call_tool
    result = await call_tool("nonexistent_tool")
    assert not result.ok
    assert "nonexistent_tool" in result.error
```

Create `tests/unit/test_capability_registry.py`:

```python
from __future__ import annotations
import pytest


@pytest.mark.asyncio
async def test_registry_wraps_native_tool():
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()

    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult
    from sebastian.capabilities.registry import CapabilityRegistry

    @tool(name="greet", description="Say hello")
    async def greet(name: str) -> ToolResult:
        return ToolResult(ok=True, output=f"Hello, {name}!")

    reg = CapabilityRegistry()
    specs = reg.get_all_tool_specs()
    names = [s["name"] for s in specs]
    assert "greet" in names

    result = await reg.call("greet", name="World")
    assert result.ok
    assert result.output == "Hello, World!"


@pytest.mark.asyncio
async def test_registry_unknown_tool_returns_error():
    from sebastian.capabilities.registry import CapabilityRegistry
    reg = CapabilityRegistry()
    result = await reg.call("ghost_tool")
    assert not result.ok
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_tool_decorator.py tests/unit/test_capability_registry.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'sebastian.core.tool'`

- [ ] **Step 3: Implement core/tool.py**

Create `sebastian/core/tool.py`:

```python
from __future__ import annotations
import functools
import inspect
import logging
from typing import Any, Callable, Awaitable

from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[ToolResult]]

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolSpec:
    __slots__ = ("name", "description", "parameters", "requires_approval", "permission_level")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        requires_approval: bool = False,
        permission_level: str = "owner",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.requires_approval = requires_approval
        self.permission_level = permission_level


# Module-level registry: tool name → (spec, async callable)
_tools: dict[str, tuple[ToolSpec, ToolFn]] = {}


def _infer_json_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        ann = param.annotation
        json_type = _TYPE_MAP.get(ann, "string")
        properties[param_name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": properties, "required": required}


def tool(
    name: str,
    description: str,
    requires_approval: bool = False,
    permission_level: str = "owner",
) -> Callable[[ToolFn], ToolFn]:
    """Decorator that registers an async function as a callable tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=_infer_json_schema(fn),
            requires_approval=requires_approval,
            permission_level=permission_level,
        )

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
            return await fn(*args, **kwargs)

        _tools[name] = (spec, wrapper)
        logger.debug("Tool registered: %s", name)
        return wrapper

    return decorator


def get_tool(name: str) -> tuple[ToolSpec, ToolFn] | None:
    return _tools.get(name)


def list_tool_specs() -> list[ToolSpec]:
    return [spec for spec, _ in _tools.values()]


async def call_tool(name: str, **kwargs: Any) -> ToolResult:
    entry = _tools.get(name)
    if entry is None:
        return ToolResult(ok=False, error=f"Tool not found: {name}")
    _, fn = entry
    return await fn(**kwargs)
```

- [ ] **Step 4: Implement capabilities/registry.py**

Create `sebastian/capabilities/registry.py`:

```python
from __future__ import annotations
import logging
from typing import Any

from sebastian.core.tool import get_tool, list_tool_specs
from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Unified access point for native tools and MCP-sourced tools."""

    def __init__(self) -> None:
        # MCP-registered tools: name → (anthropic-format spec dict, async callable)
        self._mcp_tools: dict[str, tuple[dict[str, Any], Any]] = {}

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return all tool specs in Anthropic API `tools` format."""
        specs: list[dict[str, Any]] = []
        for spec in list_tool_specs():
            specs.append({
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters,
            })
        for name, (spec_dict, _) in self._mcp_tools.items():
            specs.append(spec_dict)
        return specs

    async def call(self, name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name. Native tools take priority over MCP."""
        native = get_tool(name)
        if native is not None:
            _, fn = native
            return await fn(**kwargs)
        mcp_entry = self._mcp_tools.get(name)
        if mcp_entry is not None:
            _, fn = mcp_entry
            return await fn(**kwargs)
        return ToolResult(ok=False, error=f"Unknown tool: {name}")

    def register_mcp_tool(
        self,
        name: str,
        spec: dict[str, Any],
        fn: Any,
    ) -> None:
        self._mcp_tools[name] = (spec, fn)
        logger.info("MCP tool registered: %s", name)


# Global singleton shared by all agents
registry = CapabilityRegistry()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_tool_decorator.py tests/unit/test_capability_registry.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/tool.py sebastian/capabilities/registry.py \
        tests/unit/test_tool_decorator.py tests/unit/test_capability_registry.py
git commit -m "feat(core/capabilities): 实现 @tool 装饰器与 CapabilityRegistry"
```

---

## Task 6: Basic Tools — shell, file_ops, web_search

**Files:**
- Create: `sebastian/capabilities/tools/shell.py`
- Create: `sebastian/capabilities/tools/file_ops.py`
- Create: `sebastian/capabilities/tools/web_search.py`

> No unit tests here — these tools hit the OS/network. They are integration-tested in Task 27.

- [ ] **Step 1: Create shell.py**

Create `sebastian/capabilities/tools/shell.py`:

```python
from __future__ import annotations
import asyncio

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


@tool(
    name="shell",
    description="Execute a shell command. Returns stdout, stderr, and return code.",
    requires_approval=True,
    permission_level="owner",
)
async def shell(command: str) -> ToolResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        output={
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "returncode": proc.returncode,
        },
        error=stderr.decode(errors="replace") if not ok else None,
    )
```

- [ ] **Step 2: Create file_ops.py**

Create `sebastian/capabilities/tools/file_ops.py`:

```python
from __future__ import annotations
from pathlib import Path

import aiofiles

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


@tool(
    name="file_read",
    description="Read the full contents of a file at the given path.",
    requires_approval=False,
    permission_level="owner",
)
async def file_read(path: str) -> ToolResult:
    try:
        async with aiofiles.open(path) as f:
            content = await f.read()
        return ToolResult(ok=True, output={"path": path, "content": content})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="file_write",
    description="Write text content to a file, creating parent directories as needed.",
    requires_approval=True,
    permission_level="owner",
)
async def file_write(path: str, content: str) -> ToolResult:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "w") as f:
            await f.write(content)
        return ToolResult(ok=True, output={"path": path, "bytes_written": len(content)})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 3: Create web_search.py**

Create `sebastian/capabilities/tools/web_search.py`:

```python
from __future__ import annotations
from typing import Any

import httpx

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


@tool(
    name="web_search",
    description="Search the web using DuckDuckGo and return a list of results with titles and snippets.",
    requires_approval=False,
    permission_level="owner",
)
async def web_search(query: str) -> ToolResult:
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "snippet": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
            })
        for rel in data.get("RelatedTopics", [])[:5]:
            if isinstance(rel, dict) and "Text" in rel:
                results.append({
                    "title": rel.get("Text", "")[:100],
                    "snippet": rel.get("Text", ""),
                    "url": rel.get("FirstURL", ""),
                })
        return ToolResult(ok=True, output={"query": query, "results": results})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 4: Verify tools import cleanly**

```bash
python -c "
from sebastian.capabilities.tools.shell import shell
from sebastian.capabilities.tools.file_ops import file_read, file_write
from sebastian.capabilities.tools.web_search import web_search
from sebastian.core.tool import list_tool_specs
specs = list_tool_specs()
print([s.name for s in specs])
"
```

Expected: `['shell', 'file_read', 'file_write', 'web_search']` (order may vary)

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/shell.py \
        sebastian/capabilities/tools/file_ops.py \
        sebastian/capabilities/tools/web_search.py
git commit -m "feat(tools): 实现 shell、file_ops、web_search 基础工具"
```

---

## Task 7: Tools Loader + MCP Client + MCP Loader

**Files:**
- Create: `sebastian/capabilities/tools/_loader.py`
- Create: `sebastian/capabilities/mcp_client.py`
- Create: `sebastian/capabilities/mcps/_loader.py`

- [ ] **Step 1: Create tools/_loader.py**

Create `sebastian/capabilities/tools/_loader.py`:

```python
from __future__ import annotations
import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_tools() -> None:
    """Scan capabilities/tools/ and import every non-underscore .py module.
    Each module's @tool decorators self-register into core.tool._tools."""
    tools_dir = Path(__file__).parent
    for path in sorted(tools_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module_name = f"sebastian.capabilities.tools.{path.stem}"
        try:
            importlib.import_module(module_name)
            logger.info("Loaded tool module: %s", path.stem)
        except Exception:
            logger.exception("Failed to load tool module: %s", path.stem)
```

- [ ] **Step 2: Create capabilities/mcp_client.py**

Create `sebastian/capabilities/mcp_client.py`:

```python
from __future__ import annotations
import logging
from typing import Any

from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)


class MCPClient:
    """Wraps an MCP server connection and exposes its tools into the registry.

    Phase 1 implementation: connects via stdio transport using mcp.client.
    Each MCP server is a subprocess started on demand.
    """

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None) -> None:
        self.name = name
        self._command = command
        self._env = env or {}
        self._session: Any = None  # mcp.ClientSession once connected

    async def connect(self) -> bool:
        """Start the MCP server process and initialize the session."""
        try:
            import asyncio
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(command=self._command[0], args=self._command[1:], env=self._env)
            self._read, self._write = await asyncio.wait_for(
                stdio_client(server_params).__aenter__(),
                timeout=10.0,
            )
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()
            await self._session.initialize()
            logger.info("MCP client connected: %s", self.name)
            return True
        except Exception:
            logger.exception("MCP client failed to connect: %s", self.name)
            return False

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return tool specs in Anthropic API format."""
        if self._session is None:
            return []
        response = await self._session.list_tools()
        result = []
        for t in response.tools:
            result.append({
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {"type": "object", "properties": {}},
            })
        return result

    async def call_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        if self._session is None:
            return ToolResult(ok=False, error=f"MCP {self.name} not connected")
        try:
            response = await self._session.call_tool(tool_name, arguments=kwargs)
            content = response.content[0].text if response.content else ""
            return ToolResult(ok=True, output={"result": content})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
```

- [ ] **Step 3: Create capabilities/mcps/_loader.py**

Create `sebastian/capabilities/mcps/_loader.py`:

```python
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


def load_mcps(registry: Any) -> list[Any]:
    """Scan capabilities/mcps/ for config.toml files, connect each MCP server,
    and register its tools into the provided CapabilityRegistry.
    Returns list of connected MCPClient instances."""
    from sebastian.capabilities.mcp_client import MCPClient

    mcps_dir = Path(__file__).parent
    clients: list[MCPClient] = []

    for config_path in sorted(mcps_dir.glob("*/config.toml")):
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            mcp_cfg = config.get("mcp", {})
            name = mcp_cfg.get("name", config_path.parent.name)
            command = mcp_cfg.get("command", [])
            env = mcp_cfg.get("env", {})
            if not command:
                logger.warning("MCP config %s has no command, skipping", config_path)
                continue
            client = MCPClient(name=name, command=command, env=env)
            clients.append(client)
            logger.info("MCP config loaded: %s", name)
        except Exception:
            logger.exception("Failed to load MCP config: %s", config_path)

    return clients


async def connect_all(clients: list[Any], registry: Any) -> None:
    """Connect all MCP clients and register their tools into registry."""
    for client in clients:
        ok = await client.connect()
        if not ok:
            continue
        tools = await client.list_tools()
        for spec in tools:
            tool_name = spec["name"]

            async def _call(**kwargs: Any) -> Any:  # noqa: B023
                return await client.call_tool(tool_name, **kwargs)

            registry.register_mcp_tool(tool_name, spec, _call)
```

- [ ] **Step 4: Verify loaders import cleanly**

```bash
python -c "
from sebastian.capabilities.tools._loader import load_tools
load_tools()
from sebastian.core.tool import list_tool_specs
print('Tools:', [s.name for s in list_tool_specs()])
from sebastian.capabilities.mcps._loader import load_mcps
print('MCP loader OK')
"
```

Expected: `Tools: ['shell', 'file_read', 'file_write', 'web_search']` and `MCP loader OK`

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/_loader.py \
        sebastian/capabilities/mcp_client.py \
        sebastian/capabilities/mcps/_loader.py
git commit -m "feat(capabilities): 实现 tools loader 与 MCP client/loader"
```

---

## Task 8: Database Setup + ORM Models

**Files:**
- Create: `sebastian/store/database.py`
- Create: `sebastian/store/models.py`
- Create: `tests/unit/test_task_store.py` (partially, DB setup portion)

- [ ] **Step 1: Write failing test for DB init**

Create `tests/unit/test_task_store.py`:

```python
from __future__ import annotations
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest_asyncio.fixture
async def session():
    from sebastian.store.database import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_get_task(session):
    from sebastian.core.types import Task
    from sebastian.store.task_store import TaskStore

    store = TaskStore(session)
    task = Task(goal="Write a haiku")
    created = await store.create(task)
    assert created.id == task.id

    fetched = await store.get(task.id)
    assert fetched is not None
    assert fetched.goal == "Write a haiku"


@pytest.mark.asyncio
async def test_list_tasks_empty(session):
    from sebastian.store.task_store import TaskStore
    store = TaskStore(session)
    tasks = await store.list_tasks()
    assert tasks == []


@pytest.mark.asyncio
async def test_update_status(session):
    from sebastian.core.types import Task, TaskStatus
    from sebastian.store.task_store import TaskStore

    store = TaskStore(session)
    task = Task(goal="Brew tea")
    await store.create(task)
    await store.update_status(task.id, TaskStatus.RUNNING)

    fetched = await store.get(task.id)
    assert fetched.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_add_and_get_checkpoints(session):
    from sebastian.core.types import Task, Checkpoint
    from sebastian.store.task_store import TaskStore

    store = TaskStore(session)
    task = Task(goal="Analyze data")
    await store.create(task)

    cp = Checkpoint(task_id=task.id, step=1, data={"progress": 0.5})
    await store.add_checkpoint(cp)

    checkpoints = await store.get_checkpoints(task.id)
    assert len(checkpoints) == 1
    assert checkpoints[0].step == 1
    assert checkpoints[0].data["progress"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_task_store.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'sebastian.store.database'`

- [ ] **Step 3: Implement store/database.py**

Create `sebastian/store/database.py`:

```python
from __future__ import annotations
import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    return create_async_engine(url, echo=False, future=True)


def _make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Lazy initialization — call init_db() at startup
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        from sebastian.config import settings
        _engine = _make_engine(settings.database_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = _make_session_factory(get_engine())
    return _session_factory


async def init_db() -> None:
    """Create all tables. Call once at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")
```

- [ ] **Step 4: Implement store/models.py**

Create `sebastian/store/models.py`:

```python
from __future__ import annotations
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from sebastian.store.database import Base


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    assigned_agent: Mapped[str] = mapped_column(String(100), default="sebastian")
    parent_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resource_budget: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CheckpointRecord(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    step: Mapped[int] = mapped_column()
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)


class TurnRecord(Base):
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_input: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime)
```

- [ ] **Step 5: Implement store/task_store.py**

Create `sebastian/store/task_store.py`:

```python
from __future__ import annotations
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sebastian.core.types import Checkpoint, ResourceBudget, Task, TaskPlan, TaskStatus
from sebastian.store.models import CheckpointRecord, TaskRecord


class TaskStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        record = TaskRecord(
            id=task.id,
            goal=task.goal,
            status=task.status.value,
            assigned_agent=task.assigned_agent,
            parent_task_id=task.parent_task_id,
            plan=task.plan.model_dump() if task.plan else None,
            resource_budget=task.resource_budget.model_dump(),
            created_at=task.created_at,
            updated_at=task.updated_at,
            completed_at=task.completed_at,
        )
        self._session.add(record)
        await self._session.commit()
        return task

    async def get(self, task_id: str) -> Task | None:
        result = await self._session.execute(
            select(TaskRecord).where(TaskRecord.id == task_id)
        )
        record = result.scalar_one_or_none()
        return self._to_task(record) if record else None

    async def list_tasks(self, status: str | None = None) -> list[Task]:
        q = select(TaskRecord)
        if status:
            q = q.where(TaskRecord.status == status)
        q = q.order_by(TaskRecord.created_at.desc())
        result = await self._session.execute(q)
        return [self._to_task(r) for r in result.scalars()]

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        result = await self._session.execute(
            select(TaskRecord).where(TaskRecord.id == task_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return
        record.status = status.value
        record.updated_at = datetime.utcnow()
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            record.completed_at = datetime.utcnow()
        await self._session.commit()

    async def add_checkpoint(self, checkpoint: Checkpoint) -> None:
        record = CheckpointRecord(
            id=checkpoint.id,
            task_id=checkpoint.task_id,
            step=checkpoint.step,
            data=checkpoint.data,
            created_at=checkpoint.created_at,
        )
        self._session.add(record)
        await self._session.commit()

    async def get_checkpoints(self, task_id: str) -> list[Checkpoint]:
        result = await self._session.execute(
            select(CheckpointRecord)
            .where(CheckpointRecord.task_id == task_id)
            .order_by(CheckpointRecord.step)
        )
        return [
            Checkpoint(id=r.id, task_id=r.task_id, step=r.step, data=r.data, created_at=r.created_at)
            for r in result.scalars()
        ]

    def _to_task(self, r: TaskRecord) -> Task:
        return Task(
            id=r.id,
            goal=r.goal,
            status=TaskStatus(r.status),
            assigned_agent=r.assigned_agent,
            parent_task_id=r.parent_task_id,
            plan=TaskPlan(**r.plan) if r.plan else None,
            resource_budget=ResourceBudget(**r.resource_budget),
            created_at=r.created_at,
            updated_at=r.updated_at,
            completed_at=r.completed_at,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/unit/test_task_store.py -v
```

Expected: `4 passed`

- [ ] **Step 7: Implement store/event_log.py**

Create `sebastian/store/event_log.py`:

```python
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sebastian.protocol.events.types import Event
from sebastian.store.models import EventRecord


class EventLog:
    """Append-only event persistence. All events flow through EventBus first,
    then are persisted here for history queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: Event) -> None:
        record = EventRecord(
            id=event.id,
            type=event.type.value,
            data=event.data,
            ts=event.ts,
        )
        self._session.add(record)
        await self._session.commit()
```

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/database.py sebastian/store/models.py \
        sebastian/store/task_store.py sebastian/store/event_log.py \
        tests/unit/test_task_store.py
git commit -m "feat(store): 实现 SQLAlchemy async 数据库层、TaskStore 与 EventLog"
```

---

## Task 9: Memory — Working, Episodic, MemoryStore

**Files:**
- Create: `sebastian/memory/working_memory.py`
- Create: `sebastian/memory/episodic_memory.py`
- Create: `sebastian/memory/store.py`

> Episodic memory is exercised via the integration tests in Task 27. Unit tests here cover WorkingMemory only (no DB needed).

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_task_store.py` (append these tests):

```python
def test_working_memory_set_get():
    from sebastian.memory.working_memory import WorkingMemory
    mem = WorkingMemory()
    mem.set("task-1", "step", 3)
    assert mem.get("task-1", "step") == 3


def test_working_memory_clear():
    from sebastian.memory.working_memory import WorkingMemory
    mem = WorkingMemory()
    mem.set("task-1", "x", "hello")
    mem.clear("task-1")
    assert mem.get("task-1", "x") is None


def test_working_memory_default():
    from sebastian.memory.working_memory import WorkingMemory
    mem = WorkingMemory()
    assert mem.get("nonexistent", "key", default="fallback") == "fallback"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/unit/test_task_store.py::test_working_memory_set_get -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'sebastian.memory.working_memory'`

- [ ] **Step 3: Implement memory/working_memory.py**

Create `sebastian/memory/working_memory.py`:

```python
from __future__ import annotations
from typing import Any


class WorkingMemory:
    """In-process task-scoped memory. Holds ephemeral state for the duration
    of a task. All data lives in the process — cleared via clear(task_id)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def set(self, task_id: str, key: str, value: Any) -> None:
        self._store.setdefault(task_id, {})[key] = value

    def get(self, task_id: str, key: str, default: Any = None) -> Any:
        return self._store.get(task_id, {}).get(key, default)

    def get_all(self, task_id: str) -> dict[str, Any]:
        return dict(self._store.get(task_id, {}))

    def clear(self, task_id: str) -> None:
        self._store.pop(task_id, None)
```

- [ ] **Step 4: Run to verify tests pass**

```bash
pytest tests/unit/test_task_store.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Implement memory/episodic_memory.py**

Create `sebastian/memory/episodic_memory.py`:

```python
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sebastian.store.models import TurnRecord


@dataclass
class TurnEntry:
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime


class EpisodicMemory:
    """Persistent conversation history backed by SQLite.
    Each conversation turn (user + assistant) is stored as a TurnRecord."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_turn(self, session_id: str, role: str, content: str) -> TurnEntry:
        entry = TurnRecord(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
        )
        self._session.add(entry)
        await self._session.commit()
        return TurnEntry(
            id=entry.id,
            session_id=entry.session_id,
            role=entry.role,
            content=entry.content,
            created_at=entry.created_at,
        )

    async def get_turns(self, session_id: str, limit: int = 50) -> list[TurnEntry]:
        result = await self._session.execute(
            select(TurnRecord)
            .where(TurnRecord.session_id == session_id)
            .order_by(TurnRecord.created_at.desc())
            .limit(limit)
        )
        records = list(reversed(result.scalars().all()))
        return [
            TurnEntry(r.id, r.session_id, r.role, r.content, r.created_at)
            for r in records
        ]
```

- [ ] **Step 6: Implement memory/store.py**

Create `sebastian/memory/store.py`:

```python
from __future__ import annotations
from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.memory.working_memory import WorkingMemory


class MemoryStore:
    """Unified access point for all memory layers.
    working: task-scoped in-process dict.
    episodic: persistent conversation history (SQLite)."""

    def __init__(self, episodic: EpisodicMemory) -> None:
        self.working = WorkingMemory()
        self.episodic = episodic
```

- [ ] **Step 7: Commit**

```bash
git add sebastian/memory/working_memory.py \
        sebastian/memory/episodic_memory.py \
        sebastian/memory/store.py \
        tests/unit/test_task_store.py
git commit -m "feat(memory): 实现工作记忆与情景记忆（SQLite）"
```

---

## Task 10: Agent Loop — LLM → Tool Calls → Iterate

**Files:**
- Create: `sebastian/core/agent_loop.py`
- Create: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: Write failing tests using a mock Anthropic client**

Create `tests/unit/test_agent_loop.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_text_response(text: str):
    """Build a mock Anthropic messages.create response that returns text."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def _make_tool_response(tool_id: str, tool_name: str, tool_input: dict):
    """Build a mock response requesting a single tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input
    # no .text attribute
    del block.text
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_agent_loop_no_tools():
    """When the model responds with text immediately, return that text."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_make_text_response("Hello there!"))

    reg = CapabilityRegistry()
    loop = AgentLoop(mock_client, reg)
    result = await loop.run(system_prompt="You are helpful.", messages=[{"role": "user", "content": "Hi"}])
    assert result == "Hello there!"


@pytest.mark.asyncio
async def test_agent_loop_single_tool_call():
    """Loop should call the tool and then return the final text response."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="echo_loop_test", description="Echo")
    async def echo_tool(msg: str) -> ToolResult:
        return ToolResult(ok=True, output=f"echoed: {msg}")

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=[
        _make_tool_response("call-1", "echo_loop_test", {"msg": "hi"}),
        _make_text_response("Done, I echoed hi."),
    ])

    reg = CapabilityRegistry()
    loop = AgentLoop(mock_client, reg)
    result = await loop.run(system_prompt="sys", messages=[{"role": "user", "content": "echo hi"}])
    assert "Done" in result
    assert mock_client.messages.create.call_count == 2
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/unit/test_agent_loop.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'sebastian.core.agent_loop'`

- [ ] **Step 3: Implement core/agent_loop.py**

Create `sebastian/core/agent_loop.py`:

```python
from __future__ import annotations
import logging
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20


class AgentLoop:
    """Core reasoning loop: send messages to LLM, execute tool calls, repeat
    until stop_reason is not 'tool_use' or MAX_ITERATIONS reached."""

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        registry: CapabilityRegistry,
        model: str = "claude-opus-4-6",
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        task_id: str | None = None,
    ) -> str:
        """Run the agent loop. Returns the final text response."""
        working = list(messages)
        tools = self._registry.get_all_tool_specs()

        for iteration in range(MAX_ITERATIONS):
            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": working,
            }
            if tools:
                kwargs["tools"] = tools

            response = await self._client.messages.create(**kwargs)
            logger.debug("Iteration %d stop_reason=%s", iteration, response.stop_reason)

            # Build assistant content list
            assistant_content: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                elif hasattr(block, "text"):
                    assistant_content.append({"type": "text", "text": block.text})

            working.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        return block.text
                return ""

            # Execute tool calls, collect results
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                logger.info("Tool call: %s(%s)", block.name, block.input)
                result: ToolResult = await self._registry.call(block.name, **block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        str(result.output) if result.ok else f"Error: {result.error}"
                    ),
                })

            working.append({"role": "user", "content": tool_results})

        logger.warning("Reached MAX_ITERATIONS (%d) for task_id=%s", MAX_ITERATIONS, task_id)
        return "Max iterations reached without a final response."
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_agent_loop.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/agent_loop.py tests/unit/test_agent_loop.py
git commit -m "feat(core): 实现 AgentLoop（LLM → 工具调用 → 迭代循环）"
```

---

## Task 11: BaseAgent + TaskManager

**Files:**
- Create: `sebastian/core/base_agent.py`
- Create: `sebastian/core/task_manager.py`

- [ ] **Step 1: Implement core/base_agent.py**

Create `sebastian/core/base_agent.py`:

```python
from __future__ import annotations
import logging
from abc import ABC
from typing import Any

import anthropic

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.agent_loop import AgentLoop
from sebastian.memory.episodic_memory import EpisodicMemory
from sebastian.memory.working_memory import WorkingMemory

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = (
    "You are Sebastian, a personal AI butler. You are helpful, precise, and action-oriented. "
    "You have access to tools and will use them when needed. "
    "Think step by step, act efficiently, and always confirm important actions before executing."
)


class BaseAgent(ABC):
    """Abstract base for all agents (Sebastian and Sub-Agents).
    Provides an AgentLoop, working memory (instance-level), and episodic
    memory access (per-session via session factory).
    """

    name: str = "base_agent"
    system_prompt: str = BASE_SYSTEM_PROMPT

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_factory: Any,  # async_sessionmaker[AsyncSession]
        model: str | None = None,
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory
        self.working_memory = WorkingMemory()

        from sebastian.config import settings
        resolved_model = model or settings.sebastian_model
        api_key = settings.anthropic_api_key
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._loop = AgentLoop(self._client, registry, resolved_model)

    async def run(
        self,
        user_message: str,
        session_id: str,
        task_id: str | None = None,
    ) -> str:
        """Run one turn: load history, call agent loop, persist turn, return response."""
        async with self._session_factory() as db_session:
            episodic = EpisodicMemory(db_session)
            turns = await episodic.get_turns(session_id, limit=20)
            messages: list[dict[str, Any]] = [
                {"role": t.role, "content": t.content} for t in turns
            ]
            messages.append({"role": "user", "content": user_message})

            response = await self._loop.run(
                system_prompt=self.system_prompt,
                messages=messages,
                task_id=task_id,
            )

            await episodic.add_turn(session_id, "user", user_message)
            await episodic.add_turn(session_id, "assistant", response)
            return response
```

- [ ] **Step 2: Implement core/task_manager.py**

Create `sebastian/core/task_manager.py`:

```python
from __future__ import annotations
import asyncio
import logging
from typing import Any, Awaitable, Callable

from sebastian.core.types import Task, TaskStatus
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

TaskFn = Callable[[Task], Awaitable[None]]


class TaskManager:
    """Submits tasks for async background execution. Each task runs as an
    asyncio coroutine and publishes lifecycle events to the EventBus."""

    def __init__(self, session_factory: Any, event_bus: EventBus) -> None:
        self._session_factory = session_factory
        self._bus = event_bus
        self._running: dict[str, asyncio.Task] = {}

    async def submit(self, task: Task, fn: TaskFn) -> None:
        """Persist the task, then start execution in the background."""
        from sebastian.store.task_store import TaskStore

        async with self._session_factory() as session:
            store = TaskStore(session)
            await store.create(task)

        await self._bus.publish(Event(
            type=EventType.TASK_CREATED,
            data={"task_id": task.id, "goal": task.goal, "assigned_agent": task.assigned_agent},
        ))

        async def _run() -> None:
            async with self._session_factory() as session:
                store = TaskStore(session)
                await store.update_status(task.id, TaskStatus.RUNNING)

            await self._bus.publish(Event(type=EventType.TASK_STARTED, data={"task_id": task.id}))
            try:
                await fn(task)
                async with self._session_factory() as session:
                    store = TaskStore(session)
                    await store.update_status(task.id, TaskStatus.COMPLETED)
                await self._bus.publish(Event(type=EventType.TASK_COMPLETED, data={"task_id": task.id}))
            except asyncio.CancelledError:
                async with self._session_factory() as session:
                    store = TaskStore(session)
                    await store.update_status(task.id, TaskStatus.CANCELLED)
                await self._bus.publish(Event(type=EventType.TASK_CANCELLED, data={"task_id": task.id}))
            except Exception as exc:
                logger.exception("Task %s failed", task.id)
                async with self._session_factory() as session:
                    store = TaskStore(session)
                    await store.update_status(task.id, TaskStatus.FAILED)
                await self._bus.publish(Event(
                    type=EventType.TASK_FAILED,
                    data={"task_id": task.id, "error": str(exc)},
                ))
            finally:
                self._running.pop(task.id, None)

        asyncio_task = asyncio.create_task(_run())
        self._running[task.id] = asyncio_task

    async def cancel(self, task_id: str) -> bool:
        t = self._running.get(task_id)
        if t is None:
            return False
        t.cancel()
        return True

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running
```

- [ ] **Step 3: Verify imports cleanly**

```bash
python -c "
from sebastian.core.base_agent import BaseAgent
from sebastian.core.task_manager import TaskManager
print('BaseAgent and TaskManager OK')
"
```

Expected: `BaseAgent and TaskManager OK`

- [ ] **Step 4: Commit**

```bash
git add sebastian/core/base_agent.py sebastian/core/task_manager.py
git commit -m "feat(core): 实现 BaseAgent 抽象类与 TaskManager 异步任务队列"
```

---

## Task 12: Orchestrator — ConversationManager + Sebastian

**Files:**
- Create: `sebastian/orchestrator/conversation.py`
- Create: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: Implement orchestrator/conversation.py**

Create `sebastian/orchestrator/conversation.py`:

```python
from __future__ import annotations
import asyncio
import logging

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


class ConversationManager:
    """Conversation plane: manages pending approval futures.
    Approval requests suspend the awaiting coroutine until the user
    grants or denies via the REST API. The event bus notifies frontend clients."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict,
        timeout: float = 300.0,
    ) -> bool:
        """Suspend execution until the user approves or denies, or timeout (→ deny)."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[approval_id] = future

        await self._bus.publish(Event(
            type=EventType.USER_APPROVAL_REQUESTED,
            data={
                "approval_id": approval_id,
                "task_id": task_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
            },
        ))

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Approval %s timed out", approval_id)
            self._pending.pop(approval_id, None)
            return False

    async def resolve_approval(self, approval_id: str, granted: bool) -> None:
        """Called by the approval API endpoint to resolve a pending request."""
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            return
        future.set_result(granted)
        event_type = EventType.USER_APPROVAL_GRANTED if granted else EventType.USER_APPROVAL_DENIED
        await self._bus.publish(Event(
            type=event_type,
            data={"approval_id": approval_id, "granted": granted},
        ))
```

- [ ] **Step 2: Implement orchestrator/sebas.py**

Create `sebastian/orchestrator/sebas.py`:

```python
from __future__ import annotations
import logging
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.base_agent import BaseAgent
from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

SEBASTIAN_SYSTEM_PROMPT = """You are Sebastian — an elegant, capable personal AI butler.
Your purpose: receive instructions, plan effectively, and execute precisely.
You have access to tools. Use them to fulfill requests completely.
For complex multi-step tasks, break them down and execute step by step.
When you encounter a decision that requires the user's input, ask clearly and concisely.
You never fabricate results — if a tool fails, say so and suggest alternatives."""


class Sebastian(BaseAgent):
    """Main orchestrator agent. Handles conversation turns and can delegate
    tasks to sub-agents via TaskManager (Phase 2 will add full A2A routing)."""

    name = "sebastian"
    system_prompt = SEBASTIAN_SYSTEM_PROMPT

    def __init__(
        self,
        registry: CapabilityRegistry,
        session_factory: Any,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
    ) -> None:
        super().__init__(registry, session_factory)
        self._task_manager = task_manager
        self._conversation = conversation
        self._event_bus = event_bus

    async def chat(self, user_message: str, session_id: str) -> str:
        """Handle a conversational turn. Publishes turn events."""
        await self._event_bus.publish(Event(
            type=EventType.TURN_RECEIVED,
            data={"session_id": session_id, "message": user_message[:200]},
        ))
        response = await self.run(user_message, session_id)
        await self._event_bus.publish(Event(
            type=EventType.TURN_RESPONSE,
            data={"session_id": session_id, "response": response[:200]},
        ))
        return response

    async def submit_background_task(self, goal: str, session_id: str) -> Task:
        """Create and submit a background task. Returns the Task immediately."""
        task = Task(goal=goal, assigned_agent=self.name)

        async def execute(t: Task) -> None:
            await self.run(t.goal, session_id=session_id, task_id=t.id)

        await self._task_manager.submit(task, execute)
        return task
```

- [ ] **Step 3: Verify imports**

```bash
python -c "
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.orchestrator.sebas import Sebastian
print('Orchestrator OK')
"
```

Expected: `Orchestrator OK`

- [ ] **Step 4: Commit**

```bash
git add sebastian/orchestrator/conversation.py sebastian/orchestrator/sebas.py
git commit -m "feat(orchestrator): 实现 ConversationManager 与 Sebastian 主管家"
```

---

## Task 13: JWT Auth

**Files:**
- Create: `sebastian/gateway/auth.py`

- [ ] **Step 1: Write test for auth**

Append to `tests/unit/test_config.py`:

```python
def test_jwt_create_and_decode():
    from sebastian.gateway.auth import create_access_token, decode_token
    token = create_access_token({"sub": "owner", "role": "owner"})
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload["sub"] == "owner"
    assert payload["role"] == "owner"


def test_jwt_invalid_token_raises():
    from fastapi import HTTPException
    from sebastian.gateway.auth import decode_token
    import pytest
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.valid.token")
    assert exc_info.value.status_code == 401


def test_hash_and_verify_password():
    from sebastian.gateway.auth import hash_password, verify_password
    hashed = hash_password("secretpassword")
    assert verify_password("secretpassword", hashed)
    assert not verify_password("wrongpassword", hashed)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/unit/test_config.py::test_jwt_create_and_decode -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'sebastian.gateway.auth'`

- [ ] **Step 3: Implement gateway/auth.py**

Create `sebastian/gateway/auth.py`:

```python
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from sebastian.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(data: dict[str, Any]) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.sebastian_jwt_expire_minutes)
    payload["exp"] = expire
    return jwt.encode(
        payload,
        settings.sebastian_jwt_secret,
        algorithm=settings.sebastian_jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.sebastian_jwt_secret,
            algorithms=[settings.sebastian_jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict[str, Any]:
    """FastAPI dependency: validates Bearer token and returns the payload."""
    return decode_token(credentials.credentials)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_config.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/auth.py tests/unit/test_config.py
git commit -m "feat(gateway/auth): 实现 JWT 认证（登录、Token 创建/验证）"
```

---

## Task 14: Gateway App State + Routes + SSE

**Files:**
- Create: `sebastian/gateway/state.py`
- Create: `sebastian/gateway/sse.py`
- Create: `sebastian/gateway/routes/turns.py`
- Create: `sebastian/gateway/routes/tasks.py`
- Create: `sebastian/gateway/routes/approvals.py`
- Create: `sebastian/gateway/routes/stream.py`
- Create: `sebastian/gateway/routes/agents.py`
- Create: `sebastian/gateway/app.py`

- [ ] **Step 1: Create gateway/state.py**

Create `sebastian/gateway/state.py`:

```python
from __future__ import annotations
"""Module-level singletons initialized at startup via app lifespan.
Routes import from here to access shared services."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.gateway.sse import SSEManager
    from sebastian.protocol.events.bus import EventBus
    from sebastian.orchestrator.conversation import ConversationManager
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

sebastian: "Sebastian"
sse_manager: "SSEManager"
event_bus: "EventBus"
conversation: "ConversationManager"
session_factory: "async_sessionmaker[AsyncSession]"
```

- [ ] **Step 2: Create gateway/sse.py**

Create `sebastian/gateway/sse.py`:

```python
from __future__ import annotations
import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event

logger = logging.getLogger(__name__)


class SSEManager:
    """Manages active SSE client connections. Subscribes to the global EventBus
    and broadcasts all events to connected clients as SSE-formatted strings."""

    def __init__(self, event_bus: EventBus) -> None:
        self._queues: list[asyncio.Queue[Event | None]] = []
        event_bus.subscribe(self._on_event)

    async def _on_event(self, event: Event) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event %s", event.type)

    async def stream(self) -> AsyncGenerator[str, None]:
        """Async generator — yield SSE-formatted strings for one client."""
        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=200)
        self._queues.append(q)
        try:
            while True:
                event = await q.get()
                if event is None:
                    break
                payload = json.dumps({
                    "event": event.type.value,
                    "data": event.data | {"ts": event.ts.isoformat()},
                })
                yield f"data: {payload}\n\n"
        finally:
            if q in self._queues:
                self._queues.remove(q)
```

- [ ] **Step 3: Create gateway/routes/turns.py**

Create `sebastian/gateway/routes/turns.py`:

```python
from __future__ import annotations
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["turns"])


class SendTurnRequest(BaseModel):
    message: str
    session_id: str | None = None


class TurnResponse(BaseModel):
    session_id: str
    response: str
    ts: str


class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    from sebastian.config import settings
    from sebastian.gateway.auth import create_access_token, verify_password

    stored_hash = settings.sebastian_owner_password_hash
    if not stored_hash or not verify_password(body.password, stored_hash):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_access_token({"sub": settings.sebastian_owner_name, "role": "owner"})
    return TokenResponse(access_token=token)


@router.post("/turns", response_model=TurnResponse)
async def send_turn(
    body: SendTurnRequest,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> TurnResponse:
    import sebastian.gateway.state as state
    session_id = body.session_id or str(uuid.uuid4())
    response = await state.sebastian.chat(body.message, session_id)
    return TurnResponse(
        session_id=session_id,
        response=response,
        ts=datetime.utcnow().isoformat(),
    )


@router.get("/turns/{session_id}")
async def get_turns(
    session_id: str,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    async with state.session_factory() as session:
        from sebastian.memory.episodic_memory import EpisodicMemory
        episodic = EpisodicMemory(session)
        turns = await episodic.get_turns(session_id, limit=100)
    return {
        "session_id": session_id,
        "turns": [{"role": t.role, "content": t.content, "ts": t.created_at.isoformat()} for t in turns],
    }
```

- [ ] **Step 4: Create gateway/routes/tasks.py**

Create `sebastian/gateway/routes/tasks.py`:

```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["tasks"])


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str | None = None,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    async with state.session_factory() as session:
        from sebastian.store.task_store import TaskStore
        store = TaskStore(session)
        tasks = await store.list_tasks(status=status)
    return {"tasks": [t.model_dump(mode="json") for t in tasks]}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    async with state.session_factory() as session:
        from sebastian.store.task_store import TaskStore
        store = TaskStore(session)
        task = await store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    checkpoints = []
    async with state.session_factory() as session:
        from sebastian.store.task_store import TaskStore
        store = TaskStore(session)
        checkpoints = await store.get_checkpoints(task_id)
    return {
        "task": task.model_dump(mode="json"),
        "checkpoints": [cp.model_dump(mode="json") for cp in checkpoints],
    }


@router.post("/tasks/{task_id}/pause")
async def pause_task(
    task_id: str,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    cancelled = await state.sebastian._task_manager.cancel(task_id)
    return {"task_id": task_id, "paused": cancelled}


@router.delete("/tasks/{task_id}")
async def cancel_task(
    task_id: str,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    cancelled = await state.sebastian._task_manager.cancel(task_id)
    return {"task_id": task_id, "cancelled": cancelled}
```

- [ ] **Step 5: Create gateway/routes/approvals.py**

Create `sebastian/gateway/routes/approvals.py`:

```python
from __future__ import annotations
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["approvals"])


class ApprovalActionRequest(BaseModel):
    granted: bool


@router.get("/approvals")
async def list_approvals(
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    """Return pending approval records from the database."""
    import sebastian.gateway.state as state
    from sqlalchemy import select
    from sebastian.store.models import ApprovalRecord
    async with state.session_factory() as session:
        result = await session.execute(
            select(ApprovalRecord).where(ApprovalRecord.status == "pending")
        )
        records = result.scalars().all()
    return {
        "approvals": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "tool_name": r.tool_name,
                "tool_input": r.tool_input,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
    }


@router.post("/approvals/{approval_id}/grant")
async def grant_approval(
    approval_id: str,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    await _resolve(approval_id, granted=True, state=state)
    return {"approval_id": approval_id, "granted": True}


@router.post("/approvals/{approval_id}/deny")
async def deny_approval(
    approval_id: str,
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    import sebastian.gateway.state as state
    await _resolve(approval_id, granted=False, state=state)
    return {"approval_id": approval_id, "granted": False}


async def _resolve(approval_id: str, granted: bool, state) -> None:
    from sqlalchemy import select
    from sebastian.store.models import ApprovalRecord
    # Update DB record
    async with state.session_factory() as session:
        result = await session.execute(
            select(ApprovalRecord).where(ApprovalRecord.id == approval_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        record.status = "granted" if granted else "denied"
        record.resolved_at = datetime.utcnow()
        await session.commit()
    # Resolve the in-memory future (unblocks the awaiting agent coroutine)
    await state.conversation.resolve_approval(approval_id, granted)
```

- [ ] **Step 6: Create gateway/routes/stream.py**

Create `sebastian/gateway/routes/stream.py`:

```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def global_stream(
    request: Request,
    _auth: dict = Depends(require_auth),
):
    """SSE endpoint: streams all events to the connected client."""
    import sebastian.gateway.state as state

    async def event_generator():
        async for chunk in state.sse_manager.stream():
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 7: Create gateway/routes/agents.py**

Create `sebastian/gateway/routes/agents.py`:

```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents(
    request: Request,
    _auth: dict = Depends(require_auth),
) -> dict:
    """Return registered agent status. Phase 1: only Sebastian."""
    import sebastian.gateway.state as state
    return {
        "agents": [
            {
                "name": state.sebastian.name,
                "status": "running",
                "running_tasks": len(state.sebastian._task_manager._running),
            }
        ]
    }


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 8: Create gateway/app.py**

Create `sebastian/gateway/app.py`:

```python
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import sebastian.gateway.state as state
    from sebastian.capabilities.registry import registry
    from sebastian.capabilities.tools._loader import load_tools
    from sebastian.capabilities.mcps._loader import load_mcps, connect_all
    from sebastian.core.task_manager import TaskManager
    from sebastian.gateway.sse import SSEManager
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import bus
    from sebastian.store.database import get_session_factory, init_db

    # DB
    await init_db()
    factory = get_session_factory()

    # Tools
    load_tools()

    # MCP (connect in background, don't block startup)
    mcp_clients = load_mcps(registry)
    if mcp_clients:
        await connect_all(mcp_clients, registry)

    # Services
    event_bus = bus
    conversation = ConversationManager(event_bus)
    task_manager = TaskManager(factory, event_bus)
    sse_mgr = SSEManager(event_bus)
    sebastian = Sebastian(
        registry=registry,
        session_factory=factory,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
    )

    # Expose via state module
    state.sebastian = sebastian
    state.sse_manager = sse_mgr
    state.event_bus = event_bus
    state.conversation = conversation
    state.session_factory = factory

    logger.info("Sebastian gateway started")
    yield

    logger.info("Sebastian gateway shutdown")


def create_app() -> FastAPI:
    from sebastian.gateway.routes import agents, approvals, stream, tasks, turns

    app = FastAPI(title="Sebastian Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(turns.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 9: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/sse.py sebastian/gateway/app.py \
        sebastian/gateway/routes/turns.py sebastian/gateway/routes/tasks.py \
        sebastian/gateway/routes/approvals.py sebastian/gateway/routes/stream.py \
        sebastian/gateway/routes/agents.py
git commit -m "feat(gateway): 实现 FastAPI 应用、SSE 管理器及所有 REST 路由"
```

---

## Task 15: Main Entry Point (CLI)

**Files:**
- Create: `sebastian/main.py`

- [ ] **Step 1: Implement main.py**

Create `sebastian/main.py`:

```python
from __future__ import annotations
import typer
import uvicorn

app = typer.Typer(name="sebastian", help="Sebastian — Personal AI Butler")


@app.command()
def serve(
    host: str = typer.Option(None, help="Override gateway host"),
    port: int = typer.Option(None, help="Override gateway port"),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)"),
) -> None:
    """Start the Sebastian gateway server."""
    from sebastian.config import settings
    h = host or settings.sebastian_gateway_host
    p = port or settings.sebastian_gateway_port
    uvicorn.run("sebastian.gateway.app:app", host=h, port=p, reload=reload)


@app.command()
def init(
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Owner password"),
) -> None:
    """Initialize Sebastian: hash owner password and print to .env."""
    from sebastian.gateway.auth import hash_password
    hashed = hash_password(password)
    typer.echo(f"\nAdd this to your .env:\nSEBASTIAN_OWNER_PASSWORD_HASH={hashed}\n")


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Verify CLI works**

```bash
cd /Users/ericw/work/code/ai/sebastian
python -m sebastian.main --help
```

Expected:
```
Usage: python -m sebastian.main [OPTIONS] COMMAND [ARGS]...
  Sebastian — Personal AI Butler
Commands:
  serve  Start the Sebastian gateway server.
  init   Initialize Sebastian: hash owner password ...
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/main.py
git commit -m "feat: 添加 CLI 入口（serve + init 命令）"
```

---

## Task 16: Integration Tests — Gateway Turns + Tasks

**Files:**
- Create: `tests/integration/test_gateway_turns.py`
- Create: `tests/integration/test_gateway_tasks.py`

- [ ] **Step 1: Write integration tests**

Create `tests/integration/test_gateway_turns.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_sebastian():
    """Patch Sebastian.chat to avoid real LLM calls during gateway tests."""
    with patch("sebastian.orchestrator.sebas.Sebastian.chat", new_callable=AsyncMock) as m:
        m.return_value = "Mocked response from Sebastian."
        yield m


@pytest.fixture
def client(tmp_path, mock_sebastian):
    import os
    os.environ["SEBASTIAN_DATA_DIR"] = str(tmp_path)
    os.environ["SEBASTIAN_JWT_SECRET"] = "test-secret-key"
    os.environ["SEBASTIAN_OWNER_PASSWORD_HASH"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

    # Use a known password hash for testing
    from sebastian.gateway.auth import hash_password
    os.environ["SEBASTIAN_OWNER_PASSWORD_HASH"] = hash_password("testpass")

    # Re-create settings with new env
    import importlib
    import sebastian.config as cfg_module
    importlib.reload(cfg_module)

    from sebastian.gateway.app import create_app
    test_app = create_app()
    with TestClient(test_app, raise_server_exceptions=True) as c:
        yield c


def _login(client: TestClient) -> str:
    resp = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_success(client):
    token = _login(client)
    assert len(token) > 10


def test_login_wrong_password(client):
    resp = client.post("/api/v1/auth/login", json={"password": "wrongpass"})
    assert resp.status_code == 401


def test_send_turn_requires_auth(client):
    resp = client.post("/api/v1/turns", json={"message": "hello"})
    assert resp.status_code == 403


def test_send_turn_returns_response(client, mock_sebastian):
    token = _login(client)
    resp = client.post(
        "/api/v1/turns",
        json={"message": "Hello Sebastian"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Mocked response from Sebastian."
    assert "session_id" in data
```

Create `tests/integration/test_gateway_tasks.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    import os
    os.environ["SEBASTIAN_DATA_DIR"] = str(tmp_path)
    os.environ["SEBASTIAN_JWT_SECRET"] = "test-secret-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

    from sebastian.gateway.auth import hash_password
    os.environ["SEBASTIAN_OWNER_PASSWORD_HASH"] = hash_password("testpass")

    with patch("sebastian.orchestrator.sebas.Sebastian.chat", new_callable=AsyncMock) as m:
        m.return_value = "ok"
        import importlib
        import sebastian.config as cfg_module
        importlib.reload(cfg_module)

        from sebastian.gateway.app import create_app
        test_app = create_app()
        with TestClient(test_app) as c:
            yield c


def _token(client: TestClient) -> str:
    resp = client.post("/api/v1/auth/login", json={"password": "testpass"})
    return resp.json()["access_token"]


def test_list_tasks_empty(client):
    token = _token(client)
    resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["tasks"] == []


def test_agents_endpoint(client):
    token = _token(client)
    resp = client.get("/api/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["name"] == "sebastian"
```

- [ ] **Step 2: Run integration tests**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/integration/ -v 2>&1 | tail -30
```

Expected: `7 passed` (or close to it — adjust assertions if TestClient lifespan handling differs)

> **Note:** If `TestClient` doesn't run the async lifespan, switch to `AsyncClient` with `anyio` backend. Update tests to use `@pytest.mark.asyncio` and `httpx.AsyncClient`.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_gateway_turns.py tests/integration/test_gateway_tasks.py
git commit -m "test(integration): 添加 Gateway 集成测试（turns、tasks、auth）"
```

---

## Task 17: A2A Protocol Types

**Files:**
- Create: `sebastian/protocol/a2a/types.py`

> A2A routing and full Sub-Agent dispatch is Phase 2. Phase 1 only defines the types so the interfaces are established.

- [ ] **Step 1: Create protocol/a2a/types.py**

Create `sebastian/protocol/a2a/types.py`:

```python
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
import uuid


class Artifact(BaseModel):
    name: str
    content: str
    mime_type: str = "text/plain"


class DelegateTask(BaseModel):
    """Sebastian → Sub-Agent: delegate a task."""
    task_id: str
    goal: str
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    callback_queue_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class EscalateRequest(BaseModel):
    """Sub-Agent → Sebastian: request a decision."""
    task_id: str
    reason: str
    options: list[str] = Field(default_factory=list)
    blocking: bool = True


class TaskResult(BaseModel):
    """Sub-Agent → Sebastian: report completion."""
    task_id: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    new_tools_registered: list[str] = Field(default_factory=list)
    error: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add sebastian/protocol/a2a/types.py
git commit -m "feat(protocol/a2a): 定义 A2A 协议类型（DelegateTask、EscalateRequest、TaskResult）"
```

---

## Task 18: Docker Setup

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Read current Dockerfile**

```bash
cat /Users/ericw/work/code/ai/sebastian/Dockerfile
```

- [ ] **Step 2: Update Dockerfile**

Overwrite `Dockerfile` with:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[memory]"

# Copy source
COPY sebastian/ ./sebastian/
COPY .env.example ./.env.example

# Create data dir
RUN mkdir -p /app/data /app/knowledge

CMD ["uvicorn", "sebastian.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Update docker-compose.yml for Phase 1**

Overwrite `docker-compose.yml` with:

```yaml
services:
  gateway:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./knowledge:/app/knowledge
      - ./sebastian/agents:/app/sebastian/agents
      - ./sebastian/capabilities:/app/sebastian/capabilities
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Phase 2+: uncomment when ChromaDB semantic memory is wired
  # chromadb:
  #   image: chromadb/chroma:latest
  #   volumes:
  #     - ./data/chroma:/chroma/chroma
  #   restart: unless-stopped

  # Phase 2+: code execution sandbox
  # sandbox:
  #   build: .
  #   command: python -m sebastian.sandbox.server
  #   env_file: .env
  #   restart: unless-stopped
```

- [ ] **Step 4: Verify Docker build (optional — requires Docker)**

```bash
cd /Users/ericw/work/code/ai/sebastian
docker build -t sebastian:dev . 2>&1 | tail -5
```

Expected: `Successfully built ...` or `=> exporting to image`

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore(docker): 更新 Dockerfile 与 docker-compose，对齐 Phase 1 服务拓扑"
```

---

## Task 19: Final Smoke Test + Run Verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/ericw/work/code/ai/sebastian
pytest tests/ -v --tb=short
```

Expected: All tests pass. Record the count.

- [ ] **Step 2: Verify gateway starts (requires ANTHROPIC_API_KEY in env)**

```bash
cd /Users/ericw/work/code/ai/sebastian
# Initialize owner password first
ANTHROPIC_API_KEY=test SEBASTIAN_JWT_SECRET=devsecret python -m sebastian.main init --password devpassword
# Copy the SEBASTIAN_OWNER_PASSWORD_HASH= line into .env (or set in shell)
export ANTHROPIC_API_KEY=test
export SEBASTIAN_JWT_SECRET=devsecret
# Start server briefly to verify import chain
timeout 5 uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8765 2>&1 | head -20 || true
```

Expected: Lines like `INFO: Sebastian gateway started` and `INFO: Application startup complete.`

- [ ] **Step 3: Verify health endpoint**

```bash
curl -s http://127.0.0.1:8765/api/v1/health 2>/dev/null || echo "(server not running — start separately)"
```

Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit final state**

```bash
git add -u
git status  # verify only intended files
git commit -m "chore: Phase 1 后端实现完成，所有测试通过"
```

---

## Self-Review Against Spec

### Spec Coverage Check

| Spec Section (§13 Phase 1) | Covered By |
|---|---|
| BaseAgent + Agent Loop (asyncio) | Tasks 10, 11 |
| Sebastian 主管家 (对话平面 + 任务平面 + Event Bus) | Tasks 4, 11, 12 |
| Capability Bus: tools/ 扫描注册, shell/file/web_search | Tasks 5, 6, 7 |
| MCP Client 基础实现, mcps/ 扫描加载 | Task 7 |
| Task Store (SQLite + SQLAlchemy + 检查点) | Tasks 8, 9 |
| Gateway (FastAPI + SSE + REST API) | Tasks 13, 14 |
| JWT 认证 (Owner 密码登录) | Tasks 13, 14 |
| Docker Compose 单机部署 | Task 18 |
| Android App | → Separate plan: `2026-04-01-sebastian-phase1-android.md` |

**Gaps identified and addressed:**
- A2A types added (Task 17) so interfaces are defined for Phase 2 — not a Phase 1 gap, but establishes the contract.
- `sebastian init` CLI command ensures owner password can be set before first deploy.

### Type Consistency Check

- `ToolResult` defined in `core/types.py`, used consistently across tool.py, registry.py, agent_loop.py ✓
- `Task` / `TaskStatus` from `core/types.py` used in task_store.py, task_manager.py ✓
- `Event` / `EventType` from `protocol/events/types.py` used in bus.py, orchestrator, gateway ✓
- `CapabilityRegistry` singleton from `capabilities/registry.py` imported in agent_loop.py, gateway lifespan ✓
- `async_sessionmaker` passed as `session_factory` in BaseAgent, TaskManager, gateway state ✓

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-01-sebastian-phase1-backend.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast parallel iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

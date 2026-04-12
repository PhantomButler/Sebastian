# Permission System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 tool call 执行链引入三档权限体系（LOW / MODEL_DECIDES / HIGH_RISK），通过 PolicyGate 代理 CapabilityRegistry，使权限执行成为必经路径而非可绕过的继承行为；同时重组 tool 目录结构并补充文档。

**Architecture:** 新增 `sebastian/permissions/` 子包（types、reviewer、gate）；`PolicyGate` 包裹 `CapabilityRegistry`，是 Agent 访问工具的唯一入口；`PermissionReviewer` 是无状态 LLM 单次调用，对 MODEL_DECIDES 工具逐次判断是否升级审批；`BaseAgent` 和 `AgentLoop` 改为接收 `PolicyGate`，`ConversationManager` 移除超时改为无限等待并携带 reason。

**Tech Stack:** Python 3.12+, anthropic SDK, SQLAlchemy async, pytest + pytest-asyncio, unittest.mock

**Spec:** `docs/superpowers/specs/2026-04-05-permission-system-design.md`

---

## File Map

### 新建

| 文件 | 职责 |
|---|---|
| `sebastian/permissions/__init__.py` | 包入口（空） |
| `sebastian/permissions/types.py` | `PermissionTier`、`ToolCallContext`、`ReviewDecision` |
| `sebastian/permissions/reviewer.py` | `PermissionReviewer`：无状态 LLM 审查 |
| `sebastian/permissions/gate.py` | `PolicyGate`：权限代理 |
| `sebastian/core/protocols.py` | `ApprovalManagerProtocol`、`ToolSpecProvider` Protocol |
| `sebastian/capabilities/tools/file_ops/__init__.py` | file_read / file_write（从 file_ops.py 迁移） |
| `sebastian/capabilities/tools/shell/__init__.py` | shell（从 shell.py 迁移） |
| `sebastian/capabilities/tools/web_search/__init__.py` | web_search（从 web_search.py 迁移） |
| `sebastian/capabilities/tools/README.md` | Tool 系统完整指南 |
| `tests/unit/test_permission_types.py` | PermissionTier 枚举测试 |
| `tests/unit/test_permission_reviewer.py` | PermissionReviewer 单元测试 |
| `tests/unit/test_policy_gate.py` | PolicyGate 全路径测试 |
| `tests/integration/test_permission_flow.py` | 审批全链路集成测试 |

### 修改

| 文件 | 改动 |
|---|---|
| `sebastian/core/tool.py` | 移除 `requires_approval`/`permission_level`，新增 `permission_tier: PermissionTier` |
| `sebastian/core/agent_loop.py` | `registry: CapabilityRegistry` → `tool_provider: ToolSpecProvider` |
| `sebastian/core/base_agent.py` | 接收 `gate: PolicyGate`，添加 `_current_task_goal`，`_stream_inner` 改用 `gate.call()` |
| `sebastian/capabilities/tools/_loader.py` | 同时扫描平铺 `.py` 和子目录包 |
| `sebastian/orchestrator/conversation.py` | 移除 `timeout`，新增 `reason` 参数，移除 `asyncio.wait_for` |
| `sebastian/orchestrator/sebas.py` | 构造器改用 `gate: PolicyGate` |
| `sebastian/gateway/app.py` | 创建 `PermissionReviewer` + `PolicyGate`，传入 Sebastian |
| `sebastian/store/models.py` | `ApprovalRecord` 新增 `reason` 字段 |
| `sebastian/gateway/routes/approvals.py` | 响应中暴露 `reason` 字段 |
| `sebastian/capabilities/README.md` | 底部添加 tools/README.md 链接 |

### 删除

- `sebastian/capabilities/tools/file_ops.py`
- `sebastian/capabilities/tools/shell.py`
- `sebastian/capabilities/tools/web_search.py`

---

## Task 1: Foundation — permissions/types.py + core/protocols.py

**Files:**
- Create: `sebastian/permissions/__init__.py`
- Create: `sebastian/permissions/types.py`
- Create: `sebastian/core/protocols.py`
- Test: `tests/unit/test_permission_types.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_permission_types.py
from __future__ import annotations


def test_permission_tier_values() -> None:
    from sebastian.permissions.types import PermissionTier

    assert PermissionTier.LOW == "low"
    assert PermissionTier.MODEL_DECIDES == "model_decides"
    assert PermissionTier.HIGH_RISK == "high_risk"


def test_tool_call_context_fields() -> None:
    from sebastian.permissions.types import ToolCallContext

    ctx = ToolCallContext(task_goal="test goal", session_id="s1", task_id="t1")
    assert ctx.task_goal == "test goal"
    assert ctx.session_id == "s1"
    assert ctx.task_id == "t1"


def test_tool_call_context_task_id_optional() -> None:
    from sebastian.permissions.types import ToolCallContext

    ctx = ToolCallContext(task_goal="goal", session_id="s1", task_id=None)
    assert ctx.task_id is None


def test_review_decision_fields() -> None:
    from sebastian.permissions.types import ReviewDecision

    d = ReviewDecision(decision="proceed", explanation="")
    assert d.decision == "proceed"
    assert d.explanation == ""

    d2 = ReviewDecision(decision="escalate", explanation="Risky operation detected.")
    assert d2.decision == "escalate"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/unit/test_permission_types.py -v
```

Expected: `ImportError: No module named 'sebastian.permissions'`

- [ ] **Step 3: Create `sebastian/permissions/__init__.py`**

```python
# sebastian/permissions/__init__.py
```

(空文件)

- [ ] **Step 4: Create `sebastian/permissions/types.py`**

```python
# sebastian/permissions/types.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class PermissionTier(StrEnum):
    LOW = "low"
    MODEL_DECIDES = "model_decides"
    HIGH_RISK = "high_risk"


@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None


@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str
```

- [ ] **Step 5: Create `sebastian/core/protocols.py`**

```python
# sebastian/core/protocols.py
from __future__ import annotations

from typing import Any, Protocol


class ApprovalManagerProtocol(Protocol):
    """Protocol satisfied by ConversationManager without explicit inheritance."""

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
    ) -> bool: ...


class ToolSpecProvider(Protocol):
    """Protocol for any object that can provide tool specs. Satisfied by both
    CapabilityRegistry (tests/legacy) and PolicyGate (production)."""

    def get_all_tool_specs(self) -> list[dict[str, Any]]: ...
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
pytest tests/unit/test_permission_types.py -v
```

Expected: 4 PASSED

- [ ] **Step 7: Commit**

```bash
git add sebastian/permissions/__init__.py sebastian/permissions/types.py sebastian/core/protocols.py tests/unit/test_permission_types.py
git commit -m "feat(permissions): add PermissionTier types and core protocols

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Update ToolSpec + @tool decorator

**Files:**
- Modify: `sebastian/core/tool.py`
- Test: `tests/unit/test_tool_decorator.py` (更新现有测试)

- [ ] **Step 1: 在现有测试文件末尾追加新测试**

```python
# 追加到 tests/unit/test_tool_decorator.py 末尾

def test_tool_default_permission_tier_is_low() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult
    from sebastian.permissions.types import PermissionTier

    tool_module._tools.clear()

    @tool(name="default_tier_tool", description="test")
    async def my_tool(x: str) -> ToolResult:
        return ToolResult(ok=True, output=x)

    spec, _ = tool_module._tools["default_tier_tool"]
    assert spec.permission_tier == PermissionTier.LOW


def test_tool_explicit_permission_tier() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult
    from sebastian.permissions.types import PermissionTier

    tool_module._tools.clear()

    @tool(
        name="risky_tool",
        description="test",
        permission_tier=PermissionTier.HIGH_RISK,
    )
    async def risky(cmd: str) -> ToolResult:
        return ToolResult(ok=True, output=cmd)

    spec, _ = tool_module._tools["risky_tool"]
    assert spec.permission_tier == PermissionTier.HIGH_RISK


def test_tool_spec_no_requires_approval_field() -> None:
    """旧字段 requires_approval / permission_level 已移除。"""
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="check_slots", description="test")
    async def check(x: str) -> ToolResult:
        return ToolResult(ok=True, output=x)

    spec, _ = tool_module._tools["check_slots"]
    assert not hasattr(spec, "requires_approval")
    assert not hasattr(spec, "permission_level")
```

- [ ] **Step 2: Run new tests — expect FAIL**

```bash
pytest tests/unit/test_tool_decorator.py -v
```

Expected: 最后 3 个新测试 FAIL（`requires_approval` 字段还存在，`permission_tier` 不存在）

- [ ] **Step 3: 替换 `sebastian/core/tool.py`**

```python
# sebastian/core/tool.py
from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, get_type_hints

from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[ToolResult]]

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolSpec:
    """Specification and metadata for a registered tool."""

    __slots__ = ("name", "description", "parameters", "permission_tier")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        permission_tier: PermissionTier = PermissionTier.LOW,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.permission_tier = permission_tier


# Module-level registry: tool name → (spec, async callable)
_tools: dict[str, tuple[ToolSpec, ToolFn]] = {}


def _infer_json_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Infer JSON schema from function signature."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(
            fn,
            localns={
                "int": int,
                "str": str,
                "float": float,
                "bool": bool,
                "ToolResult": ToolResult,
            },
        )
    except Exception as e:
        logger.debug(
            "get_type_hints failed for %s: %s, falling back to raw annotations",
            fn.__name__,
            e,
        )
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        ann = hints.get(param_name, param.annotation)
        json_type = _TYPE_MAP.get(ann, "string")
        properties[param_name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": properties, "required": required}


def tool(
    name: str,
    description: str,
    permission_tier: PermissionTier = PermissionTier.LOW,
) -> Callable[[ToolFn], ToolFn]:
    """Decorator that registers an async function as a callable tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=_infer_json_schema(fn),
            permission_tier=permission_tier,
        )

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
            return await fn(*args, **kwargs)

        _tools[name] = (spec, wrapper)
        logger.debug("Tool registered: %s", name)
        return wrapper

    return decorator


def get_tool(name: str) -> tuple[ToolSpec, ToolFn] | None:
    """Retrieve a registered tool by name."""
    return _tools.get(name)


def list_tool_specs() -> list[ToolSpec]:
    """List all registered tool specifications."""
    return [spec for spec, _ in _tools.values()]


async def call_tool(name: str, **kwargs: Any) -> ToolResult:
    """Execute a tool by name with the given arguments."""
    entry = _tools.get(name)
    if entry is None:
        return ToolResult(ok=False, error=f"Tool not found: {name}")
    _, fn = entry
    return await fn(**kwargs)
```

- [ ] **Step 4: Run all tool tests — expect PASS**

```bash
pytest tests/unit/test_tool_decorator.py -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/tool.py tests/unit/test_tool_decorator.py
git commit -m "feat(core): replace requires_approval/permission_level with PermissionTier

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Tool 目录结构迁移

**Files:**
- Modify: `sebastian/capabilities/tools/_loader.py`
- Create: `sebastian/capabilities/tools/file_ops/__init__.py`
- Create: `sebastian/capabilities/tools/shell/__init__.py`
- Create: `sebastian/capabilities/tools/web_search/__init__.py`
- Delete: `sebastian/capabilities/tools/file_ops.py`
- Delete: `sebastian/capabilities/tools/shell.py`
- Delete: `sebastian/capabilities/tools/web_search.py`

- [ ] **Step 1: 更新 `_loader.py`（先不删旧文件，验证双模式）**

```python
# sebastian/capabilities/tools/_loader.py
from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_tools() -> None:
    """Scan capabilities/tools/ and import:
    1. Flat .py modules (non-underscore-prefixed)
    2. Subdirectory packages containing __init__.py (non-underscore-prefixed)

    Each module's @tool decorators self-register into core.tool._tools.
    """
    tools_dir = Path(__file__).parent

    # 1. Flat .py files
    for path in sorted(tools_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module_name = f"sebastian.capabilities.tools.{path.stem}"
        try:
            importlib.import_module(module_name)
            logger.info("Loaded tool module: %s", path.stem)
        except Exception:
            logger.exception("Failed to load tool module: %s", path.stem)

    # 2. Subdirectory packages
    for entry in sorted(tools_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not (entry / "__init__.py").exists():
            continue
        module_name = f"sebastian.capabilities.tools.{entry.name}"
        try:
            importlib.import_module(module_name)
            logger.info("Loaded tool package: %s", entry.name)
        except Exception:
            logger.exception("Failed to load tool package: %s", entry.name)
```

- [ ] **Step 2: 创建 `sebastian/capabilities/tools/file_ops/__init__.py`**

```python
# sebastian/capabilities/tools/file_ops/__init__.py
# mypy: disable-error-code=import-untyped
from __future__ import annotations

from pathlib import Path

import aiofiles

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="file_read",
    description="Read the full contents of a file at the given path.",
    permission_tier=PermissionTier.LOW,
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
    permission_tier=PermissionTier.MODEL_DECIDES,
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

- [ ] **Step 3: 创建 `sebastian/capabilities/tools/shell/__init__.py`**

```python
# sebastian/capabilities/tools/shell/__init__.py
from __future__ import annotations

import asyncio

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="shell",
    description=(
        "Execute a shell command. Returns stdout, stderr, and return code. "
        "Use reason to explain why this specific command is safe for the current task."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
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

- [ ] **Step 4: 创建 `sebastian/capabilities/tools/web_search/__init__.py`**

```python
# sebastian/capabilities/tools/web_search/__init__.py
from __future__ import annotations

from typing import Any

import httpx

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="web_search",
    description=(
        "Search the web using DuckDuckGo and return a list of results "
        "with titles and snippets."
    ),
    permission_tier=PermissionTier.LOW,
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

- [ ] **Step 5: 验证双模式加载——先确认两套工具都能注册（旧文件还在）**

```bash
python -c "
from sebastian.core import tool as t
t._tools.clear()
from sebastian.capabilities.tools._loader import load_tools
load_tools()
print('Registered tools:', list(t._tools.keys()))
"
```

注意此时可能会报 `AlreadyRegistered` 或重复注册，因为旧 .py 文件和新目录都会加载。没有报错的话说明双模式正常工作。

- [ ] **Step 6: 删除旧的平铺工具文件**

```bash
rm sebastian/capabilities/tools/file_ops.py
rm sebastian/capabilities/tools/shell.py
rm sebastian/capabilities/tools/web_search.py
```

- [ ] **Step 7: 验证只有新目录版本被加载**

```bash
python -c "
from sebastian.core import tool as t
t._tools.clear()
from sebastian.capabilities.tools._loader import load_tools
load_tools()
tools = list(t._tools.keys())
print('Registered tools:', tools)
assert 'file_read' in tools
assert 'file_write' in tools
assert 'shell' in tools
assert 'web_search' in tools
print('OK')
"
```

Expected: `Registered tools: ['file_read', 'file_write', 'shell', 'web_search']` 且 `OK`

- [ ] **Step 8: 运行现有工具相关测试确保不退化**

```bash
pytest tests/unit/test_tool_decorator.py tests/unit/test_capability_registry.py -v
```

Expected: 全部 PASS

- [ ] **Step 9: Commit**

```bash
git add sebastian/capabilities/tools/_loader.py \
        sebastian/capabilities/tools/file_ops/ \
        sebastian/capabilities/tools/shell/ \
        sebastian/capabilities/tools/web_search/
git commit -m "refactor(tools): 迁移至目录-per-tool 结构，_loader 支持子目录包

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: PermissionReviewer

**Files:**
- Create: `sebastian/permissions/reviewer.py`
- Test: `tests/unit/test_permission_reviewer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_permission_reviewer.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_reviewer_returns_proceed_on_safe_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer
    from sebastian.permissions.types import ReviewDecision

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"decision": "proceed", "explanation": ""}')]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "cat /etc/hosts"},
        reason="Reading hosts file to debug DNS issue",
        task_goal="Debug network connectivity",
    )

    assert decision.decision == "proceed"
    assert decision.explanation == ""


@pytest.mark.asyncio
async def test_reviewer_returns_escalate_on_risky_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(
            text='{"decision": "escalate", "explanation": "此命令将永久删除文件，请确认。"}'
        )
    ]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "rm -rf /tmp/old_data"},
        reason="Cleaning up temp files",
        task_goal="Summarize today's news",
    )

    assert decision.decision == "escalate"
    assert "删除" in decision.explanation


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_api_error() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API error"))

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "ls"},
        reason="List files",
        task_goal="Find config file",
    )

    assert decision.decision == "escalate"
    assert decision.explanation != ""


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_invalid_json() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="not valid json")]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="file_write",
        tool_input={"path": "/tmp/out.txt", "content": "data"},
        reason="Write output",
        task_goal="Generate report",
    )

    assert decision.decision == "escalate"


@pytest.mark.asyncio
async def test_reviewer_passes_context_to_llm() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"decision": "proceed", "explanation": ""}')]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    await reviewer.review(
        tool_name="shell",
        tool_input={"command": "pwd"},
        reason="Check working directory",
        task_goal="Debug file path issue",
    )

    call_kwargs = mock_client.messages.create.call_args
    user_content = call_kwargs.kwargs["messages"][0]["content"]
    assert "shell" in user_content
    assert "pwd" in user_content
    assert "Check working directory" in user_content
    assert "Debug file path issue" in user_content
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/unit/test_permission_reviewer.py -v
```

Expected: `ImportError: cannot import name 'PermissionReviewer'`

- [ ] **Step 3: 创建 `sebastian/permissions/reviewer.py`**

```python
# sebastian/permissions/reviewer.py
from __future__ import annotations

import json
import logging
from typing import Any

from sebastian.permissions.types import ReviewDecision

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a security reviewer for an AI assistant system.
Your job: decide whether a tool call should proceed directly or require user approval.

Rules:
- PROCEED if: the action is reversible, read-only, or clearly aligned with the stated task goal
- ESCALATE if: the action is destructive, irreversible, accesses sensitive data,
  or the stated reason does not match the task goal
- When in doubt, ESCALATE

Respond ONLY in valid JSON:
{"decision": "proceed" | "escalate", "explanation": "..."}
explanation must be in the user's language, written for a non-technical user.
When decision is "proceed", explanation is an empty string.\
"""


class PermissionReviewer:
    """Stateless LLM reviewer for MODEL_DECIDES tool calls.

    Each review is a single API call with no session state.
    Defaults to escalate on any failure (conservative).
    """

    def __init__(self, client: Any, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client = client
        self._model = model

    async def review(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        task_goal: str,
    ) -> ReviewDecision:
        """Return a proceed/escalate decision for the given tool call."""
        user_content = (
            f"Task goal: {task_goal}\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
            f"Model's reason: {reason}"
        )
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = message.content[0].text.strip()
            data = json.loads(raw)
            decision = data.get("decision", "escalate")
            if decision not in ("proceed", "escalate"):
                decision = "escalate"
            explanation = data.get("explanation", "")
            return ReviewDecision(decision=decision, explanation=explanation)
        except Exception:
            logger.exception("PermissionReviewer failed, defaulting to escalate")
            return ReviewDecision(
                decision="escalate",
                explanation="Permission review failed; manual approval required.",
            )
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/unit/test_permission_reviewer.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add sebastian/permissions/reviewer.py tests/unit/test_permission_reviewer.py
git commit -m "feat(permissions): add PermissionReviewer stateless LLM reviewer

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: PolicyGate

**Files:**
- Create: `sebastian/permissions/gate.py`
- Test: `tests/unit/test_policy_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_policy_gate.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier, ReviewDecision, ToolCallContext


def _make_context(task_goal: str = "test goal") -> ToolCallContext:
    return ToolCallContext(task_goal=task_goal, session_id="s1", task_id="t1")


def _make_gate(
    *,
    tier: PermissionTier = PermissionTier.LOW,
    review_decision: str = "proceed",
    review_explanation: str = "",
    approval_result: bool = True,
) -> "PolicyGate":  # noqa: F821
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_all_tool_specs.return_value = [
        {"name": "test_tool", "description": "test", "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}}
    ]
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="done"))

    # Patch get_tool to return a spec with the given tier
    spec = MagicMock()
    spec.permission_tier = tier

    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=ReviewDecision(decision=review_decision, explanation=review_explanation)
    )

    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=approval_result)

    gate = PolicyGate(
        registry=registry,
        reviewer=reviewer,
        approval_manager=approval_manager,
    )
    # Patch get_tool at module level
    gate._get_tool_tier = lambda name: tier  # type: ignore[attr-defined]
    return gate


@pytest.mark.asyncio
async def test_low_tier_bypasses_reviewer_and_approval() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="result"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": "/tmp/f.txt"}, _make_context())

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()
    registry.call.assert_awaited_once_with("file_read", path="/tmp/f.txt")


@pytest.mark.asyncio
async def test_model_decides_proceed_no_approval() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(return_value=ReviewDecision(decision="proceed", explanation=""))
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "shell",
            {"command": "cat /tmp/a.txt", "reason": "Reading temp file for task"},
            _make_context("Read temp file"),
        )

    assert result.ok
    reviewer.review.assert_awaited_once()
    approval_manager.request_approval.assert_not_called()
    # reason must not reach registry
    registry.call.assert_awaited_once_with("shell", command="cat /tmp/a.txt")


@pytest.mark.asyncio
async def test_model_decides_escalate_user_grants() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="deleted"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=ReviewDecision(decision="escalate", explanation="将删除文件，请确认。")
    )
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "shell",
            {"command": "rm /tmp/old.log", "reason": "Remove stale log"},
            _make_context("Clean up logs"),
        )

    assert result.ok
    approval_manager.request_approval.assert_awaited_once()
    call_kwargs = approval_manager.request_approval.call_args.kwargs
    assert call_kwargs["reason"] == "将删除文件，请确认。"


@pytest.mark.asyncio
async def test_model_decides_escalate_user_denies() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="done"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        return_value=ReviewDecision(decision="escalate", explanation="Risky.")
    )
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=False)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "shell",
            {"command": "rm /etc/hosts", "reason": "cleanup"},
            _make_context(),
        )

    assert not result.ok
    assert "denied" in (result.error or "").lower()
    registry.call.assert_not_called()


@pytest.mark.asyncio
async def test_high_risk_always_requests_approval() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="done"))
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.HIGH_RISK
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("delete_file", {"path": "/data/db"}, _make_context())

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_high_risk_denied_returns_error() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=False)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.HIGH_RISK
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("delete_file", {"path": "/data"}, _make_context())

    assert not result.ok
    registry.call.assert_not_called()


def test_get_all_tool_specs_injects_reason_for_model_decides() -> None:
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_all_tool_specs.return_value = [
        {
            "name": "shell",
            "description": "Run shell command",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "file_read",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]

    gate = PolicyGate(registry=registry, reviewer=MagicMock(), approval_manager=MagicMock())

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        def _side_effect(name: str):
            spec = MagicMock()
            spec.permission_tier = (
                PermissionTier.MODEL_DECIDES if name == "shell" else PermissionTier.LOW
            )
            return (spec, MagicMock())

        mock_get_tool.side_effect = _side_effect
        specs = gate.get_all_tool_specs()

    shell_spec = next(s for s in specs if s["name"] == "shell")
    file_spec = next(s for s in specs if s["name"] == "file_read")

    assert "reason" in shell_spec["input_schema"]["properties"]
    assert "reason" in shell_spec["input_schema"]["required"]
    assert "reason" not in file_spec["input_schema"]["properties"]


def test_get_all_tool_specs_unknown_tool_defaults_to_model_decides() -> None:
    """MCP tools not in native registry default to MODEL_DECIDES."""
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.get_all_tool_specs.return_value = [
        {
            "name": "mcp_tool",
            "description": "An MCP tool",
            "input_schema": {
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
        }
    ]

    gate = PolicyGate(registry=registry, reviewer=MagicMock(), approval_manager=MagicMock())

    with patch("sebastian.permissions.gate.get_tool", return_value=None):
        specs = gate.get_all_tool_specs()

    mcp_spec = specs[0]
    assert "reason" in mcp_spec["input_schema"]["properties"]
    assert "reason" in mcp_spec["input_schema"]["required"]
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/unit/test_policy_gate.py -v
```

Expected: `ImportError: cannot import name 'PolicyGate'`

- [ ] **Step 3: 创建 `sebastian/permissions/gate.py`**

```python
# sebastian/permissions/gate.py
from __future__ import annotations

import copy
import logging
import uuid
from typing import Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.protocols import ApprovalManagerProtocol
from sebastian.core.tool import get_tool
from sebastian.core.types import ToolResult
from sebastian.permissions.reviewer import PermissionReviewer
from sebastian.permissions.types import PermissionTier, ToolCallContext

logger = logging.getLogger(__name__)

_REASON_SCHEMA: dict[str, str] = {
    "type": "string",
    "description": (
        "Explain why you need to call this tool and confirm it aligns "
        "with the current task goal."
    ),
}


class PolicyGate:
    """Permission-enforcing proxy around CapabilityRegistry.

    All agents access tools through this gate. CapabilityRegistry remains
    unaware of permission logic and can be tested independently.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        reviewer: PermissionReviewer,
        approval_manager: ApprovalManagerProtocol,
    ) -> None:
        self._registry = registry
        self._reviewer = reviewer
        self._approval_manager = approval_manager

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return tool specs in Anthropic API format.

        For MODEL_DECIDES tools (including unrecognised MCP tools), inject
        a required `reason` field so the LLM must state its intent.
        """
        specs: list[dict[str, Any]] = []
        for spec_dict in self._registry.get_all_tool_specs():
            tool_name = spec_dict["name"]
            native = get_tool(tool_name)
            tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

            if tier == PermissionTier.MODEL_DECIDES:
                spec_dict = copy.deepcopy(spec_dict)
                schema = spec_dict.setdefault("input_schema", {})
                props = schema.setdefault("properties", {})
                required: list[str] = schema.setdefault("required", [])
                props["reason"] = _REASON_SCHEMA
                if "reason" not in required:
                    required.append("reason")

            specs.append(spec_dict)
        return specs

    async def call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """Execute a tool after enforcing its permission tier."""
        native = get_tool(tool_name)
        tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

        if tier == PermissionTier.LOW:
            return await self._registry.call(tool_name, **inputs)

        if tier == PermissionTier.MODEL_DECIDES:
            reason = inputs.pop("reason", "")
            decision = await self._reviewer.review(
                tool_name=tool_name,
                tool_input=inputs,
                reason=reason,
                task_goal=context.task_goal,
            )
            if decision.decision == "proceed":
                return await self._registry.call(tool_name, **inputs)
            granted = await self._approval_manager.request_approval(
                approval_id=uuid.uuid4().hex,
                task_id=context.task_id or "",
                tool_name=tool_name,
                tool_input=inputs,
                reason=decision.explanation,
            )
            if granted:
                return await self._registry.call(tool_name, **inputs)
            return ToolResult(ok=False, error="User denied approval for this tool call.")

        # HIGH_RISK — always request approval regardless of model intent
        granted = await self._approval_manager.request_approval(
            approval_id=uuid.uuid4().hex,
            task_id=context.task_id or "",
            tool_name=tool_name,
            tool_input=inputs,
            reason=f"High-risk tool '{tool_name}' requires explicit user approval.",
        )
        if granted:
            return await self._registry.call(tool_name, **inputs)
        return ToolResult(ok=False, error="User denied approval for this tool call.")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/unit/test_policy_gate.py -v
```

Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add sebastian/permissions/gate.py tests/unit/test_policy_gate.py
git commit -m "feat(permissions): add PolicyGate permission-enforcing proxy

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 更新 AgentLoop + BaseAgent

**Files:**
- Modify: `sebastian/core/agent_loop.py`
- Modify: `sebastian/core/base_agent.py`

- [ ] **Step 1: 更新 `sebastian/core/agent_loop.py`**

将 `registry: CapabilityRegistry` 改为 `tool_provider: ToolSpecProvider`，只涉及构造器和 `get_all_tool_specs()` 调用：

```python
# sebastian/core/agent_loop.py — 修改 __init__ 签名
# 找到以下部分：
#   from sebastian.capabilities.registry import CapabilityRegistry
# 替换为：
#   from sebastian.core.protocols import ToolSpecProvider
#
# 找到构造器：
#   def __init__(self, client, registry: CapabilityRegistry, model, max_tokens):
#       self._registry = registry
# 替换为：
#   def __init__(self, client, tool_provider: ToolSpecProvider, model, max_tokens):
#       self._registry = tool_provider
```

完整更新后的 `__init__` 和导入部分如下（其余方法不变）：

```python
# 在 agent_loop.py 顶部，将
#   from sebastian.capabilities.registry import CapabilityRegistry
# 改为
from sebastian.core.protocols import ToolSpecProvider

# 将构造器改为：
    def __init__(
        self,
        client: Any,
        tool_provider: ToolSpecProvider,
        model: str = "claude-opus-4-6",
        max_tokens: int | None = None,
    ) -> None:
        self._client = client
        self._registry = tool_provider   # 内部变量名保持不变，调用的是 get_all_tool_specs()
        self._model = model
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            from sebastian.config import settings
            self._max_tokens = settings.llm_max_tokens
```

- [ ] **Step 2: 更新 `sebastian/core/base_agent.py`**

关键改动四处：
1. 导入 `PolicyGate` 和 `ToolCallContext`
2. 构造器接收 `gate: PolicyGate` 替代 `registry: CapabilityRegistry`
3. 添加 `_current_task_goal: str` 实例变量
4. `run_streaming()` 设置 `_current_task_goal`；`_stream_inner()` 改用 `gate.call()`

```python
# sebastian/core/base_agent.py

# 1. 修改导入部分 — 移除 CapabilityRegistry，新增 PolicyGate 和 ToolCallContext：
# 移除：from sebastian.capabilities.registry import CapabilityRegistry
# 新增：
from sebastian.permissions.gate import PolicyGate
from sebastian.permissions.types import ToolCallContext

# 2. 修改构造器签名：
    def __init__(
        self,
        gate: PolicyGate,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        model: str | None = None,
    ) -> None:
        self._gate = gate
        self._session_store = session_store
        self._event_bus = event_bus
        self._episodic = EpisodicMemory(session_store)
        self.working_memory = WorkingMemory()
        self._active_stream: asyncio.Task[str] | None = None
        self._current_task_goal: str = ""

        from sebastian.config import settings

        resolved_model = model or settings.sebastian_model
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._loop = AgentLoop(self._client, gate, resolved_model)

# 3. 在 run_streaming() 入口（append user message 之前）设置 task_goal：
        self._current_task_goal = user_message

# 4. 在 _stream_inner() 中，将工具执行部分替换：
# 找到：
#   result = await self._registry.call(event.name, **event.inputs)
# 替换为：
                    context = ToolCallContext(
                        task_goal=self._current_task_goal,
                        session_id=session_id,
                        task_id=task_id,
                    )
                    result = await self._gate.call(event.name, event.inputs, context)
```

- [ ] **Step 3: 运行现有 BaseAgent 和 AgentLoop 相关测试**

```bash
pytest tests/unit/test_agent_loop.py tests/unit/test_base_agent.py tests/unit/test_base_agent_provider.py -v
```

如果测试构造 `BaseAgent` 或 `AgentLoop` 时传入了旧参数名，需逐一修正（将 `registry=...` 改为 `gate=...`，将 `registry` 传参改为 `tool_provider`）。

- [ ] **Step 4: 运行完整测试套件确认无退化**

```bash
pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: 全部 PASS（或仅有与 sebastain 实例化相关的少量 fail，由下一步修复）

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/agent_loop.py sebastian/core/base_agent.py
git commit -m "refactor(core): AgentLoop 和 BaseAgent 改用 PolicyGate/ToolSpecProvider

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 更新 ConversationManager + ApprovalRecord

**Files:**
- Modify: `sebastian/orchestrator/conversation.py`
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/gateway/routes/approvals.py`

- [ ] **Step 1: 更新 `sebastian/orchestrator/conversation.py`**

移除 `timeout` 参数，新增 `reason` 参数，移除 `asyncio.wait_for`：

```python
# sebastian/orchestrator/conversation.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)


class ConversationManager:
    """Conversation plane: manages pending approval futures.

    Approval requests suspend the awaiting coroutine indefinitely until
    the user grants or denies via the REST API.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
    ) -> bool:
        """Suspend execution until the user approves or denies. No timeout."""
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
                "reason": reason,
            },
        ))

        return await future

    async def resolve_approval(self, approval_id: str, granted: bool) -> None:
        """Called by the approval API endpoint to resolve a pending request."""
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            return
        future.set_result(granted)
        event_type = (
            EventType.USER_APPROVAL_GRANTED if granted else EventType.USER_APPROVAL_DENIED
        )
        await self._bus.publish(Event(
            type=event_type,
            data={"approval_id": approval_id, "granted": granted},
        ))
```

- [ ] **Step 2: 更新 `sebastian/store/models.py` — 新增 `reason` 字段**

在 `ApprovalRecord` 类中添加 `reason` 字段：

```python
# 在 ApprovalRecord 类中，在 created_at 字段之前插入：
    reason: Mapped[str] = mapped_column(String, default="")
```

完整 `ApprovalRecord` 类：

```python
class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True, default="")
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 3: 处理现有数据库的 schema 迁移**

对于**全新安装**，`init_db()` 会自动创建含 `reason` 列的表。

对于**已有数据库**（开发环境），手动执行：

```bash
python -c "
import asyncio
from sebastian.store.database import get_engine
async def migrate():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            \"ALTER TABLE approvals ADD COLUMN reason TEXT NOT NULL DEFAULT ''\"
        )
        print('Migration done')
asyncio.run(migrate())
"
```

如果报 `duplicate column name`，说明已有该列，可忽略。

- [ ] **Step 4: 更新 `sebastian/gateway/routes/approvals.py` — 暴露 reason 字段**

在 `list_approvals` 的返回列表里补充 `reason`：

```python
# 在 list_approvals 的 return 里，每条 approval 字典新增：
                "reason": r.reason,
```

在 `_resolve` 函数更新 DB 记录时，approval route 的 grant/deny 不需要改变（resolve 时 DB 记录已有 reason）。

完整 `list_approvals` 返回结构：

```python
    return {
        "approvals": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "taskId": r.task_id,
                "session_id": r.session_id,
                "tool_name": r.tool_name,
                "tool_input": r.tool_input,
                "reason": r.reason,
                "description": _approval_description(r.tool_name, r.tool_input),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "requestedAt": r.created_at.isoformat(),
            }
            for r in records
        ]
    }
```

- [ ] **Step 5: 运行 approval 相关测试**

```bash
pytest tests/integration/test_gateway_approvals.py -v
```

Expected: PASS（如果测试构造 `ConversationManager` 时调用了 `request_approval(timeout=...)`，去掉 `timeout` 参数）

- [ ] **Step 6: Commit**

```bash
git add sebastian/orchestrator/conversation.py sebastian/store/models.py sebastian/gateway/routes/approvals.py
git commit -m "feat(approval): 移除超时，新增 reason 字段，ConversationManager 无限等待

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 接线 — gateway/app.py + sebas.py

**Files:**
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: 更新 `sebastian/orchestrator/sebas.py`**

构造器改用 `gate: PolicyGate`：

```python
# sebastian/orchestrator/sebas.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Session, Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.permissions.gate import PolicyGate
from sebastian.protocol.events.bus import EventBus
from sebastian.protocol.events.types import EventType
from sebastian.store.index_store import IndexStore
from sebastian.store.session_store import SessionStore

# BaseAgent 导入保留
from sebastian.core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

SEBASTIAN_SYSTEM_PROMPT = """You are Sebastian — an elegant, capable personal AI butler.
Your purpose: receive instructions, plan effectively, and execute precisely.
You have access to tools. Use them to fulfill requests completely.
For complex multi-step tasks, break them down and execute step by step.
When you encounter a decision that requires the user's input, ask clearly and concisely.
You never fabricate results — if a tool fails, say so and suggest alternatives."""


class Sebastian(BaseAgent):
    name = "sebastian"
    system_prompt = SEBASTIAN_SYSTEM_PROMPT

    def __init__(
        self,
        gate: PolicyGate,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
    ) -> None:
        super().__init__(gate, session_store, event_bus=event_bus)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation

    # 以下方法保持不变（chat, get_or_create_session, intervene, submit_background_task）
```

- [ ] **Step 2: 更新 `sebastian/gateway/app.py` — 创建 PolicyGate 并接线**

在 `lifespan` 函数里，在创建 `sebastian_agent` 之前，新增 `PermissionReviewer` 和 `PolicyGate`：

```python
# 在 lifespan 里，在 sebastian_agent = Sebastian(...) 之前插入：

    import anthropic as _anthropic
    from sebastian.config import settings as _settings
    from sebastian.permissions.gate import PolicyGate
    from sebastian.permissions.reviewer import PermissionReviewer

    _reviewer_client = _anthropic.AsyncAnthropic(api_key=_settings.anthropic_api_key)
    reviewer = PermissionReviewer(client=_reviewer_client)
    policy_gate = PolicyGate(
        registry=registry,
        reviewer=reviewer,
        approval_manager=conversation,
    )

# 然后将 Sebastian 的构造调用改为：
    sebastian_agent = Sebastian(
        gate=policy_gate,
        session_store=session_store,
        index_store=index_store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
    )
```

- [ ] **Step 3: 运行 Sebastian 相关单元测试**

```bash
pytest tests/unit/test_sebas.py -v
```

修复因构造器签名变更导致的测试失败：将 `Sebastian(registry=..., ...)` 改为 `Sebastian(gate=..., ...)`，`gate` 可用 `MagicMock()` 替代。

- [ ] **Step 4: 运行完整单元测试**

```bash
pytest tests/unit/ -v --tb=short 2>&1 | tail -40
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/orchestrator/sebas.py sebastian/gateway/app.py
git commit -m "feat(gateway): 接入 PolicyGate，Sebastian 改用权限代理层

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 集成测试

**Files:**
- Create: `tests/integration/test_permission_flow.py`

- [ ] **Step 1: 创建集成测试**

```python
# tests/integration/test_permission_flow.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier, ReviewDecision, ToolCallContext


@pytest.mark.asyncio
async def test_policy_gate_low_tier_end_to_end() -> None:
    """LOW tier tool executes without touching reviewer or approval."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.permissions.gate import PolicyGate

    registry = CapabilityRegistry()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output={"content": "hello"}))

    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        spec = MagicMock()
        spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (spec, MagicMock())

        result = await gate.call(
            "file_read",
            {"path": "/tmp/test.txt"},
            ToolCallContext(task_goal="Read file", session_id="s1", task_id=None),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()


@pytest.mark.asyncio
async def test_conversation_manager_approval_flow() -> None:
    """ConversationManager suspends and resumes on resolve."""
    import asyncio
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.protocol.events.bus import EventBus

    bus = EventBus()
    manager = ConversationManager(event_bus=bus)

    approval_task = asyncio.create_task(
        manager.request_approval(
            approval_id="test_001",
            task_id="t1",
            tool_name="shell",
            tool_input={"command": "rm /tmp/x"},
            reason="Cleanup temp file",
        )
    )

    # 让协程挂起
    await asyncio.sleep(0)
    assert not approval_task.done()

    # 用户 grant
    await manager.resolve_approval("test_001", granted=True)
    result = await approval_task
    assert result is True


@pytest.mark.asyncio
async def test_conversation_manager_deny_flow() -> None:
    """ConversationManager returns False when denied."""
    import asyncio
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.protocol.events.bus import EventBus

    bus = EventBus()
    manager = ConversationManager(event_bus=bus)

    approval_task = asyncio.create_task(
        manager.request_approval(
            approval_id="test_002",
            task_id="t1",
            tool_name="delete_file",
            tool_input={"path": "/data"},
            reason="High-risk tool requires approval.",
        )
    )

    await asyncio.sleep(0)
    await manager.resolve_approval("test_002", granted=False)
    result = await approval_task
    assert result is False


@pytest.mark.asyncio
async def test_policy_gate_model_decides_full_escalate_grant_flow() -> None:
    """Full MODEL_DECIDES flow: reviewer escalates → approval granted → tool runs."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.permissions.gate import PolicyGate
    from sebastian.permissions.reviewer import PermissionReviewer
    from sebastian.protocol.events.bus import EventBus
    import asyncio

    registry = CapabilityRegistry()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output={"stdout": "done"}))

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(text='{"decision": "escalate", "explanation": "删除操作需要确认"}')
    ]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    bus = EventBus()
    conversation = ConversationManager(event_bus=bus)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=conversation)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        spec = MagicMock()
        spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (spec, MagicMock())

        call_task = asyncio.create_task(
            gate.call(
                "shell",
                {"command": "rm /tmp/old.log", "reason": "Remove stale log file"},
                ToolCallContext(task_goal="Clean up logs", session_id="s1", task_id="t1"),
            )
        )

        # 等待 approval 请求产生
        await asyncio.sleep(0)
        # 找出 pending 的 approval_id
        assert len(conversation._pending) == 1
        approval_id = next(iter(conversation._pending))

        # 用户批准
        await conversation.resolve_approval(approval_id, granted=True)
        result = await call_task

    assert result.ok
    registry.call.assert_awaited_once_with("shell", command="rm /tmp/old.log")
```

- [ ] **Step 2: 运行集成测试**

```bash
pytest tests/integration/test_permission_flow.py -v
```

Expected: 4 PASSED

- [ ] **Step 3: 运行完整测试套件**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_permission_flow.py
git commit -m "test(permissions): 添加权限系统集成测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: 文档化

**Files:**
- Create: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/capabilities/README.md`

- [ ] **Step 1: 创建 `sebastian/capabilities/tools/README.md`**

写入以下内容：

````markdown
# Tool 系统完整指南

## 概述

Tool 是 Sebastian 中 Agent 调用外部能力的核心扩展机制。每个 tool 是一个被 `@tool` 装饰器注册的异步函数，系统启动时由 `_loader.py` 自动扫描并注册到全局注册表，无需手动配置。

所有 tool call 经过 `PolicyGate` 执行，根据工具的 `permission_tier` 元数据决定是直接执行、交给 PermissionReviewer 审查，还是强制向用户发起审批。

---

## ToolResult

所有 tool 函数必须返回 `ToolResult`：

```python
from sebastian.core.types import ToolResult

ToolResult(ok=True, output={"key": "value"})   # 成功
ToolResult(ok=False, error="错误描述")          # 失败
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 执行是否成功 |
| `output` | `Any` | 成功时的返回数据（任意可序列化结构） |
| `error` | `str \| None` | 失败时的错误描述 |

---

## @tool 装饰器参数

```python
from sebastian.core.tool import tool
from sebastian.permissions.types import PermissionTier

@tool(
    name="my_tool",          # 工具名，全局唯一，LLM 调用时使用
    description="工具说明",   # 清晰描述用途，LLM 根据此决定何时调用
    permission_tier=PermissionTier.LOW,  # 权限档位（见下方）
)
async def my_tool(param: str) -> ToolResult:
    ...
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 全局唯一工具名 |
| `description` | `str` | 必填 | 供 LLM 理解工具用途 |
| `permission_tier` | `PermissionTier` | `PermissionTier.LOW` | 执行前的权限级别 |

---

## 三档权限详解

### Tier 1 — LOW（直接执行）

```python
permission_tier=PermissionTier.LOW
```

无任何拦截，直接执行。适用于只读、无副作用的操作。

**适用场景：** 读取文件内容、搜索网页、查询只读状态

**示例：**
```python
@tool(name="file_read", description="读取文件内容", permission_tier=PermissionTier.LOW)
async def file_read(path: str) -> ToolResult:
    ...
```

---

### Tier 2 — MODEL_DECIDES（PermissionReviewer 审查）

```python
permission_tier=PermissionTier.MODEL_DECIDES
```

系统自动在工具 schema 中注入 `reason: string` 必填字段，LLM 调用时必须填写原因。系统将工具调用 + reason + 当前任务目标传给 PermissionReviewer（无状态 LLM 审查器），由它决定：
- **proceed**：直接执行，无需用户介入
- **escalate**：向用户发起审批请求，携带审查原因说明

> **注意：** 工具函数本身**不需要**定义 `reason` 参数，系统自动注入和提取，函数签名里写了反而会出错。

**适用场景：** 写入文件、执行 shell 命令、发送消息等有副作用但结果可能合理的操作

**示例：**
```python
@tool(
    name="file_write",
    description="写入文件内容",
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def file_write(path: str, content: str) -> ToolResult:
    # 函数签名里不要写 reason 参数
    ...
```

---

### Tier 3 — HIGH_RISK（必定用户审批）

```python
permission_tier=PermissionTier.HIGH_RISK
```

无论模型意图如何，每次调用必定向用户发起审批。用户批准后执行，拒绝后返回 `ToolResult(ok=False, error="User denied approval")`。

**适用场景：** 删除文件/目录、格式化磁盘、访问密钥/密码、终止进程等不可逆操作

**示例：**
```python
@tool(
    name="delete_file",
    description="永久删除指定路径的文件或目录",
    permission_tier=PermissionTier.HIGH_RISK,
)
async def delete_file(path: str) -> ToolResult:
    ...
```

---

## 创建新 Tool 的完整步骤

### 1. 新建目录

在 `sebastian/capabilities/tools/` 下创建以 tool 名命名的目录：

```bash
mkdir sebastian/capabilities/tools/my_tool
```

### 2. 创建 `__init__.py`

```python
# sebastian/capabilities/tools/my_tool/__init__.py
from __future__ import annotations

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="my_tool",
    description="工具的清晰描述，告诉 LLM 它能做什么",
    permission_tier=PermissionTier.LOW,  # 根据风险选择档位
)
async def my_tool(param: str) -> ToolResult:
    try:
        result = do_something(param)
        return ToolResult(ok=True, output={"result": result})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

### 3. 多文件结构（可选）

如果工具逻辑复杂，可拆分辅助模块：

```
tools/my_tool/
    __init__.py    # @tool 装饰器和入口函数
    _helpers.py    # 辅助函数（_ 开头，_loader 不直接扫描）
    _models.py     # 数据模型
```

`__init__.py` 中 import 辅助模块：

```python
from sebastian.capabilities.tools.my_tool._helpers import process_data
```

### 4. 重启服务

无需任何其他配置，重启后 `_loader.py` 自动扫描并注册：

```bash
uvicorn sebastian.gateway.app:app --reload
```

---

## 类型注解规范

函数参数支持以下类型（自动映射到 JSON Schema）：

| Python 类型 | JSON Schema 类型 |
|---|---|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| 其他 | `string`（fallback） |

所有参数必须有类型注解，返回值固定为 `-> ToolResult`。

---

## 常见错误

| 错误 | 原因 | 修复 |
|---|---|---|
| `reason` 参数出现在函数签名里 | `MODEL_DECIDES` 工具的 `reason` 由系统自动注入/提取，工具函数不需要它 | 从函数签名中删除 `reason` 参数 |
| 工具注册后找不到 | 目录名以 `_` 开头，_loader 会跳过 | 重命名目录，去掉 `_` 前缀 |
| 工具函数不是 `async` | `_loader` 导入成功但调用时出错 | 将函数改为 `async def` |
| 同名工具覆盖 | 两个工具使用相同的 `name` | 确保 `@tool(name=...)` 全局唯一 |
| 类型推断失败 | 使用了不支持的参数类型 | 改用支持的类型，或 fallback 为 `str` |

---

## MCP 工具的权限处理

通过 `config.toml` 注册的 MCP 工具没有显式的 `permission_tier` 元数据，`PolicyGate` 默认按 `MODEL_DECIDES` 处理（保守策略）。
````

- [ ] **Step 2: 更新 `sebastian/capabilities/README.md` — 添加链接**

在文件末尾追加：

```markdown

## 详细文档

- **Tool 系统完整指南**：[`capabilities/tools/README.md`](tools/README.md)
  — 权限档位选择、创建流程、代码示例、常见错误
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/capabilities/tools/README.md sebastian/capabilities/README.md
git commit -m "docs(tools): 新增 Tool 系统完整指南，涵盖三档权限和创建流程

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 完成验证

所有任务完成后运行完整测试套件：

```bash
pytest tests/ -v 2>&1 | tail -20
```

Expected: 全部 PASS，无新增 FAIL。

手动验证服务启动：

```bash
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
```

Expected: 启动日志出现 `Loaded tool package: file_ops`、`Loaded tool package: shell`、`Loaded tool package: web_search`，无报错。

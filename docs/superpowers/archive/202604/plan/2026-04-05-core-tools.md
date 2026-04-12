# Core Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **JetBrains PyCharm MCP** is available — use it for symbol lookups, references, and type hierarchy queries before falling back to grep/find.

**Goal:** 用六个对齐 Claude Code 语义的标准工具（Read、Write、Edit、Bash、Glob、Grep）替换 Sebastian 现有的临时占位工具，并在工具调用层统一引入参数类型强制转换。

**Architecture:** 每个工具独立子目录包，共享进程级全局文件状态缓存（`_file_state.py`）用于 Write 的读后写校验；`_coerce_args` 在 `core/tool.py` 的 `call_tool` 中统一处理字符串参数强制转换；`_loader.py` 无需改动，自动发现新目录包。

**Tech Stack:** Python 3.12+、asyncio、pytest + pytest-asyncio、系统 ripgrep（优先）或 grep。

---

## 文件结构

```
新建：
  sebastian/capabilities/tools/_file_state.py
  sebastian/capabilities/tools/read/__init__.py
  sebastian/capabilities/tools/write/__init__.py
  sebastian/capabilities/tools/edit/__init__.py
  sebastian/capabilities/tools/bash/__init__.py
  sebastian/capabilities/tools/glob/__init__.py
  sebastian/capabilities/tools/grep/__init__.py
  tests/unit/test_file_state.py
  tests/unit/test_tool_coerce.py
  tests/unit/test_tools_read.py
  tests/unit/test_tools_write.py
  tests/unit/test_tools_edit.py
  tests/unit/test_tools_glob.py
  tests/unit/test_tools_grep.py
  tests/integration/test_tools_rw_flow.py

修改：
  sebastian/core/tool.py  — 新增 _unwrap_optional / _coerce_args，更新 _infer_json_schema 和 call_tool

删除：
  sebastian/capabilities/tools/file_ops/  （整个目录）
  sebastian/capabilities/tools/shell/     （整个目录）
```

---

## Task 1: 全局文件状态缓存 `_file_state.py`

**Files:**
- Create: `sebastian/capabilities/tools/_file_state.py`
- Test: `tests/unit/test_file_state.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_file_state.py
from __future__ import annotations

import pytest


def _clear():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()


def test_record_read_stores_mtime(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "a.txt"
    f.write_text("hello")
    _file_state.record_read(str(f))
    assert str(f) in _file_state._file_mtimes


def test_check_write_new_file_allowed(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    path = str(tmp_path / "new.txt")  # does not exist
    _file_state.check_write(path)  # must not raise


def test_check_write_requires_read_first(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "existing.txt"
    f.write_text("content")
    with pytest.raises(ValueError, match="not been read"):
        _file_state.check_write(str(f))


def test_check_write_rejects_stale_mtime(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "stale.txt"
    f.write_text("content")
    # Manually set a fake old mtime in cache (simulate "read a long time ago")
    _file_state._file_mtimes[str(f)] = 0.0
    with pytest.raises(ValueError, match="modified externally"):
        _file_state.check_write(str(f))


def test_check_write_passes_after_read(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "ok.txt"
    f.write_text("content")
    _file_state.record_read(str(f))
    _file_state.check_write(str(f))  # must not raise


def test_invalidate_updates_cache(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "out.txt"
    f.write_text("v1")
    _file_state.record_read(str(f))
    old_mtime = _file_state._file_mtimes[str(f)]
    f.write_text("v2")
    _file_state.invalidate(str(f))
    assert _file_state._file_mtimes[str(f)] != old_mtime
```

- [ ] **Step 2: 运行，确认全部失败**

```bash
pytest tests/unit/test_file_state.py -v
```

Expected: `ModuleNotFoundError` 或 `ImportError`（`_file_state` 不存在）

- [ ] **Step 3: 实现 `_file_state.py`**

```python
# sebastian/capabilities/tools/_file_state.py
from __future__ import annotations

import os

_file_mtimes: dict[str, float] = {}


def record_read(path: str) -> None:
    """Read 成功后调用，记录当前 mtime。"""
    try:
        _file_mtimes[path] = os.path.getmtime(path)
    except OSError:
        pass


def check_write(path: str) -> None:
    """
    Write 前调用。
    - 文件不存在 → 允许（新建）
    - 文件存在但从未 Read → 拒绝
    - 文件存在且 Read 过但 mtime 变更 → 拒绝
    抛出 ValueError。
    """
    if not os.path.exists(path):
        return
    if path not in _file_mtimes:
        raise ValueError(
            f"File has not been read yet. Call Read first before writing: {path}"
        )
    current_mtime = os.path.getmtime(path)
    if current_mtime != _file_mtimes[path]:
        raise ValueError(
            f"File has been modified externally since last read. "
            f"Call Read again before writing: {path}"
        )


def invalidate(path: str) -> None:
    """Write/Edit 成功后调用，更新缓存 mtime。"""
    try:
        _file_mtimes[path] = os.path.getmtime(path)
    except OSError:
        _file_mtimes.pop(path, None)
```

- [ ] **Step 4: 运行，确认全部通过**

```bash
pytest tests/unit/test_file_state.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add sebastian/capabilities/tools/_file_state.py tests/unit/test_file_state.py
git commit -m "feat(tools): 新增全局文件状态缓存 _file_state.py"
```

---

## Task 2: `_coerce_args` 与 Optional 类型修复（`core/tool.py`）

**Files:**
- Modify: `sebastian/core/tool.py`
- Test: `tests/unit/test_tool_coerce.py`

**背景：** 当前 `call_tool` 直接透传 kwargs，LLM 可能传 `"2"` 而非 `2`。同时 `_infer_json_schema` 对 `int | None` 会错误地返回 `"string"`，需一并修复。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tool_coerce.py
from __future__ import annotations

import pytest


def test_coerce_str_to_int():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(offset: int) -> ToolResult: ...

    result = _coerce_args(fn, {"offset": "5"})
    assert result["offset"] == 5
    assert isinstance(result["offset"], int)


def test_coerce_str_to_float():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(score: float) -> ToolResult: ...

    result = _coerce_args(fn, {"score": "3.14"})
    assert abs(result["score"] - 3.14) < 1e-9


def test_coerce_str_to_bool_true():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(replace_all: bool) -> ToolResult: ...

    for val in ("true", "True", "TRUE", "1", "yes"):
        assert _coerce_args(fn, {"replace_all": val})["replace_all"] is True


def test_coerce_str_to_bool_false():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(replace_all: bool) -> ToolResult: ...

    for val in ("false", "False", "0", "no"):
        assert _coerce_args(fn, {"replace_all": val})["replace_all"] is False


def test_coerce_optional_int():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(limit: int | None = None) -> ToolResult: ...

    result = _coerce_args(fn, {"limit": "10"})
    assert result["limit"] == 10
    assert isinstance(result["limit"], int)


def test_coerce_non_string_unchanged():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(offset: int) -> ToolResult: ...

    result = _coerce_args(fn, {"offset": 7})
    assert result["offset"] == 7


def test_coerce_invalid_int_keeps_original():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(offset: int) -> ToolResult: ...

    result = _coerce_args(fn, {"offset": "abc"})
    assert result["offset"] == "abc"  # 保留原值，让函数本身报错


def test_infer_schema_optional_int_maps_to_integer():
    """int | None 参数应在 JSON schema 中映射为 integer，而非 string。"""
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="schema_test_opt", description="test")
    async def fn(offset: int | None = None) -> ToolResult:
        return ToolResult(ok=True, output=None)

    spec, _ = tool_module._tools["schema_test_opt"]
    assert spec.parameters["properties"]["offset"]["type"] == "integer"
    assert "offset" not in spec.parameters["required"]
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_tool_coerce.py -v
```

Expected: `ImportError: cannot import name '_coerce_args'`

- [ ] **Step 3: 修改 `core/tool.py`**

用以下完整内容替换（保留原有逻辑，新增 `_unwrap_optional`、`_coerce_args`，更新 `_infer_json_schema` 和 `call_tool`）：

```python
# sebastian/core/tool.py
from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Union, get_args, get_origin, get_type_hints

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


def _unwrap_optional(hint: Any) -> Any:
    """X | None → X。非 Optional 类型原样返回。"""
    if get_origin(hint) is Union:
        args = [a for a in get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint


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
        effective_ann = _unwrap_optional(ann)
        json_type = _TYPE_MAP.get(effective_ann, "string")
        properties[param_name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": properties, "required": required}


def _coerce_args(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    根据函数签名的类型注解对传入参数做宽松类型转换。
    将字符串 "2" → int 2，"3.14" → float 3.14，"true"/"1"/"yes" → bool True。
    转换失败时保留原值。支持 X | None（Optional）类型。
    """
    try:
        hints = get_type_hints(inspect.unwrap(fn))
    except Exception:
        return kwargs

    result = dict(kwargs)
    for name, value in kwargs.items():
        if not isinstance(value, str):
            continue
        hint = hints.get(name)
        if hint is None:
            continue
        target = _unwrap_optional(hint)
        if target is int:
            try:
                result[name] = int(value)
            except (ValueError, TypeError):
                pass
        elif target is float:
            try:
                result[name] = float(value)
            except (ValueError, TypeError):
                pass
        elif target is bool:
            result[name] = value.lower() in ("true", "1", "yes")
    return result


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
    coerced = _coerce_args(fn, kwargs)
    return await fn(**coerced)
```

- [ ] **Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_tool_coerce.py tests/unit/test_tool_decorator.py -v
```

Expected: 所有测试通过（包括原有 test_tool_decorator.py）

- [ ] **Step 5: 提交**

```bash
git add sebastian/core/tool.py tests/unit/test_tool_coerce.py
git commit -m "feat(core): 新增 _coerce_args 类型强制转换，修复 Optional 类型 schema 推断"
```

---

## Task 3: Read 工具

**Files:**
- Create: `sebastian/capabilities/tools/read/__init__.py`
- Test: `tests/unit/test_tools_read.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tools_read.py
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_state():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()


@pytest.mark.asyncio
async def test_read_basic(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")

    result = await call_tool("Read", file_path=str(f))
    assert result.ok
    assert "line1" in result.output["content"]
    assert result.output["total_lines"] == 3
    assert result.output["truncated"] is False


@pytest.mark.asyncio
async def test_read_with_offset_and_limit(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "multi.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)))

    result = await call_tool("Read", file_path=str(f), offset=3, limit=2)
    assert result.ok
    content = result.output["content"]
    assert "line3" in content
    assert "line4" in content
    assert "line5" not in content
    assert result.output["lines_read"] == 2


@pytest.mark.asyncio
async def test_read_truncates_at_2000_lines(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 2501)))

    result = await call_tool("Read", file_path=str(f))
    assert result.ok
    assert result.output["truncated"] is True
    assert result.output["lines_read"] == 2000
    assert result.output["total_lines"] == 2500


@pytest.mark.asyncio
async def test_read_nonexistent_file():
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    result = await call_tool("Read", file_path="/nonexistent/path/file.txt")
    assert not result.ok
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_read_directory_returns_error(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    result = await call_tool("Read", file_path=str(tmp_path))
    assert not result.ok
    assert "directory" in result.error.lower()


@pytest.mark.asyncio
async def test_read_updates_file_state(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools import _file_state
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "track.txt"
    f.write_text("content")

    assert str(f) not in _file_state._file_mtimes
    await call_tool("Read", file_path=str(f))
    assert str(f) in _file_state._file_mtimes
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_tools_read.py -v
```

Expected: `ModuleNotFoundError: No module named 'sebastian.capabilities.tools.read'`

- [ ] **Step 3: 实现 Read 工具**

```python
# sebastian/capabilities/tools/read/__init__.py
from __future__ import annotations

import os

from sebastian.capabilities.tools import _file_state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_DEFAULT_LIMIT = 2000


@tool(
    name="Read",
    description=(
        "Read the contents of a file. Supports optional offset (1-indexed start line) "
        "and limit (number of lines to read). Defaults to first 2000 lines. "
        "Returns content, total_lines, lines_read, and truncated flag."
    ),
    permission_tier=PermissionTier.LOW,
)
async def read(
    file_path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> ToolResult:
    path = os.path.abspath(file_path)
    if not os.path.exists(path):
        return ToolResult(ok=False, error=f"File not found: {path}")
    if os.path.isdir(path):
        return ToolResult(ok=False, error=f"Path is a directory, not a file: {path}")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        start = max(0, (offset - 1) if offset is not None else 0)
        max_lines = limit if limit is not None else _DEFAULT_LIMIT
        end = min(start + max_lines, total_lines)
        selected = lines[start:end]

        _file_state.record_read(path)

        return ToolResult(
            ok=True,
            output={
                "content": "".join(selected),
                "total_lines": total_lines,
                "lines_read": len(selected),
                "truncated": (start + max_lines) < total_lines,
            },
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_tools_read.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add sebastian/capabilities/tools/read/__init__.py tests/unit/test_tools_read.py
git commit -m "feat(tools): 新增 Read 工具，支持 offset/limit 和 mtime 状态追踪"
```

---

## Task 4: Write 工具

**Files:**
- Create: `sebastian/capabilities/tools/write/__init__.py`
- Test: `tests/unit/test_tools_write.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tools_write.py
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_state():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()


@pytest.mark.asyncio
async def test_write_creates_new_file(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.write import write  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "new.txt"
    result = await call_tool("Write", file_path=str(f), content="hello world")
    assert result.ok
    assert result.output["action"] == "created"
    assert f.read_text() == "hello world"


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.write import write  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "a" / "b" / "c.txt"
    result = await call_tool("Write", file_path=str(f), content="deep")
    assert result.ok
    assert f.read_text() == "deep"


@pytest.mark.asyncio
async def test_write_existing_file_requires_read_first(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.write import write  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "existing.txt"
    f.write_text("original")

    result = await call_tool("Write", file_path=str(f), content="new")
    assert not result.ok
    assert "not been read" in result.error


@pytest.mark.asyncio
async def test_write_after_read_succeeds(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools import _file_state
    from sebastian.capabilities.tools.write import write  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "rw.txt"
    f.write_text("original")
    _file_state.record_read(str(f))

    result = await call_tool("Write", file_path=str(f), content="updated")
    assert result.ok
    assert result.output["action"] == "updated"
    assert f.read_text() == "updated"


@pytest.mark.asyncio
async def test_write_rejects_stale_mtime(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools import _file_state
    from sebastian.capabilities.tools.write import write  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "stale.txt"
    f.write_text("original")
    # Simulate "read a long time ago"
    _file_state._file_mtimes[str(f)] = 0.0

    result = await call_tool("Write", file_path=str(f), content="new")
    assert not result.ok
    assert "modified externally" in result.error
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_tools_write.py -v
```

Expected: `ModuleNotFoundError: No module named 'sebastian.capabilities.tools.write'`

- [ ] **Step 3: 实现 Write 工具**

```python
# sebastian/capabilities/tools/write/__init__.py
from __future__ import annotations

import os
from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="Write",
    description=(
        "Write full content to a file, replacing existing content. "
        "Creates parent directories if needed. "
        "If the file already exists, it must have been previously Read in this session."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def write(file_path: str, content: str) -> ToolResult:
    path = os.path.abspath(file_path)
    try:
        _file_state.check_write(path)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))

    action = "updated" if os.path.exists(path) else "created"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        _file_state.invalidate(path)
        return ToolResult(
            ok=True,
            output={
                "file_path": path,
                "action": action,
                "bytes_written": len(content.encode("utf-8")),
            },
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_tools_write.py -v
```

Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add sebastian/capabilities/tools/write/__init__.py tests/unit/test_tools_write.py
git commit -m "feat(tools): 新增 Write 工具，含 mtime 读后写校验"
```

---

## Task 5: Edit 工具

**Files:**
- Create: `sebastian/capabilities/tools/edit/__init__.py`
- Test: `tests/unit/test_tools_edit.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tools_edit.py
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_state():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()


@pytest.mark.asyncio
async def test_edit_replaces_unique_match(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.edit import edit  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")

    result = await call_tool(
        "Edit",
        file_path=str(f),
        old_string="return 1",
        new_string="return 42",
    )
    assert result.ok
    assert result.output["replacements"] == 1
    assert f.read_text() == "def foo():\n    return 42\n"


@pytest.mark.asyncio
async def test_edit_fails_when_not_found(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.edit import edit  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "f.txt"
    f.write_text("hello world")

    result = await call_tool(
        "Edit", file_path=str(f), old_string="xyz", new_string="abc"
    )
    assert not result.ok
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_fails_on_multiple_matches(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.edit import edit  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "dup.txt"
    f.write_text("foo\nfoo\nbar\n")

    result = await call_tool(
        "Edit", file_path=str(f), old_string="foo", new_string="baz"
    )
    assert not result.ok
    assert "2" in result.error  # mentions count


@pytest.mark.asyncio
async def test_edit_replace_all_replaces_all_occurrences(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.edit import edit  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "multi.txt"
    f.write_text("foo\nfoo\nfoo\n")

    result = await call_tool(
        "Edit",
        file_path=str(f),
        old_string="foo",
        new_string="bar",
        replace_all=True,
    )
    assert result.ok
    assert result.output["replacements"] == 3
    assert f.read_text() == "bar\nbar\nbar\n"


@pytest.mark.asyncio
async def test_edit_nonexistent_file():
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.edit import edit  # noqa: F401
    from sebastian.core.tool import call_tool

    result = await call_tool(
        "Edit",
        file_path="/no/such/file.txt",
        old_string="x",
        new_string="y",
    )
    assert not result.ok
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_edit_updates_file_state(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools import _file_state
    from sebastian.capabilities.tools.edit import edit  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "state.txt"
    f.write_text("hello world")

    await call_tool("Edit", file_path=str(f), old_string="world", new_string="there")
    assert str(f) in _file_state._file_mtimes
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_tools_edit.py -v
```

Expected: `ModuleNotFoundError: No module named 'sebastian.capabilities.tools.edit'`

- [ ] **Step 3: 实现 Edit 工具**

```python
# sebastian/capabilities/tools/edit/__init__.py
from __future__ import annotations

import os

from sebastian.capabilities.tools import _file_state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="Edit",
    description=(
        "Replace old_string with new_string in a file. "
        "By default (replace_all=false), old_string must appear exactly once — "
        "if it appears 0 times the tool errors, if it appears more than once the tool "
        "errors and asks you to provide more context to make it unique. "
        "Set replace_all=true to replace every occurrence."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> ToolResult:
    path = os.path.abspath(file_path)
    if not os.path.exists(path):
        return ToolResult(ok=False, error=f"File not found: {path}")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return ToolResult(ok=False, error=f"old_string not found in file: {path}")
        if count > 1 and not replace_all:
            return ToolResult(
                ok=False,
                error=(
                    f"old_string matches {count} times. "
                    f"Provide more context to make it unique, or use replace_all=true"
                ),
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        _file_state.invalidate(path)
        return ToolResult(ok=True, output={"file_path": path, "replacements": replacements})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_tools_edit.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add sebastian/capabilities/tools/edit/__init__.py tests/unit/test_tools_edit.py
git commit -m "feat(tools): 新增 Edit 工具，精准字符串替换含唯一性校验"
```

---

## Task 6: Bash 工具

**Files:**
- Create: `sebastian/capabilities/tools/bash/__init__.py`

（Bash 依赖真实子进程，无独立单元测试；集成测试在 Task 9 覆盖。）

- [ ] **Step 1: 创建 Bash 工具**

```python
# sebastian/capabilities/tools/bash/__init__.py
from __future__ import annotations

import asyncio

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_MAX_OUTPUT_CHARS = 10_000
_DEFAULT_TIMEOUT = 600


@tool(
    name="Bash",
    description=(
        "Execute a shell command. Returns stdout, stderr, and return code. "
        "Non-zero return codes are not automatically errors "
        "(e.g. grep returns 1 when no match found). "
        "Default timeout is 600 seconds; override with timeout parameter for longer tasks."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def bash(command: str, timeout: int | None = None) -> ToolResult:
    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=float(effective_timeout)
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return ToolResult(
            ok=False, error=f"Command timed out after {effective_timeout}s"
        )

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    truncated = False
    if len(stdout) > _MAX_OUTPUT_CHARS:
        stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True
    if len(stderr) > _MAX_OUTPUT_CHARS:
        stderr = stderr[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True

    return ToolResult(
        ok=True,
        output={
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode,
            "truncated": truncated,
        },
    )
```

- [ ] **Step 2: 快速冒烟测试**

```bash
python -c "
import asyncio
from sebastian.capabilities.tools.bash import bash
from sebastian.core.tool import call_tool
result = asyncio.run(call_tool('Bash', command='echo hello'))
assert result.ok
assert 'hello' in result.output['stdout']
print('Bash smoke test passed')
"
```

Expected: `Bash smoke test passed`

- [ ] **Step 3: 提交**

```bash
git add sebastian/capabilities/tools/bash/__init__.py
git commit -m "feat(tools): 新增 Bash 工具，替换 shell，默认 timeout 600s"
```

---

## Task 7: Glob 工具

**Files:**
- Create: `sebastian/capabilities/tools/glob/__init__.py`
- Test: `tests/unit/test_tools_glob.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tools_glob.py
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_glob_finds_matching_files(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.glob import glob  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "c.txt").write_text("c")

    result = await call_tool("Glob", pattern="*.py", path=str(tmp_path))
    assert result.ok
    files = result.output["files"]
    assert len(files) == 2
    assert all(f.endswith(".py") for f in files)
    assert result.output["truncated"] is False


@pytest.mark.asyncio
async def test_glob_recursive(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.glob import glob  # noqa: F401
    from sebastian.core.tool import call_tool

    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "root.py").write_text("root")
    (sub / "nested.py").write_text("nested")

    result = await call_tool("Glob", pattern="**/*.py", path=str(tmp_path))
    assert result.ok
    assert result.output["count"] == 2


@pytest.mark.asyncio
async def test_glob_truncates_at_100(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.glob import glob  # noqa: F401
    from sebastian.core.tool import call_tool

    for i in range(110):
        (tmp_path / f"file{i}.txt").write_text(str(i))

    result = await call_tool("Glob", pattern="*.txt", path=str(tmp_path))
    assert result.ok
    assert result.output["count"] == 100
    assert result.output["truncated"] is True


@pytest.mark.asyncio
async def test_glob_no_match_returns_empty(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.glob import glob  # noqa: F401
    from sebastian.core.tool import call_tool

    result = await call_tool("Glob", pattern="*.xyz", path=str(tmp_path))
    assert result.ok
    assert result.output["files"] == []
    assert result.output["count"] == 0
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_tools_glob.py -v
```

Expected: `ModuleNotFoundError: No module named 'sebastian.capabilities.tools.glob'`

- [ ] **Step 3: 实现 Glob 工具**

```python
# sebastian/capabilities/tools/glob/__init__.py
from __future__ import annotations

import glob as _glob_module
import os

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_MAX_RESULTS = 100


@tool(
    name="Glob",
    description=(
        "Find files matching a glob pattern (e.g. '**/*.py'). "
        "Results are sorted by modification time (newest first), up to 100 entries. "
        "Use path to restrict search to a specific directory (defaults to CWD)."
    ),
    permission_tier=PermissionTier.LOW,
)
async def glob(pattern: str, path: str | None = None) -> ToolResult:
    root = os.path.abspath(path) if path else os.getcwd()
    try:
        matches = _glob_module.glob(pattern, root_dir=root, recursive=True)

        def _mtime(p: str) -> float:
            try:
                return os.path.getmtime(os.path.join(root, p))
            except OSError:
                return 0.0

        sorted_matches = sorted(matches, key=_mtime, reverse=True)
        truncated = len(sorted_matches) > _MAX_RESULTS
        results = sorted_matches[:_MAX_RESULTS]

        return ToolResult(
            ok=True,
            output={"files": results, "count": len(results), "truncated": truncated},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_tools_glob.py -v
```

Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add sebastian/capabilities/tools/glob/__init__.py tests/unit/test_tools_glob.py
git commit -m "feat(tools): 新增 Glob 工具，文件模式搜索"
```

---

## Task 8: Grep 工具

**Files:**
- Create: `sebastian/capabilities/tools/grep/__init__.py`
- Test: `tests/unit/test_tools_grep.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_tools_grep.py
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_grep_finds_matches(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\ndef bar():\n    return 2\n")

    result = await call_tool("Grep", pattern="def ", path=str(f))
    assert result.ok
    assert "foo" in result.output["output"]
    assert "bar" in result.output["output"]


@pytest.mark.asyncio
async def test_grep_ignore_case(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "text.txt"
    f.write_text("Hello World\nhello world\n")

    result = await call_tool("Grep", pattern="HELLO", path=str(f), ignore_case=True)
    assert result.ok
    assert "Hello" in result.output["output"] or "hello" in result.output["output"]


@pytest.mark.asyncio
async def test_grep_head_limit(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "many.txt"
    f.write_text("\n".join(f"match line {i}" for i in range(300)))

    result = await call_tool("Grep", pattern="match", path=str(f), head_limit=10)
    assert result.ok
    lines = result.output["output"].strip().splitlines()
    assert len(lines) <= 10
    assert result.output["truncated"] is True


@pytest.mark.asyncio
async def test_grep_no_match_returns_empty(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "empty_match.txt"
    f.write_text("nothing relevant here\n")

    result = await call_tool("Grep", pattern="xyz123notexist", path=str(f))
    assert result.ok
    assert result.output["output"] == ""


@pytest.mark.asyncio
async def test_grep_with_glob_filter(tmp_path):
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.py").write_text("target in python\n")
    (tmp_path / "b.txt").write_text("target in text\n")

    result = await call_tool("Grep", pattern="target", path=str(tmp_path), glob="*.py")
    assert result.ok
    assert "python" in result.output["output"]
    assert "text" not in result.output["output"]
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_tools_grep.py -v
```

Expected: `ModuleNotFoundError: No module named 'sebastian.capabilities.tools.grep'`

- [ ] **Step 3: 实现 Grep 工具**

```python
# sebastian/capabilities/tools/grep/__init__.py
from __future__ import annotations

import asyncio
import shutil

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_rg_available: bool | None = None


def _has_ripgrep() -> bool:
    global _rg_available
    if _rg_available is None:
        _rg_available = shutil.which("rg") is not None
    return _rg_available


@tool(
    name="Grep",
    description=(
        "Search file contents using a regex pattern. "
        "Uses ripgrep (rg) if available, falls back to grep. "
        "Searches recursively by default. "
        "Returns matching lines up to head_limit (default 250)."
    ),
    permission_tier=PermissionTier.LOW,
)
async def grep(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    ignore_case: bool = False,
    context_lines: int | None = None,
    head_limit: int | None = None,
) -> ToolResult:
    import os

    search_path = os.path.abspath(path) if path else os.getcwd()
    limit = head_limit if head_limit is not None else 250

    if _has_ripgrep():
        cmd: list[str] = ["rg", "--line-number", pattern, search_path]
        if ignore_case:
            cmd.append("--ignore-case")
        if glob:
            cmd += ["--glob", glob]
        if context_lines is not None:
            cmd += ["--context", str(context_lines)]
        backend = "ripgrep"
    else:
        cmd = ["grep", "-rn", pattern, search_path]
        if ignore_case:
            cmd.append("-i")
        if glob:
            cmd += ["--include", glob]
        if context_lines is not None:
            cmd += [f"-C{context_lines}"]
        backend = "grep"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        return ToolResult(ok=False, error="Grep timed out after 30s")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

    output = stdout_bytes.decode(errors="replace")
    lines = output.splitlines()
    truncated = len(lines) > limit
    result_output = "\n".join(lines[:limit])

    return ToolResult(
        ok=True,
        output={"output": result_output, "truncated": truncated, "backend": backend},
    )
```

- [ ] **Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_tools_grep.py -v
```

Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add sebastian/capabilities/tools/grep/__init__.py tests/unit/test_tools_grep.py
git commit -m "feat(tools): 新增 Grep 工具，优先 ripgrep，fallback grep"
```

---

## Task 9: 删除旧工具 + 集成测试

**Files:**
- Delete: `sebastian/capabilities/tools/file_ops/` (整个目录)
- Delete: `sebastian/capabilities/tools/shell/` (整个目录)
- Create: `tests/integration/test_tools_rw_flow.py`

- [ ] **Step 1: 写集成测试（在删除旧工具之前）**

```python
# tests/integration/test_tools_rw_flow.py
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_tool_state():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()
    from sebastian.core import tool as tool_module
    tool_module._tools.clear()
    # Import all 6 new tools so they are registered
    import sebastian.capabilities.tools.bash  # noqa: F401
    import sebastian.capabilities.tools.edit  # noqa: F401
    import sebastian.capabilities.tools.glob  # noqa: F401
    import sebastian.capabilities.tools.grep  # noqa: F401
    import sebastian.capabilities.tools.read  # noqa: F401
    import sebastian.capabilities.tools.write  # noqa: F401


@pytest.mark.asyncio
async def test_read_then_write_flow(tmp_path):
    """Read → modify content → Write 完整流程。"""
    from sebastian.core.tool import call_tool

    f = tmp_path / "target.txt"
    f.write_text("version: 1\n")

    read_result = await call_tool("Read", file_path=str(f))
    assert read_result.ok
    new_content = read_result.output["content"].replace("version: 1", "version: 2")

    write_result = await call_tool("Write", file_path=str(f), content=new_content)
    assert write_result.ok
    assert f.read_text() == "version: 2\n"


@pytest.mark.asyncio
async def test_write_without_read_is_rejected(tmp_path):
    """已存在的文件未经 Read 直接 Write 应被拒绝。"""
    from sebastian.core.tool import call_tool

    f = tmp_path / "protected.txt"
    f.write_text("original")

    result = await call_tool("Write", file_path=str(f), content="overwrite")
    assert not result.ok
    assert "not been read" in result.error
    assert f.read_text() == "original"


@pytest.mark.asyncio
async def test_read_edit_verify(tmp_path):
    """Read → Edit → Read：验证内容已更新。"""
    from sebastian.core.tool import call_tool

    f = tmp_path / "src.py"
    f.write_text("x = 1\ny = 2\n")

    await call_tool("Read", file_path=str(f))  # prime file state
    edit_result = await call_tool(
        "Edit", file_path=str(f), old_string="x = 1", new_string="x = 100"
    )
    assert edit_result.ok

    read_result = await call_tool("Read", file_path=str(f))
    assert "x = 100" in read_result.output["content"]
    assert "x = 1" not in read_result.output["content"]


@pytest.mark.asyncio
async def test_bash_runs_command():
    """Bash 工具可执行基础命令。"""
    from sebastian.core.tool import call_tool

    result = await call_tool("Bash", command="echo integration_test_ok")
    assert result.ok
    assert "integration_test_ok" in result.output["stdout"]
    assert result.output["returncode"] == 0


@pytest.mark.asyncio
async def test_bash_nonzero_returncode_is_not_error():
    """Bash 非 0 返回码不是 tool 错误，ok=True。"""
    from sebastian.core.tool import call_tool

    result = await call_tool("Bash", command="exit 1")
    assert result.ok  # ok=True even though returncode=1
    assert result.output["returncode"] == 1


@pytest.mark.asyncio
async def test_glob_and_grep_on_real_files(tmp_path):
    """Glob + Grep 联合使用：先找文件，再搜内容。"""
    from sebastian.core.tool import call_tool

    (tmp_path / "alpha.py").write_text("SECRET_KEY = 'abc'\n")
    (tmp_path / "beta.py").write_text("password = 'xyz'\n")
    (tmp_path / "readme.txt").write_text("no secrets here\n")

    glob_result = await call_tool("Glob", pattern="*.py", path=str(tmp_path))
    assert glob_result.ok
    assert glob_result.output["count"] == 2

    grep_result = await call_tool(
        "Grep", pattern="SECRET_KEY|password", path=str(tmp_path), glob="*.py"
    )
    assert grep_result.ok
    assert "SECRET_KEY" in grep_result.output["output"]
    assert "password" in grep_result.output["output"]
```

- [ ] **Step 2: 确认集成测试在删除旧工具前通过**

```bash
pytest tests/integration/test_tools_rw_flow.py -v
```

Expected: 6 passed

- [ ] **Step 3: 确认没有代码直接 import 旧工具模块**

```bash
grep -r "from sebastian.capabilities.tools.file_ops" sebastian/ tests/
grep -r "from sebastian.capabilities.tools.shell" sebastian/ tests/
grep -r "capabilities.tools.file_ops" sebastian/ tests/
grep -r "capabilities.tools.shell" sebastian/ tests/
```

Expected: 无输出（全部无引用）

- [ ] **Step 4: 删除旧工具目录**

```bash
rm -rf sebastian/capabilities/tools/file_ops
rm -rf sebastian/capabilities/tools/shell
```

- [ ] **Step 5: 运行全量测试，确认无回归**

```bash
pytest -x -q
```

Expected: 全部通过，无 `file_read`、`file_write`、`shell` 相关失败。若有失败检查输出找出原因。

- [ ] **Step 6: 提交**

```bash
git add tests/integration/test_tools_rw_flow.py
git rm -r sebastian/capabilities/tools/file_ops sebastian/capabilities/tools/shell
git commit -m "feat(tools): 删除旧 file_ops/shell，新增集成测试，完成 Core Tools 重建"
```

# Workspace 边界强制执行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 确保 Agent 的文件写/改操作默认限制在 `workspace_dir` 内，workspace 外操作需用户审批，并通过统一的系统提示词引导所有 Agent 优先使用结构化工具。

**Architecture:** 新增共享路径解析模块 `_path_utils.py`，Write/Edit/Read 工具统一使用 `resolve_path()` 替换 `os.path.abspath()`；PolicyGate 在 MODEL_DECIDES 工具调用前检查 `file_path` 是否在 workspace 内；PermissionReviewer 动态注入 `workspace_dir` 到 prompt；BaseAgent 新增 `_guidelines_section()` 注入全局操作规范。

**Tech Stack:** Python 3.12+, pytest-asyncio, unittest.mock（`AsyncMock`/`MagicMock`/`patch`）

---

## File Map

| 操作 | 文件 |
|------|------|
| 新建 | `sebastian/capabilities/tools/_path_utils.py` |
| 修改 | `sebastian/capabilities/tools/write/__init__.py` |
| 修改 | `sebastian/capabilities/tools/edit/__init__.py` |
| 修改 | `sebastian/capabilities/tools/read/__init__.py` |
| 修改 | `sebastian/permissions/gate.py` |
| 修改 | `sebastian/permissions/reviewer.py` |
| 修改 | `sebastian/core/base_agent.py` |
| 新建 | `tests/unit/test_path_utils.py` |
| 修改 | `tests/unit/test_tools_write.py` |
| 修改 | `tests/unit/test_tools_edit.py` |
| 修改 | `tests/unit/test_policy_gate.py` |
| 修改 | `tests/unit/test_permission_reviewer.py` |
| 修改 | `tests/unit/test_base_agent.py` |

---

### Task 1: 新建 `_path_utils.py` + 单元测试

**Files:**
- Create: `sebastian/capabilities/tools/_path_utils.py`
- Create: `tests/unit/test_path_utils.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_path_utils.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def test_relative_path_resolves_to_workspace(tmp_path: Path) -> None:
    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        from sebastian.capabilities.tools._path_utils import resolve_path
        result = resolve_path("foo/bar.txt")
    assert result == (tmp_path / "foo/bar.txt").resolve()


def test_absolute_path_within_workspace_resolves_as_is(tmp_path: Path) -> None:
    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        from sebastian.capabilities.tools._path_utils import resolve_path
        abs_path = str(tmp_path / "sub" / "file.py")
        result = resolve_path(abs_path)
    assert result == Path(abs_path).resolve()


def test_absolute_path_outside_workspace_resolves_as_is(tmp_path: Path) -> None:
    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        from sebastian.capabilities.tools._path_utils import resolve_path
        result = resolve_path("/tmp/evil.txt")
    assert result == Path("/tmp/evil.txt").resolve()
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_path_utils.py -v
```

Expected: `ImportError: cannot import name 'resolve_path'`

- [ ] **Step 3: 创建 `_path_utils.py`**

```python
# sebastian/capabilities/tools/_path_utils.py
from __future__ import annotations

from pathlib import Path

from sebastian.config import settings


def resolve_path(file_path: str) -> Path:
    """将文件路径解析为绝对路径。

    相对路径解析到 workspace_dir；绝对路径直接 resolve()。
    所有文件类工具必须调用此函数，不得使用 os.path.abspath()。
    """
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    return (settings.workspace_dir / file_path).resolve()
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/unit/test_path_utils.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/_path_utils.py tests/unit/test_path_utils.py
git commit -m "feat(tools): 新增 _path_utils.resolve_path() 统一路径解析基准"
```

---

### Task 2: 更新 Write 工具使用 `resolve_path`

**Files:**
- Modify: `sebastian/capabilities/tools/write/__init__.py`
- Modify: `tests/unit/test_tools_write.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_tools_write.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_write_relative_path_resolves_to_workspace(tmp_path):
    """相对路径应解析到 workspace_dir，而非进程 cwd。"""
    from unittest.mock import patch
    from sebastian.core.tool import call_tool

    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        result = await call_tool("Write", file_path="output.txt", content="hello")

    assert result.ok
    assert (tmp_path / "output.txt").read_text() == "hello"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_tools_write.py::test_write_relative_path_resolves_to_workspace -v
```

Expected: FAIL — 文件写到进程 cwd 下，不在 `tmp_path`

- [ ] **Step 3: 修改 Write 工具**

将 `sebastian/capabilities/tools/write/__init__.py` 中：

```python
import os
...
path = os.path.abspath(file_path)
```

替换为：

```python
from sebastian.capabilities.tools._path_utils import resolve_path
...
path = str(resolve_path(file_path))
```

同时删除 `import os`（若仅用于 `abspath`；`os.path.exists` 改用 `Path(path).exists()`）。

完整修改后文件：

```python
from __future__ import annotations

from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.capabilities.tools._path_utils import resolve_path
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
    path = str(resolve_path(file_path))
    try:
        _file_state.check_write(path)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))

    action = "updated" if Path(path).exists() else "created"
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

- [ ] **Step 4: 运行所有 Write 测试**

```bash
pytest tests/unit/test_tools_write.py -v
```

Expected: 全部 passed（现有测试用绝对路径，不受影响）

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/write/__init__.py tests/unit/test_tools_write.py
git commit -m "feat(tools): Write 工具使用 resolve_path() 统一路径解析"
```

---

### Task 3: 更新 Edit 工具使用 `resolve_path`

**Files:**
- Modify: `sebastian/capabilities/tools/edit/__init__.py`
- Modify: `tests/unit/test_tools_edit.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_tools_edit.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_edit_relative_path_resolves_to_workspace(tmp_path):
    """相对路径应解析到 workspace_dir。"""
    from unittest.mock import patch
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    target = tmp_path / "script.py"
    target.write_text("x = 1\n")
    record_read(str(target))

    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        result = await call_tool(
            "Edit",
            file_path="script.py",
            old_string="x = 1",
            new_string="x = 42",
        )

    assert result.ok
    assert target.read_text() == "x = 42\n"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_tools_edit.py::test_edit_relative_path_resolves_to_workspace -v
```

Expected: FAIL

- [ ] **Step 3: 修改 Edit 工具**

完整替换 `sebastian/capabilities/tools/edit/__init__.py`：

```python
from __future__ import annotations

from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.capabilities.tools._path_utils import resolve_path
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
    path = str(resolve_path(file_path))
    try:
        _file_state.check_write(path)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))
    if not Path(path).exists():
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

- [ ] **Step 4: 运行所有 Edit 测试**

```bash
pytest tests/unit/test_tools_edit.py -v
```

Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/edit/__init__.py tests/unit/test_tools_edit.py
git commit -m "feat(tools): Edit 工具使用 resolve_path() 统一路径解析"
```

---

### Task 4: 更新 Read 工具使用 `resolve_path`

**Files:**
- Modify: `sebastian/capabilities/tools/read/__init__.py`

Read 工具不受 workspace 约束（可读任意路径），但路径解析基准应与其他工具一致。无需新增测试（现有用例覆盖绝对路径，不受影响）。

- [ ] **Step 1: 修改 Read 工具**

将 `sebastian/capabilities/tools/read/__init__.py` 中：

```python
import os
...
path = os.path.abspath(file_path)
```

替换为：

```python
from sebastian.capabilities.tools._path_utils import resolve_path
...
path = str(resolve_path(file_path))
```

完整修改后文件：

```python
from __future__ import annotations

from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.capabilities.tools._path_utils import resolve_path
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
    path = str(resolve_path(file_path))
    if not Path(path).exists():
        return ToolResult(ok=False, error=f"File not found: {path}")
    if Path(path).is_dir():
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

        content = "".join(selected)
        empty_hint = f"File exists but is empty (0 lines): {path}" if not content and total_lines == 0 else None

        return ToolResult(
            ok=True,
            output={
                "content": content,
                "total_lines": total_lines,
                "lines_read": len(selected),
                "truncated": (start + max_lines) < total_lines,
            },
            empty_hint=empty_hint,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 2: 运行 Read 测试确认无回归**

```bash
pytest tests/unit/test_tools_read.py -v
```

Expected: 全部 passed

- [ ] **Step 3: Commit**

```bash
git add sebastian/capabilities/tools/read/__init__.py
git commit -m "feat(tools): Read 工具使用 resolve_path() 统一路径解析基准"
```

---

### Task 5: PolicyGate workspace 边界前置检查

**Files:**
- Modify: `sebastian/permissions/gate.py`
- Modify: `tests/unit/test_policy_gate.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_policy_gate.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_model_decides_file_path_outside_workspace_skips_reviewer(tmp_path) -> None:
    """file_path 在 workspace 外 → 跳过 reviewer，直接走用户审批。"""
    from pathlib import Path
    from unittest.mock import patch
    from sebastian.permissions.gate import PolicyGate

    outside_path = "/tmp/evil_output.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="written"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=True)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool, \
         patch("sebastian.permissions.gate.resolve_path", return_value=Path(outside_path)), \
         patch("sebastian.permissions.gate.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Write",
            {"file_path": outside_path, "content": "data", "reason": "write outside"},
            _make_context("write a file"),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_awaited_once()
    # reason 不应透传给 registry
    call_kwargs = registry.call.call_args
    assert "reason" not in call_kwargs.kwargs


@pytest.mark.asyncio
async def test_model_decides_file_path_outside_workspace_user_denies(tmp_path) -> None:
    """workspace 外路径，用户拒绝审批 → 返回错误，不执行。"""
    from pathlib import Path
    from unittest.mock import patch
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock()
    reviewer = MagicMock()
    approval_manager = MagicMock()
    approval_manager.request_approval = AsyncMock(return_value=False)

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool, \
         patch("sebastian.permissions.gate.resolve_path", return_value=Path("/tmp/evil.txt")), \
         patch("sebastian.permissions.gate.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Write",
            {"file_path": "/tmp/evil.txt", "content": "x", "reason": "bad"},
            _make_context("write"),
        )

    assert not result.ok
    assert "拒绝" in (result.error or "")
    registry.call.assert_not_called()


@pytest.mark.asyncio
async def test_model_decides_file_path_inside_workspace_uses_reviewer(tmp_path) -> None:
    """file_path 在 workspace 内 → 走原有 reviewer 流程，不触发 workspace 拦截。"""
    from pathlib import Path
    from unittest.mock import patch
    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "output.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    reviewer.review = AsyncMock(return_value=ReviewDecision(decision="proceed", explanation=""))
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool, \
         patch("sebastian.permissions.gate.resolve_path", return_value=inside_path), \
         patch("sebastian.permissions.gate.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Write",
            {"file_path": "output.txt", "content": "data", "reason": "write in workspace"},
            _make_context("write a file"),
        )

    assert result.ok
    reviewer.review.assert_awaited_once()
    approval_manager.request_approval.assert_not_called()


@pytest.mark.asyncio
async def test_low_tier_with_file_path_no_workspace_check(tmp_path) -> None:
    """LOW tier（Read）含 file_path → 不触发 workspace 检查，直接执行。"""
    from pathlib import Path
    from unittest.mock import patch
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="content"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call(
            "Read",
            {"file_path": "/etc/hosts"},
            _make_context("read system file"),
        )

    assert result.ok
    reviewer.review.assert_not_called()
    approval_manager.request_approval.assert_not_called()
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_policy_gate.py::test_model_decides_file_path_outside_workspace_skips_reviewer -v
```

Expected: FAIL

- [ ] **Step 3: 修改 `gate.py`**

在 `sebastian/permissions/gate.py` 文件顶部新增 import：

```python
from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.config import settings
```

在 `call()` 方法里，`token = _current_tool_ctx.set(context)` 之后，`try:` 块内的 tier 判断之前，插入：

```python
        # Workspace 边界检查：MODEL_DECIDES 工具含 file_path 时，路径在 workspace 外直接请求用户审批
        if tier == PermissionTier.MODEL_DECIDES and "file_path" in inputs:
            resolved = resolve_path(inputs["file_path"])
            if not resolved.is_relative_to(settings.workspace_dir):
                clean_inputs = {k: v for k, v in inputs.items() if k != "reason"}
                granted = await self._approval_manager.request_approval(
                    approval_id=uuid.uuid4().hex,
                    task_id=context.task_id or "",
                    tool_name=tool_name,
                    tool_input=clean_inputs,
                    reason=f"操作路径 '{resolved}' 在 workspace 外，需要用户确认。",
                    session_id=context.session_id or "",
                )
                if granted:
                    return await self._registry.call(tool_name, **clean_inputs)
                return ToolResult(ok=False, error="用户拒绝了 workspace 外的文件操作。")
```

- [ ] **Step 4: 运行所有 PolicyGate 测试**

```bash
pytest tests/unit/test_policy_gate.py -v
```

Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/permissions/gate.py tests/unit/test_policy_gate.py
git commit -m "feat(permissions): PolicyGate 新增 workspace 边界前置检查"
```

---

### Task 6: PermissionReviewer 动态注入 workspace_dir

**Files:**
- Modify: `sebastian/permissions/reviewer.py`
- Modify: `tests/unit/test_permission_reviewer.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_permission_reviewer.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_reviewer_system_prompt_contains_workspace_dir() -> None:
    """review() 构建的 system prompt 包含真实 workspace_dir 路径。"""
    from unittest.mock import patch
    from pathlib import Path
    from sebastian.permissions.reviewer import PermissionReviewer

    fake_workspace = Path("/fake/workspace/path")
    captured_prompts: list[str] = []

    provider = MagicMock()

    async def _capturing_stream(*args, **kwargs):
        captured_prompts.append(kwargs.get("system", ""))
        yield TextDelta(block_id="0", delta='{"decision": "proceed", "explanation": ""}')

    provider.stream = _capturing_stream
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)

    with patch("sebastian.permissions.reviewer.settings") as mock_settings:
        mock_settings.workspace_dir = fake_workspace
        await reviewer.review(
            tool_name="Bash",
            tool_input={"command": "echo hello"},
            reason="test",
            task_goal="test goal",
        )

    assert captured_prompts, "stream was not called"
    assert str(fake_workspace) in captured_prompts[0]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_permission_reviewer.py::test_reviewer_system_prompt_contains_workspace_dir -v
```

Expected: FAIL — 当前 prompt 不含 workspace_dir

- [ ] **Step 3: 修改 `reviewer.py`**

将模块级常量 `_SYSTEM_PROMPT` 改名为 `_SYSTEM_PROMPT_TEMPLATE` 并加入 workspace 规则占位符，在 `review()` 内动态格式化：

```python
# sebastian/permissions/reviewer.py
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sebastian.config import settings
from sebastian.core.stream_events import TextDelta
from sebastian.permissions.types import ReviewDecision

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a security reviewer for an AI assistant system.
Your job: decide whether a tool call should proceed directly or require user approval.

Rules:
- PROCEED if: the action is reversible, read-only, or clearly aligned with the stated task goal
- ESCALATE if: the action is destructive, irreversible, accesses sensitive data,
  or the stated reason does not match the task goal
- If the tool is `Bash` and the command writes, modifies, moves, or deletes files \
outside the workspace directory (`{workspace_dir}`), you MUST ESCALATE.
- When in doubt, ESCALATE

Respond ONLY in valid JSON:
{{"decision": "proceed" | "escalate", "explanation": "..."}}
explanation must be in the user's language, written for a non-technical user.
When decision is "proceed", explanation is an empty string.\
"""


class PermissionReviewer:
    """Stateless LLM reviewer for MODEL_DECIDES tool calls."""

    def __init__(self, llm_registry: LLMProviderRegistry) -> None:
        self._llm_registry = llm_registry

    async def review(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        task_goal: str,
    ) -> ReviewDecision:
        """Return a proceed/escalate decision for the given tool call."""
        try:
            provider, model = await self._llm_registry.get_default_with_model()
        except RuntimeError:
            logger.warning(
                "PermissionReviewer: no LLM provider configured, defaulting to escalate"
            )
            return ReviewDecision(
                decision="escalate",
                explanation="未配置 LLM Provider，无法自动审查工具调用，请人工批准。",
            )

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(workspace_dir=settings.workspace_dir)

        user_content = (
            f"Task goal: {task_goal}\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
            f"Model's reason: {reason}"
        )
        try:
            text = ""
            async for event in provider.stream(
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                tools=[],
                model=model,
                max_tokens=2048,
            ):
                if isinstance(event, TextDelta):
                    text += event.delta
            if not text.strip():
                logger.warning("PermissionReviewer: LLM returned empty response, defaulting to escalate")
                return ReviewDecision(
                    decision="escalate",
                    explanation="审查响应为空，请人工批准。",
                )
            logger.info("PermissionReviewer raw response: %r", text)
            data = json.loads(_extract_json(text))
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


def _extract_json(text: str) -> str:
    """Extract JSON object from text, stripping markdown code fences if present."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        return text[start:end]
    return text.strip()
```

注意：`_SYSTEM_PROMPT_TEMPLATE` 中的 JSON 示例用 `{{` `}}` 转义花括号，避免 `.format()` 误解析。

- [ ] **Step 4: 运行所有 reviewer 测试**

```bash
pytest tests/unit/test_permission_reviewer.py -v
```

Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/permissions/reviewer.py tests/unit/test_permission_reviewer.py
git commit -m "feat(permissions): PermissionReviewer 动态注入 workspace_dir 到 system prompt"
```

---

### Task 7: BaseAgent 新增 `_guidelines_section()`

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `tests/unit/test_base_agent.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_base_agent.py` 末尾追加：

```python
def test_build_system_prompt_contains_guidelines_section() -> None:
    """build_system_prompt() 包含 guidelines section，含 workspace_dir 路径。"""
    from pathlib import Path
    from unittest.mock import MagicMock, patch
    from sebastian.core.base_agent import BaseAgent

    class TestAgent(BaseAgent):
        name = "test"

    fake_workspace = Path("/fake/workspace")

    gate = MagicMock()
    gate.get_tool_specs.return_value = []
    gate.get_skill_specs.return_value = []

    with patch("sebastian.core.base_agent.settings") as mock_settings:
        mock_settings.workspace_dir = fake_workspace
        mock_settings.sebastian_owner_name = "Eric"
        mock_settings.sebastian_model = "claude-opus-4-6"
        agent = TestAgent(gate, MagicMock())
        prompt = agent.system_prompt

    assert "Operation Guidelines" in prompt
    assert str(fake_workspace) in prompt
    assert "Read" in prompt
    assert "Write" in prompt
    assert "Glob" in prompt
    assert "Grep" in prompt


def test_guidelines_section_appears_before_tools_section() -> None:
    """guidelines section 必须在 tools section 之前出现。"""
    from pathlib import Path
    from unittest.mock import MagicMock, patch
    from sebastian.core.base_agent import BaseAgent

    class TestAgent(BaseAgent):
        name = "test"

    gate = MagicMock()
    gate.get_tool_specs.return_value = [
        {"name": "Read", "description": "Read a file"}
    ]
    gate.get_skill_specs.return_value = []

    with patch("sebastian.core.base_agent.settings") as mock_settings:
        mock_settings.workspace_dir = Path("/fake/ws")
        mock_settings.sebastian_owner_name = "Eric"
        mock_settings.sebastian_model = "claude-opus-4-6"
        agent = TestAgent(gate, MagicMock())
        prompt = agent.system_prompt

    guidelines_pos = prompt.index("Operation Guidelines")
    tools_pos = prompt.index("Available Tools")
    assert guidelines_pos < tools_pos
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/test_base_agent.py::test_build_system_prompt_contains_guidelines_section tests/unit/test_base_agent.py::test_guidelines_section_appears_before_tools_section -v
```

Expected: FAIL

- [ ] **Step 3: 修改 `base_agent.py`**

在 `BaseAgent` 类中新增方法（放在 `_tools_section` 之前）：

```python
def _guidelines_section(self) -> str:
    return (
        "## Operation Guidelines\n\n"
        f"- Workspace directory: `{settings.workspace_dir}`. "
        "Use relative paths for all file operations — they resolve to workspace automatically.\n"
        "- Prefer structured tools over shell commands for file operations:\n"
        "  - Use `Read` instead of `bash cat`\n"
        "  - Use `Write` / `Edit` instead of `bash sed`, `bash tee`, or redirect (`>`)\n"
        "  - Use `Glob` instead of `bash find`\n"
        "  - Use `Grep` instead of `bash grep` / `bash rg`\n"
        "- Operations outside the workspace directory require user approval. "
        "Always explain why you need to access a path outside workspace before requesting."
    )
```

修改 `build_system_prompt()` 在 `_persona_section()` 之后插入 `_guidelines_section()`：

```python
def build_system_prompt(
    self,
    gate: PolicyGate,
    agent_registry: dict[str, object] | None = None,
) -> str:
    sections = [
        self._persona_section(),
        self._guidelines_section(),
        self._tools_section(gate),
        self._skills_section(gate),
        self._agents_section(agent_registry),
        self._knowledge_section(),
    ]
    return "\n\n".join(s for s in sections if s)
```

- [ ] **Step 4: 运行所有 base_agent 测试**

```bash
pytest tests/unit/test_base_agent.py tests/unit/test_base_agent_knowledge.py tests/unit/test_base_agent_provider.py tests/unit/test_prompt_builder.py -v
```

Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent.py
git commit -m "feat(agent): BaseAgent 新增 _guidelines_section() 注入全局操作规范"
```

---

### Task 8: 全量测试 + 最终提交

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/unit/ -v --tb=short
```

Expected: 全部 passed，无 regression

- [ ] **Step 2: Lint 检查**

```bash
ruff check sebastian/capabilities/tools/_path_utils.py sebastian/capabilities/tools/write/__init__.py sebastian/capabilities/tools/edit/__init__.py sebastian/capabilities/tools/read/__init__.py sebastian/permissions/gate.py sebastian/permissions/reviewer.py sebastian/core/base_agent.py
```

Expected: 无错误

- [ ] **Step 3: 类型检查**

```bash
mypy sebastian/capabilities/tools/_path_utils.py sebastian/permissions/gate.py sebastian/permissions/reviewer.py sebastian/core/base_agent.py
```

Expected: 无 error

- [ ] **Step 4: 最终提交**

若以上全部通过，无需额外提交（各 task 已单独 commit）。运行：

```bash
git log --oneline -8
```

确认 7 个 commit 均已就位。

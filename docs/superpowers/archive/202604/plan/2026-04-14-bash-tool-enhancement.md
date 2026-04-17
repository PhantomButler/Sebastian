# Bash Tool Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对齐 Claude Code BashTool 四项核心能力：description 参数、noOutputExpected 静默命令识别、returnCodeInterpretation 语义化退出码、进度心跳（通过 ToolCallContext.progress_cb 推 TOOL_RUNNING 事件）。

**Architecture:** 在 `ToolCallContext` 加 `progress_cb` 回调字段，`base_agent.py` 创建 context 时绑定 `_publish`，bash tool 读取该回调发心跳；output quality 三件套（description/noOutputExpected/returnCodeInterpretation）全在 bash tool 内实现，不改框架层。

**Tech Stack:** Python 3.12+, asyncio, pytest-asyncio, unittest.mock

---

## File Map

| 文件 | 操作 | 职责 |
|------|------|------|
| `sebastian/permissions/types.py` | 修改 | 加 `progress_cb` 字段到 `ToolCallContext` |
| `sebastian/core/base_agent.py` | 修改 | 创建 context 时绑定 `progress_cb` |
| `sebastian/capabilities/tools/bash/__init__.py` | 修改 | description / noOutputExpected / returnCodeInterpretation / 心跳 |
| `tests/unit/identity/test_permission_types.py` | 修改 | 验证 `ToolCallContext.progress_cb` |
| `tests/unit/core/test_base_agent.py` | 修改 | 验证 progress_cb 被绑定且调用 `_publish` |
| `tests/unit/capabilities/test_tools_bash.py` | 修改 | 验证 4 个功能点 |

---

## Task 1：ToolCallContext 增加 progress_cb 字段

**Files:**
- Modify: `sebastian/permissions/types.py`
- Modify: `tests/unit/identity/test_permission_types.py`

- [ ] **Step 1：写失败测试**

在 `tests/unit/identity/test_permission_types.py` 末尾追加：

```python
def test_tool_call_context_progress_cb_defaults_to_none() -> None:
    from sebastian.permissions.types import ToolCallContext

    ctx = ToolCallContext(task_goal="goal", session_id="s1", task_id=None)
    assert ctx.progress_cb is None


def test_tool_call_context_progress_cb_accepts_callable() -> None:
    import asyncio
    from sebastian.permissions.types import ToolCallContext

    async def fake_cb(data: dict) -> None:
        pass

    ctx = ToolCallContext(
        task_goal="goal",
        session_id="s1",
        task_id=None,
        progress_cb=fake_cb,
    )
    assert ctx.progress_cb is fake_cb
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/unit/identity/test_permission_types.py::test_tool_call_context_progress_cb_defaults_to_none -v
```

期望：`FAILED` — `TypeError: ToolCallContext.__init__() got an unexpected keyword argument 'progress_cb'`

- [ ] **Step 3：实现**

打开 `sebastian/permissions/types.py`，在文件头部加 import，并修改 `ToolCallContext`：

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class PermissionTier(StrEnum):
    LOW = "low"
    MODEL_DECIDES = "model_decides"
    HIGH_RISK = "high_risk"


@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = field(
        default=None, repr=False
    )


@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str
```

注意：`field(default=None, repr=False)` 避免 dataclass 在打印 context 时把回调函数也输出。

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/unit/identity/test_permission_types.py -v
```

期望：全部 `PASSED`。

- [ ] **Step 5：提交**

```bash
git add sebastian/permissions/types.py tests/unit/identity/test_permission_types.py
git commit -m "feat(permissions): ToolCallContext 增加 progress_cb 回调字段"
```

---

## Task 2：base_agent 绑定 progress_cb

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `tests/unit/core/test_base_agent.py`

- [ ] **Step 1：写失败测试**

在 `tests/unit/core/test_base_agent.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_base_agent_progress_cb_calls_publish(tmp_path: Path) -> None:
    """progress_cb 被调用时应该触发 _publish(session_id, TOOL_RUNNING, data)."""
    import dataclasses
    from unittest.mock import AsyncMock, patch

    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import ToolCallReady
    from sebastian.core.tool_context import _current_tool_ctx
    from sebastian.core.types import Session
    from sebastian.core.types import ToolResult as CoreToolResult
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir)
    await store.create_session(
        Session(id="prog-test", agent_type="sebastian", title="Test")
    )
    agent = TestAgent(MagicMock(), store)

    captured_ctx = {}

    async def fake_tool(name, inputs, context):
        # 捕获 context，验证 progress_cb 已设置
        captured_ctx["ctx"] = context
        # 调用 progress_cb，模拟心跳
        if context.progress_cb:
            await context.progress_cb({"elapsed_seconds": 5})
        return CoreToolResult(ok=True, output="done")

    publish_calls = []

    async def fake_publish(session_id, event_type, data):
        publish_calls.append((session_id, event_type, data))

    agent._publish = fake_publish  # type: ignore[method-assign]

    async def fake_stream(*args, **kwargs):
        yield ToolCallReady(
            block_id="b0_0",
            tool_id="toolu_001",
            name="Bash",
            inputs={"command": "echo hi", "reason": "test"},
        )

    agent._loop.stream = fake_stream  # type: ignore[attr-defined]
    agent._gate.call = fake_tool  # type: ignore[attr-defined]

    await agent.run("test", "prog-test")

    # 验证 context 有 progress_cb
    assert "ctx" in captured_ctx
    assert captured_ctx["ctx"].progress_cb is not None

    # 验证调用 progress_cb 后确实触发了 TOOL_RUNNING publish
    tool_running_calls = [
        c for c in publish_calls if c[1] == EventType.TOOL_RUNNING
    ]
    # 应该有至少两次：一次是 base_agent 自己发的，一次是 progress_cb 触发的
    # base_agent 在 ToolCallReady 时发 TOOL_RUNNING（已有逻辑），
    # progress_cb 再发一次（带 elapsed_seconds）
    progress_calls = [c for c in tool_running_calls if "elapsed_seconds" in c[2]]
    assert len(progress_calls) == 1
    assert progress_calls[0][2]["elapsed_seconds"] == 5
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/unit/core/test_base_agent.py::test_base_agent_progress_cb_calls_publish -v
```

期望：`FAILED` — `AssertionError: assert 0 == 1`（`progress_calls` 为空，因为 progress_cb 未设置）

- [ ] **Step 3：实现**

打开 `sebastian/core/base_agent.py`，在文件顶部 import 处加：

```python
import functools
```

找到创建 `ToolCallContext` 的代码（搜索 `context = ToolCallContext(`），修改如下：

```python
context = ToolCallContext(
    task_goal=self._current_task_goals.get(session_id, ""),
    session_id=session_id,
    task_id=task_id,
    agent_type=agent_context,
    depth=getattr(self, "_current_depth", {}).get(session_id, 1),
    progress_cb=functools.partial(
        self._publish, session_id, EventType.TOOL_RUNNING
    ),
)
```

`functools.partial(self._publish, session_id, EventType.TOOL_RUNNING)` 返回一个 callable，调用时传入 `data` dict，等价于 `await self._publish(session_id, EventType.TOOL_RUNNING, data)`。

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/unit/core/test_base_agent.py -v
```

期望：全部 `PASSED`。

- [ ] **Step 5：提交**

```bash
git add sebastian/core/base_agent.py tests/unit/core/test_base_agent.py
git commit -m "feat(agent): base_agent 创建 ToolCallContext 时绑定 progress_cb"
```

---

## Task 3：bash tool output quality（description / noOutputExpected / returnCodeInterpretation）

**Files:**
- Modify: `sebastian/capabilities/tools/bash/__init__.py`
- Modify: `tests/unit/capabilities/test_tools_bash.py`

- [ ] **Step 1：写失败测试**

在 `tests/unit/capabilities/test_tools_bash.py` 末尾追加：

```python
# ── description ──────────────────────────────────────────────────────────────

async def test_bash_description_accepted_as_parameter() -> None:
    """description 参数不影响执行结果。"""
    r = await bash(command="printf 'hi'", description="Print hi")
    assert r.ok
    assert r.display == "hi"


# ── noOutputExpected ──────────────────────────────────────────────────────────

async def test_bash_silent_command_empty_hint_is_done() -> None:
    """mv 等静默命令无输出时 empty_hint 应为 'Done'。"""
    import os, tempfile
    with tempfile.NamedTemporaryFile(delete=False) as f:
        src = f.name
    dst = src + "_moved"
    try:
        r = await bash(command=f"mv {src} {dst}")
        assert r.ok
        assert r.empty_hint == "Done"
    finally:
        if os.path.exists(dst):
            os.unlink(dst)


async def test_bash_non_silent_command_empty_hint_contains_exit_code() -> None:
    """非静默命令无输出时 empty_hint 含退出码信息。"""
    r = await bash(command="true")  # true 返回 0，无输出
    assert r.ok
    assert r.empty_hint is not None
    assert "0" in r.empty_hint


# ── returnCodeInterpretation ──────────────────────────────────────────────────
# 注意：_interpret_exit_code 只匹配命令行第一个 token。
# 测试用例必须以 grep/diff 等作为第一个 token，pipeline 中间的子命令不会被识别。

async def test_bash_grep_exit_1_interpretation_in_output() -> None:
    """grep 作为第一个 token 且找不到匹配时，output 含语义字段，empty_hint 含解释。"""
    r = await bash(command="grep 'NOMATCH_XYZ' /dev/null")
    assert r.ok
    assert r.output["returncode"] == 1
    assert r.output["returncode_interpretation"] == "No matches found (not an error)"
    # 无 stdout/stderr 时 empty_hint 含语义解释
    assert r.empty_hint is not None
    assert "No matches found" in r.empty_hint


async def test_bash_diff_exit_1_interpretation_in_output(tmp_path) -> None:
    """diff 比较不同文件返回 1，output 含语义字段，display 含解释后缀。"""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("hello\n")
    f2.write_text("world\n")
    r = await bash(command=f"diff {f1} {f2}")
    assert r.ok
    assert r.output["returncode"] == 1
    assert r.output["returncode_interpretation"] == "Files differ (not an error)"
    # diff 有 stdout 输出，interpretation 追加到 display
    assert r.display is not None
    assert "Files differ" in r.display


async def test_bash_grep_exit_0_no_interpretation() -> None:
    """grep 找到匹配返回 0，output 不含 returncode_interpretation 字段。"""
    import os, tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello\n")
        fname = f.name
    try:
        r = await bash(command=f"grep 'hello' {fname}")
        assert r.ok
        assert r.output["returncode"] == 0
        assert "returncode_interpretation" not in r.output
    finally:
        os.unlink(fname)
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/unit/capabilities/test_tools_bash.py -k "silent or interpretation or description" -v
```

期望：多个 `FAILED`。

- [ ] **Step 3：实现**

将 `sebastian/capabilities/tools/bash/__init__.py` 替换为以下内容：

```python
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sebastian.config import settings
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 10_000
_DEFAULT_TIMEOUT = 600
_HEARTBEAT_INTERVAL_S: float = 3.0

# 执行后通常无 stdout 的命令——无输出时返回 "Done" 而非 "no output"
_SILENT_COMMANDS: frozenset[str] = frozenset({
    "mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown",
    "chgrp", "touch", "ln", "cd", "export", "unset", "wait",
})

# 退出码具有特殊语义的命令：exit code → 人类可读说明
# 仅匹配命令行第一个 token（不处理 pipeline 中间的子命令）
_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep":  {1: "No matches found (not an error)"},
    "find":  {1: "No matches found (not an error)"},
    "diff":  {1: "Files differ (not an error)"},
    "test":  {1: "Condition false (not an error)"},
    "[":     {1: "Condition false (not an error)"},
}


def _is_silent_command(command: str) -> bool:
    """返回 True 当命令第一个 token 在 _SILENT_COMMANDS 白名单中。"""
    base = command.strip().split()[0] if command.strip() else ""
    return base in _SILENT_COMMANDS


def _interpret_exit_code(command: str, returncode: int) -> str | None:
    """返回退出码的语义解释。仅匹配命令行第一个 token，无解释时返回 None。"""
    base = command.strip().split()[0] if command.strip() else ""
    return _EXIT_CODE_SEMANTICS.get(base, {}).get(returncode)


async def _heartbeat(
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    """每隔 _HEARTBEAT_INTERVAL_S 秒调用一次 progress_cb，直到 stop_event 被设置。"""
    start = time.monotonic()
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_HEARTBEAT_INTERVAL_S)
            return  # stop_event 已 set，命令结束
        except asyncio.TimeoutError:
            elapsed = int(time.monotonic() - start)
            try:
                await progress_cb({"elapsed_seconds": elapsed})
            except Exception:
                logger.warning("bash heartbeat publish failed", exc_info=True)


@tool(
    name="Bash",
    description=(
        "Execute a shell command. Returns stdout, stderr, and return code. "
        "Non-zero return codes are not automatically errors. "
        "Default timeout is 600 seconds."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def bash(
    command: str,
    timeout: int | None = None,
    description: str | None = None,
) -> ToolResult:
    logger.debug("bash[%s]: %s", description or command[:60], command)

    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    workspace = settings.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workspace),
    )

    # 进度心跳：仅当 ToolCallContext 有 progress_cb 时启动
    ctx = get_tool_context()
    stop_event = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    if ctx is not None and ctx.progress_cb is not None:
        heartbeat_task = asyncio.create_task(
            _heartbeat(ctx.progress_cb, stop_event)
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(effective_timeout),
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(ok=False, error=f"Command timed out after {effective_timeout}s")
    finally:
        stop_event.set()
        if heartbeat_task is not None:
            await heartbeat_task

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    truncated = False

    if len(stdout) > _MAX_OUTPUT_CHARS:
        stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True
    if len(stderr) > _MAX_OUTPUT_CHARS:
        stderr = stderr[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True

    # 语义化退出码：写入 output dict，LLM 可直接读取
    interpretation = _interpret_exit_code(command, proc.returncode)

    # output dict：LLM 通过 json.dumps 看到的内容
    output: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": proc.returncode,
        "truncated": truncated,
    }
    if interpretation:
        output["returncode_interpretation"] = interpretation

    # empty_hint：无任何输出时给 LLM 的语义化提示（优先于 output dict）
    empty_hint: str | None = None
    if not stdout and not stderr:
        if interpretation:
            empty_hint = f"exit {proc.returncode}: {interpretation}"
        elif _is_silent_command(command):
            empty_hint = "Done"
        else:
            empty_hint = f"Command exited with code {proc.returncode}, no output"

    # display：用户/日志可见的字符串，含 stderr 和语义解释后缀
    if proc.returncode != 0 and stderr:
        display: str | None = (
            f"{stdout}\n--- stderr ---\n{stderr}" if stdout else f"--- stderr ---\n{stderr}"
        )
    else:
        display = stdout or None

    if interpretation and (stdout or stderr):
        suffix = f"(exit {proc.returncode}: {interpretation})"
        display = f"{display}\n{suffix}" if display else suffix

    return ToolResult(
        ok=True,
        output=output,
        display=display,
        empty_hint=empty_hint,
    )
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/unit/capabilities/test_tools_bash.py -v
```

期望：全部 `PASSED`。

- [ ] **Step 5：提交**

```bash
git add sebastian/capabilities/tools/bash/__init__.py tests/unit/capabilities/test_tools_bash.py
git commit -m "feat(bash): description / noOutputExpected / returnCodeInterpretation"
```

---

## Task 4：bash 进度心跳测试

> 心跳代码已在 Task 3 实现，本任务补充专项测试并验证。

**Files:**
- Modify: `tests/unit/capabilities/test_tools_bash.py`

- [ ] **Step 1：写失败测试**

在 `tests/unit/capabilities/test_tools_bash.py` 末尾追加：

```python
# ── heartbeat ─────────────────────────────────────────────────────────────────

async def test_bash_heartbeat_fires_on_long_command() -> None:
    """命令耗时超过心跳间隔时，progress_cb 应被调用。"""
    from unittest.mock import patch

    from sebastian.capabilities.tools.bash import bash as bash_tool
    from sebastian.core.tool_context import _current_tool_ctx
    from sebastian.permissions.types import ToolCallContext

    calls: list[dict] = []

    async def fake_cb(data: dict) -> None:
        calls.append(data)

    ctx = ToolCallContext(
        task_goal="test", session_id="s1", task_id=None, progress_cb=fake_cb
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.bash._HEARTBEAT_INTERVAL_S", 0.05):
            await bash_tool(command="sleep 0.2")
    finally:
        _current_tool_ctx.reset(token)

    assert len(calls) >= 1
    assert all("elapsed_seconds" in c for c in calls)
    assert calls[0]["elapsed_seconds"] >= 0


async def test_bash_heartbeat_does_not_fire_on_short_command() -> None:
    """命令在心跳间隔内完成时，progress_cb 不应被调用。"""
    from unittest.mock import patch

    from sebastian.capabilities.tools.bash import bash as bash_tool
    from sebastian.core.tool_context import _current_tool_ctx
    from sebastian.permissions.types import ToolCallContext

    calls: list[dict] = []

    async def fake_cb(data: dict) -> None:
        calls.append(data)

    ctx = ToolCallContext(
        task_goal="test", session_id="s1", task_id=None, progress_cb=fake_cb
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.bash._HEARTBEAT_INTERVAL_S", 10.0):
            await bash_tool(command="echo hi")
    finally:
        _current_tool_ctx.reset(token)

    assert calls == []


async def test_bash_heartbeat_skipped_when_no_ctx() -> None:
    """无 ToolCallContext 时（如单测直接调用），命令正常执行，无副作用。"""
    from sebastian.core.tool_context import _current_tool_ctx

    # 确保 contextvar 为 None
    token = _current_tool_ctx.set(None)
    try:
        r = await bash(command="printf 'ok'")
    finally:
        _current_tool_ctx.reset(token)

    assert r.ok
    assert r.display == "ok"


async def test_bash_heartbeat_publish_failure_does_not_break_command() -> None:
    """progress_cb 抛异常时命令应正常完成，不向上传播异常。"""
    from unittest.mock import patch

    from sebastian.capabilities.tools.bash import bash as bash_tool
    from sebastian.core.tool_context import _current_tool_ctx
    from sebastian.permissions.types import ToolCallContext

    async def failing_cb(data: dict) -> None:
        raise RuntimeError("publish exploded")

    ctx = ToolCallContext(
        task_goal="test", session_id="s1", task_id=None, progress_cb=failing_cb
    )
    token = _current_tool_ctx.set(ctx)
    try:
        with patch("sebastian.capabilities.tools.bash._HEARTBEAT_INTERVAL_S", 0.05):
            r = await bash_tool(command="sleep 0.2")
    finally:
        _current_tool_ctx.reset(token)

    assert r.ok  # 命令本身不受影响
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/unit/capabilities/test_tools_bash.py -k "heartbeat" -v
```

期望：多个 `FAILED`（心跳相关函数尚未被测试到，或 `_HEARTBEAT_INTERVAL_S` patch 路径不对）。

> 如果测试已通过（Task 3 实现完整），跳到 Step 4。

- [ ] **Step 3：如有失败，检查 patch 路径**

确认 `sebastian.capabilities.tools.bash._HEARTBEAT_INTERVAL_S` 是 `_heartbeat` 函数读取的模块级常量。如果测试仍失败，检查 `_heartbeat` 内是否直接用 `_HEARTBEAT_INTERVAL_S`（已在 Task 3 实现中正确引用）。

- [ ] **Step 4：运行全量测试**

```bash
pytest tests/unit/capabilities/test_tools_bash.py -v
```

期望：全部 `PASSED`。

- [ ] **Step 5：运行全量单测，确认无回归**

```bash
pytest tests/unit/ -v --tb=short
```

期望：全部 `PASSED`，无新增失败。

- [ ] **Step 6：提交**

```bash
git add tests/unit/capabilities/test_tools_bash.py
git commit -m "test(bash): 补充 heartbeat 专项测试"
```

---

## 验收检查

完成后运行：

```bash
pytest tests/unit/ -v --tb=short
```

确认以下测试全部通过：

- `test_permission_types.py::test_tool_call_context_progress_cb_defaults_to_none`
- `test_permission_types.py::test_tool_call_context_progress_cb_accepts_callable`
- `test_base_agent.py::test_base_agent_progress_cb_calls_publish`
- `test_tools_bash.py::test_bash_description_accepted_as_parameter`
- `test_tools_bash.py::test_bash_silent_command_empty_hint_is_done`
- `test_tools_bash.py::test_bash_non_silent_command_empty_hint_contains_exit_code`
- `test_tools_bash.py::test_bash_grep_exit_1_adds_interpretation`
- `test_tools_bash.py::test_bash_diff_exit_1_adds_interpretation`
- `test_tools_bash.py::test_bash_grep_exit_0_no_interpretation`
- `test_tools_bash.py::test_bash_heartbeat_fires_on_long_command`
- `test_tools_bash.py::test_bash_heartbeat_does_not_fire_on_short_command`
- `test_tools_bash.py::test_bash_heartbeat_skipped_when_no_ctx`
- `test_tools_bash.py::test_bash_heartbeat_publish_failure_does_not_break_command`

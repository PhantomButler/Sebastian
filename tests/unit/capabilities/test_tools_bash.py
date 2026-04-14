from __future__ import annotations

import pytest

from sebastian.capabilities.tools.bash import bash

pytestmark = pytest.mark.asyncio


async def test_bash_display_is_stdout_on_success() -> None:
    r = await bash(command="printf 'hello'")
    assert r.ok
    assert r.display == "hello"


async def test_bash_display_appends_stderr_on_nonzero_exit() -> None:
    r = await bash(command="printf 'boom' >&2; exit 1")
    assert r.ok  # Bash tool 的 ok 不等于 returncode==0
    assert r.display is not None
    assert "--- stderr ---" in r.display
    assert "boom" in r.display


async def test_bash_display_omits_stderr_on_zero_exit() -> None:
    r = await bash(command="printf 'out'; printf 'noise' >&2; exit 0")
    assert r.ok
    assert r.display == "out"
    assert "noise" not in (r.display or "")


# ── description ──────────────────────────────────────────────────────────────

async def test_bash_description_accepted_as_parameter() -> None:
    """description 参数不影响执行结果。"""
    r = await bash(command="printf 'hi'", description="Print hi")
    assert r.ok
    assert r.display == "hi"


async def test_bash_description_logged() -> None:
    """description 出现在 logger.debug 调用中，但不泄露到 output/display。"""
    from unittest.mock import patch

    with patch("sebastian.capabilities.tools.bash.logger") as mock_logger:
        r = await bash(command="echo hello", description="build the project")

    debug_calls = mock_logger.debug.call_args_list
    assert any("build the project" in str(call) for call in debug_calls)
    assert "build the project" not in str(r.output)
    assert "build the project" not in (r.display or "")


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

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

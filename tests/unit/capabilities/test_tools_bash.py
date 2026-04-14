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

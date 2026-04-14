from __future__ import annotations

import time

import pytest


@pytest.fixture()
def isolated_registry():
    import sebastian.capabilities.tools.glob  # noqa: F401 — ensures Glob is registered
    from sebastian.core import tool as tool_module

    saved = dict(tool_module._tools)
    yield
    tool_module._tools.clear()
    tool_module._tools.update(saved)


@pytest.mark.asyncio
async def test_glob_finds_matching_files(tmp_path, isolated_registry) -> None:
    from sebastian.core.tool import call_tool

    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "c.txt").write_text("c")

    result = await call_tool("Glob", pattern="*.py", path=str(tmp_path))
    assert result.ok
    assert set(result.output["files"]) == {"a.py", "b.py"}
    assert result.output["count"] == 2
    assert result.output["truncated"] is False


@pytest.mark.asyncio
async def test_glob_sorted_by_mtime(tmp_path, isolated_registry) -> None:
    from sebastian.core.tool import call_tool

    old_file = tmp_path / "old.py"
    old_file.write_text("old")
    time.sleep(0.05)
    new_file = tmp_path / "new.py"
    new_file.write_text("new")

    result = await call_tool("Glob", pattern="*.py", path=str(tmp_path))
    assert result.ok
    assert result.output["files"][0] == "new.py"
    assert result.output["files"][1] == "old.py"


@pytest.mark.asyncio
async def test_glob_truncates_at_100(tmp_path, isolated_registry) -> None:
    from sebastian.core.tool import call_tool

    for i in range(110):
        (tmp_path / f"file_{i}.py").write_text(str(i))

    result = await call_tool("Glob", pattern="*.py", path=str(tmp_path))
    assert result.ok
    assert result.output["count"] == 100
    assert result.output["truncated"] is True


@pytest.mark.asyncio
async def test_glob_invalid_path_returns_error(tmp_path, isolated_registry) -> None:
    from sebastian.core.tool import call_tool

    nonexistent = str(tmp_path / "nonexistent")
    result = await call_tool("Glob", pattern="*.py", path=nonexistent)
    assert not result.ok
    assert "not a directory" in result.error.lower()

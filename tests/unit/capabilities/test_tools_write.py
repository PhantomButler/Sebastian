from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_registry():
    import sebastian.capabilities.tools.write  # noqa: F401 — ensures tool is registered
    from sebastian.capabilities.tools import _file_state
    from sebastian.core import tool as tool_module

    _file_state._file_mtimes.clear()
    saved = dict(tool_module._tools)
    yield
    tool_module._tools.clear()
    tool_module._tools.update(saved)


@pytest.mark.asyncio
async def test_write_creates_new_file(tmp_path):
    from sebastian.core.tool import call_tool

    f = tmp_path / "new.txt"
    result = await call_tool("Write", file_path=str(f), content="hello world")
    assert result.ok
    assert result.output["action"] == "created"
    assert f.read_text() == "hello world"


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(tmp_path):
    from sebastian.core.tool import call_tool

    f = tmp_path / "a" / "b" / "c.txt"
    result = await call_tool("Write", file_path=str(f), content="deep")
    assert result.ok
    assert f.read_text() == "deep"


@pytest.mark.asyncio
async def test_write_existing_file_requires_read_first(tmp_path):
    from sebastian.core.tool import call_tool

    f = tmp_path / "existing.txt"
    f.write_text("original")

    result = await call_tool("Write", file_path=str(f), content="new")
    assert not result.ok
    assert "not been read" in result.error


@pytest.mark.asyncio
async def test_write_after_read_succeeds(tmp_path):
    from sebastian.capabilities.tools import _file_state
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
    from sebastian.capabilities.tools import _file_state
    from sebastian.core.tool import call_tool

    f = tmp_path / "stale.txt"
    f.write_text("original")
    _file_state._file_mtimes[str(f)] = 0.0

    result = await call_tool("Write", file_path=str(f), content="new")
    assert not result.ok
    assert "modified externally" in result.error


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

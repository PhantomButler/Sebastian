from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def clear_state():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()
    # Remove write module from cache to force re-import and re-registration
    sys.modules.pop("sebastian.capabilities.tools.write", None)


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

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_state():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()


@pytest.mark.asyncio
async def test_read_basic(tmp_path):
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
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    result = await call_tool("Read", file_path="/nonexistent/path/file.txt")
    assert not result.ok
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_read_directory_returns_error(tmp_path):
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    result = await call_tool("Read", file_path=str(tmp_path))
    assert not result.ok
    assert "directory" in result.error.lower()


@pytest.mark.asyncio
async def test_read_updates_file_state(tmp_path):
    from sebastian.capabilities.tools import _file_state
    from sebastian.capabilities.tools.read import read  # noqa: F401
    from sebastian.core.tool import call_tool

    f = tmp_path / "track.txt"
    f.write_text("content")

    assert str(f) not in _file_state._file_mtimes
    await call_tool("Read", file_path=str(f))
    assert str(f) in _file_state._file_mtimes

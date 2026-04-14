from __future__ import annotations

import pytest

from sebastian.capabilities.tools._loader import load_tools


@pytest.fixture(autouse=True)
def ensure_tools_registered() -> None:
    """Ensure all tools are loaded before each test in this module."""
    load_tools()


@pytest.mark.asyncio
async def test_read_then_write_flow(tmp_path) -> None:
    """Read → Write 正常流程：先读再写，写入成功。"""
    from sebastian.core.tool import call_tool

    target = tmp_path / "hello.txt"
    target.write_text("original content")

    read_result = await call_tool("Read", file_path=str(target))
    assert read_result.ok
    assert "original content" in read_result.output["content"]

    write_result = await call_tool("Write", file_path=str(target), content="new content")
    assert write_result.ok
    assert write_result.output["action"] == "updated"

    read_again = await call_tool("Read", file_path=str(target))
    assert "new content" in read_again.output["content"]


@pytest.mark.asyncio
async def test_write_without_read_is_rejected(tmp_path) -> None:
    """未 Read 过的现有文件，直接 Write 应被拒绝。"""
    from sebastian.capabilities.tools._file_state import _file_mtimes
    from sebastian.core.tool import call_tool

    target = tmp_path / "existing.txt"
    target.write_text("existing content")

    # Ensure this path is not in the mtime cache
    _file_mtimes.pop(str(target), None)

    write_result = await call_tool("Write", file_path=str(target), content="should fail")
    assert not write_result.ok
    assert "Read" in write_result.error


@pytest.mark.asyncio
async def test_write_new_file_without_read(tmp_path) -> None:
    """新文件（不存在）可以无需 Read 直接 Write。"""
    from sebastian.core.tool import call_tool

    new_file = tmp_path / "brand_new.txt"
    assert not new_file.exists()

    write_result = await call_tool("Write", file_path=str(new_file), content="brand new")
    assert write_result.ok
    assert write_result.output["action"] == "created"
    assert new_file.read_text() == "brand new"


@pytest.mark.asyncio
async def test_read_edit_read_flow(tmp_path) -> None:
    """Read → Edit → Read 验证内容变更。"""
    from sebastian.core.tool import call_tool

    target = tmp_path / "code.py"
    target.write_text("def hello():\n    return 'world'\n")

    read_result = await call_tool("Read", file_path=str(target))
    assert read_result.ok

    edit_result = await call_tool(
        "Edit",
        file_path=str(target),
        old_string="return 'world'",
        new_string="return 'sebastian'",
    )
    assert edit_result.ok
    assert edit_result.output["replacements"] == 1

    read_again = await call_tool("Read", file_path=str(target))
    assert "return 'sebastian'" in read_again.output["content"]
    assert "return 'world'" not in read_again.output["content"]


@pytest.mark.asyncio
async def test_glob_finds_files(tmp_path) -> None:
    """Glob 能找到匹配模式的文件。"""
    from sebastian.core.tool import call_tool

    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "c.txt").write_text("c")

    result = await call_tool("Glob", pattern="*.py", path=str(tmp_path))
    assert result.ok
    assert set(result.output["files"]) == {"a.py", "b.py"}


@pytest.mark.asyncio
async def test_grep_finds_pattern_in_files(tmp_path) -> None:
    """Grep 能在文件中找到指定 pattern。"""
    from sebastian.core.tool import call_tool

    (tmp_path / "src.py").write_text("def main():\n    print('hello sebastian')\n")

    result = await call_tool("Grep", pattern="sebastian", path=str(tmp_path))
    assert result.ok
    assert "sebastian" in result.output["output"]

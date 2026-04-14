from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_registry():
    import sebastian.capabilities.tools.edit  # noqa: F401
    from sebastian.capabilities.tools import _file_state
    from sebastian.core import tool as tool_module

    _file_state._file_mtimes.clear()
    saved = dict(tool_module._tools)
    yield
    tool_module._tools.clear()
    tool_module._tools.update(saved)


@pytest.mark.asyncio
async def test_edit_replaces_unique_match(tmp_path):
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    record_read(str(f))

    result = await call_tool(
        "Edit",
        file_path=str(f),
        old_string="return 1",
        new_string="return 42",
    )
    assert result.ok
    assert result.output["replacements"] == 1
    assert f.read_text() == "def foo():\n    return 42\n"


@pytest.mark.asyncio
async def test_edit_fails_when_not_found(tmp_path):
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    f = tmp_path / "f.txt"
    f.write_text("hello world")
    record_read(str(f))

    result = await call_tool("Edit", file_path=str(f), old_string="xyz", new_string="abc")
    assert not result.ok
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_fails_on_multiple_matches(tmp_path):
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    f = tmp_path / "dup.txt"
    f.write_text("foo\nfoo\nbar\n")
    record_read(str(f))

    result = await call_tool("Edit", file_path=str(f), old_string="foo", new_string="baz")
    assert not result.ok
    assert "2" in result.error  # mentions count


@pytest.mark.asyncio
async def test_edit_replace_all_replaces_all_occurrences(tmp_path):
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    f = tmp_path / "multi.txt"
    f.write_text("foo\nfoo\nfoo\n")
    record_read(str(f))

    result = await call_tool(
        "Edit",
        file_path=str(f),
        old_string="foo",
        new_string="bar",
        replace_all=True,
    )
    assert result.ok
    assert result.output["replacements"] == 3
    assert f.read_text() == "bar\nbar\nbar\n"


@pytest.mark.asyncio
async def test_edit_nonexistent_file():
    from sebastian.core.tool import call_tool

    result = await call_tool(
        "Edit",
        file_path="/no/such/file.txt",
        old_string="x",
        new_string="y",
    )
    assert not result.ok
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_edit_updates_file_state(tmp_path):
    from sebastian.capabilities.tools import _file_state
    from sebastian.core.tool import call_tool

    f = tmp_path / "state.txt"
    f.write_text("hello world")
    _file_state.record_read(str(f))

    await call_tool("Edit", file_path=str(f), old_string="world", new_string="there")
    assert str(f) in _file_state._file_mtimes


@pytest.mark.asyncio
async def test_edit_existing_file_requires_read_first(tmp_path, isolated_registry) -> None:
    """未 Read 过的现有文件，直接 Edit 应被拒绝。"""
    from sebastian.capabilities.tools._file_state import _file_mtimes
    from sebastian.core.tool import call_tool

    target = tmp_path / "code.py"
    target.write_text("def hello():\n    return 'world'\n")

    # Ensure path is not in mtime cache
    _file_mtimes.pop(str(target), None)

    result = await call_tool(
        "Edit",
        file_path=str(target),
        old_string="return 'world'",
        new_string="return 'hacked'",
    )
    assert not result.ok
    assert "Read" in result.error


@pytest.mark.asyncio
async def test_edit_after_read_succeeds(tmp_path, isolated_registry) -> None:
    """Read 过且 mtime 未变，Edit 应该成功。"""
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    target = tmp_path / "code.py"
    target.write_text("def hello():\n    return 'world'\n")

    record_read(str(target))

    result = await call_tool(
        "Edit",
        file_path=str(target),
        old_string="return 'world'",
        new_string="return 'sebastian'",
    )
    assert result.ok
    assert result.output["replacements"] == 1


@pytest.mark.asyncio
async def test_edit_rejects_stale_mtime(tmp_path, isolated_registry) -> None:
    """Read 过但文件被外部修改（mtime 变化），Edit 应被拒绝。"""
    from sebastian.capabilities.tools import _file_state
    from sebastian.core.tool import call_tool

    target = tmp_path / "code.py"
    target.write_text("def hello():\n    return 'world'\n")

    # Simulate "read long ago" with a stale mtime
    _file_state._file_mtimes[str(target)] = 0.0

    result = await call_tool(
        "Edit",
        file_path=str(target),
        old_string="return 'world'",
        new_string="return 'hacked'",
    )
    assert not result.ok
    assert "modified externally" in result.error


@pytest.mark.asyncio
async def test_edit_old_string_with_line_prefix_fails(tmp_path):
    """Edit 不会默默 strip Read 输出的 cat -n 行号前缀 —— 传入带前缀的
    old_string 必须匹配失败，LLM 需自行剥除前缀。"""
    from sebastian.capabilities.tools._file_state import record_read
    from sebastian.core.tool import call_tool

    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    record_read(str(f))

    # 模拟 LLM 误把 Read 输出的 "1\tdef foo():" 直接当 old_string
    result = await call_tool(
        "Edit",
        file_path=str(f),
        old_string="1\tdef foo():",
        new_string="def bar():",
    )
    assert not result.ok
    assert "not found" in result.error.lower()


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

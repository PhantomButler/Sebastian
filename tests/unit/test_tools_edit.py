from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_registry():
    from sebastian.capabilities.tools import _file_state
    from sebastian.core import tool as tool_module

    import sebastian.capabilities.tools.edit  # noqa: F401

    _file_state._file_mtimes.clear()
    saved = dict(tool_module._tools)
    yield
    tool_module._tools.clear()
    tool_module._tools.update(saved)


@pytest.mark.asyncio
async def test_edit_replaces_unique_match(tmp_path):
    from sebastian.core.tool import call_tool

    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")

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
    from sebastian.core.tool import call_tool

    f = tmp_path / "f.txt"
    f.write_text("hello world")

    result = await call_tool(
        "Edit", file_path=str(f), old_string="xyz", new_string="abc"
    )
    assert not result.ok
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_fails_on_multiple_matches(tmp_path):
    from sebastian.core.tool import call_tool

    f = tmp_path / "dup.txt"
    f.write_text("foo\nfoo\nbar\n")

    result = await call_tool(
        "Edit", file_path=str(f), old_string="foo", new_string="baz"
    )
    assert not result.ok
    assert "2" in result.error  # mentions count


@pytest.mark.asyncio
async def test_edit_replace_all_replaces_all_occurrences(tmp_path):
    from sebastian.core.tool import call_tool

    f = tmp_path / "multi.txt"
    f.write_text("foo\nfoo\nfoo\n")

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

    await call_tool("Edit", file_path=str(f), old_string="world", new_string="there")
    assert str(f) in _file_state._file_mtimes

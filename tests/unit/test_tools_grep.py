from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_grep_finds_pattern(tmp_path) -> None:
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.txt").write_text("hello world\nfoo bar\n")
    (tmp_path / "b.txt").write_text("hello again\n")

    result = await call_tool("Grep", pattern="hello", path=str(tmp_path))
    assert result.ok
    assert "hello" in result.output["output"]
    assert result.output["backend"] in ("ripgrep", "grep")
    assert result.output["truncated"] is False


@pytest.mark.asyncio
async def test_grep_no_match_returns_ok(tmp_path) -> None:
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.txt").write_text("hello world\n")

    result = await call_tool("Grep", pattern="zzznomatch", path=str(tmp_path))
    assert result.ok  # non-zero exit is not an error


@pytest.mark.asyncio
async def test_grep_ignore_case(tmp_path) -> None:
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.txt").write_text("HELLO World\n")

    result = await call_tool("Grep", pattern="hello", path=str(tmp_path), ignore_case=True)
    assert result.ok
    assert "HELLO" in result.output["output"]


@pytest.mark.asyncio
async def test_grep_head_limit_truncates(tmp_path) -> None:
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.txt").write_text("\n".join(f"match line {i}" for i in range(50)))

    result = await call_tool("Grep", pattern="match", path=str(tmp_path), head_limit=5)
    assert result.ok
    assert result.output["truncated"] is True
    assert "[truncated]" in result.output["output"]


@pytest.mark.asyncio
async def test_grep_glob_filter(tmp_path) -> None:
    from sebastian.capabilities.tools.grep import grep  # noqa: F401
    from sebastian.core.tool import call_tool

    (tmp_path / "a.py").write_text("target pattern\n")
    (tmp_path / "b.txt").write_text("target pattern\n")

    result = await call_tool("Grep", pattern="target", path=str(tmp_path), glob="*.py")
    assert result.ok
    # Only .py file should appear in results
    assert "a.py" in result.output["output"]
    # b.txt should not appear
    assert "b.txt" not in result.output["output"]

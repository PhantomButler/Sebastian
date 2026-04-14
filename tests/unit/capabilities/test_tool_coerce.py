from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def restore_tool_registry():
    from sebastian.core import tool as tool_module

    saved = dict(tool_module._tools)
    yield
    tool_module._tools.clear()
    tool_module._tools.update(saved)


def test_coerce_str_to_int():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(offset: int) -> ToolResult: ...

    result = _coerce_args(fn, {"offset": "5"})
    assert result["offset"] == 5
    assert isinstance(result["offset"], int)


def test_coerce_str_to_float():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(score: float) -> ToolResult: ...

    result = _coerce_args(fn, {"score": "3.14"})
    assert abs(result["score"] - 3.14) < 1e-9


def test_coerce_str_to_bool_true():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(replace_all: bool) -> ToolResult: ...

    for val in ("true", "True", "TRUE", "1", "yes"):
        assert _coerce_args(fn, {"replace_all": val})["replace_all"] is True


def test_coerce_str_to_bool_false():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(replace_all: bool) -> ToolResult: ...

    for val in ("false", "False", "0", "no"):
        assert _coerce_args(fn, {"replace_all": val})["replace_all"] is False


def test_coerce_optional_int():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(limit: int | None = None) -> ToolResult: ...

    result = _coerce_args(fn, {"limit": "10"})
    assert result["limit"] == 10
    assert isinstance(result["limit"], int)


def test_coerce_non_string_unchanged():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(offset: int) -> ToolResult: ...

    result = _coerce_args(fn, {"offset": 7})
    assert result["offset"] == 7


def test_coerce_invalid_int_keeps_original():
    from sebastian.core.tool import _coerce_args
    from sebastian.core.types import ToolResult

    async def fn(offset: int) -> ToolResult: ...

    result = _coerce_args(fn, {"offset": "abc"})
    assert result["offset"] == "abc"  # 保留原值，让函数本身报错


def test_infer_schema_optional_int_maps_to_integer():
    """int | None 参数应在 JSON schema 中映射为 integer，而非 string。"""
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="schema_test_opt", description="test")
    async def fn(offset: int | None = None) -> ToolResult:
        return ToolResult(ok=True, output=None)

    spec, _ = tool_module._tools["schema_test_opt"]
    assert spec.parameters["properties"]["offset"]["type"] == "integer"
    assert "offset" not in spec.parameters["required"]

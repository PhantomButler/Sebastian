from __future__ import annotations

import pytest

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.types import ToolResult
from sebastian.permissions.types import ALL_TOOLS


def _make_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()

    async def mcp_fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="ok")

    reg.register_mcp_tool(
        "mcp_tool_a",
        {"name": "mcp_tool_a", "description": "tool a", "input_schema": {}},
        mcp_fn,
    )
    reg.register_mcp_tool(
        "mcp_tool_b",
        {"name": "mcp_tool_b", "description": "tool b", "input_schema": {}},
        mcp_fn,
    )
    return reg


def test_skill_registration_apis_do_not_exist() -> None:
    reg = _make_registry()

    assert not hasattr(reg, "_skill_tools")
    assert not hasattr(reg, "register_skill_specs")
    assert not hasattr(reg, "replace_skill_specs")
    assert not hasattr(reg, "get_skill_specs")
    assert not hasattr(reg, "is_skill")


def test_get_callable_specs_all_tools_returns_only_native_and_mcp_tools() -> None:
    reg = _make_registry()
    specs = reg.get_callable_specs(allowed_tools=ALL_TOOLS)
    names = {s["name"] for s in specs}

    assert {"mcp_tool_a", "mcp_tool_b"} <= names
    assert "research_skill" not in names
    assert "skill__research" not in names


def test_get_tool_specs_with_allowed_filter() -> None:
    reg = _make_registry()
    specs = reg.get_tool_specs(allowed={"mcp_tool_a"})
    names = {s["name"] for s in specs}
    assert "mcp_tool_a" in names
    assert "mcp_tool_b" not in names


def test_get_tool_specs_none_allows_no_tools() -> None:
    reg = _make_registry()
    assert reg.get_tool_specs(allowed=None) == []


def test_get_tool_specs_empty_set_allows_no_tools() -> None:
    reg = _make_registry()
    assert reg.get_tool_specs(allowed=set()) == []


def test_get_callable_specs_with_allowed_filter() -> None:
    reg = _make_registry()
    specs = reg.get_callable_specs(allowed_tools={"mcp_tool_a"})
    names = {s["name"] for s in specs}
    assert names == {"mcp_tool_a"}


def test_get_callable_specs_none_allows_no_tools() -> None:
    reg = _make_registry()
    assert reg.get_callable_specs(allowed_tools=None) == []


def test_get_callable_specs_all_tools_sentinel_means_all_tools() -> None:
    reg = _make_registry()
    specs = reg.get_callable_specs(allowed_tools=ALL_TOOLS)
    names = {s["name"] for s in specs}
    assert {"mcp_tool_a", "mcp_tool_b"} <= names
    assert "unknown_tool" not in names


def test_get_all_tool_specs_uses_all_tools_sentinel() -> None:
    reg = _make_registry()
    specs = reg.get_all_tool_specs()
    names = {s["name"] for s in specs}
    assert {"mcp_tool_a", "mcp_tool_b"} <= names
    assert "unknown_tool" not in names


def test_mcp_tool_with_skill_like_name_is_regular_tool() -> None:
    reg = CapabilityRegistry()

    async def mcp_fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="mcp")

    reg.register_mcp_tool(
        "skill__travel",
        {"name": "skill__travel", "description": "mcp travel", "input_schema": {}},
        mcp_fn,
    )

    callable_names = [s["name"] for s in reg.get_callable_specs(ALL_TOOLS)]
    tool_names = {s["name"] for s in reg.get_tool_specs(ALL_TOOLS)}

    assert callable_names.count("skill__travel") == 1
    assert "skill__travel" in tool_names


@pytest.mark.asyncio
async def test_skill_like_name_is_unknown_without_native_or_mcp_tool() -> None:
    reg = CapabilityRegistry()

    result = await reg.call("skill__travel")

    assert result.ok is False
    assert result.error == "Unknown tool: skill__travel"


@pytest.mark.asyncio
async def test_call_uses_mcp_for_skill_like_name_when_registered() -> None:
    reg = CapabilityRegistry()

    async def mcp_fn(**kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(ok=True, output="mcp")

    reg.register_mcp_tool(
        "skill__travel",
        {"name": "skill__travel", "description": "mcp travel", "input_schema": {}},
        mcp_fn,
    )

    result = await reg.call("skill__travel")

    assert result.output == "mcp"

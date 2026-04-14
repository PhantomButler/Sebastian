from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def restore_tool_registry():
    from sebastian.core import tool as tool_module

    saved = dict(tool_module._tools)
    yield
    tool_module._tools.clear()
    tool_module._tools.update(saved)


@pytest.mark.asyncio
async def test_tool_registers_and_is_callable() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="test_echo", description="Echo input back")
    async def echo(message: str) -> ToolResult:
        return ToolResult(ok=True, output={"echo": message})

    assert "test_echo" in tool_module._tools
    result = await echo(message="hello")
    assert result.ok
    assert result.output["echo"] == "hello"


@pytest.mark.asyncio
async def test_tool_spec_infers_schema() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import list_tool_specs, tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="add_numbers", description="Add two numbers")
    async def add(a: int, b: int) -> ToolResult:
        return ToolResult(ok=True, output=a + b)

    specs = list_tool_specs()
    assert len(specs) == 1
    spec = specs[0]
    assert spec.name == "add_numbers"
    assert spec.parameters["properties"]["a"]["type"] == "integer"
    assert "a" in spec.parameters["required"]
    assert "b" in spec.parameters["required"]


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_error() -> None:
    from sebastian.core.tool import call_tool

    result = await call_tool("nonexistent_tool")
    assert not result.ok
    assert result.error is not None
    assert "nonexistent_tool" in result.error


def test_tool_default_permission_tier_is_low() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult
    from sebastian.permissions.types import PermissionTier

    tool_module._tools.clear()

    @tool(name="default_tier_tool", description="test")
    async def my_tool(x: str) -> ToolResult:
        return ToolResult(ok=True, output=x)

    spec, _ = tool_module._tools["default_tier_tool"]
    assert spec.permission_tier == PermissionTier.MODEL_DECIDES


def test_tool_explicit_permission_tier() -> None:
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult
    from sebastian.permissions.types import PermissionTier

    tool_module._tools.clear()

    @tool(
        name="risky_tool",
        description="test",
        permission_tier=PermissionTier.HIGH_RISK,
    )
    async def risky(cmd: str) -> ToolResult:
        return ToolResult(ok=True, output=cmd)

    spec, _ = tool_module._tools["risky_tool"]
    assert spec.permission_tier == PermissionTier.HIGH_RISK


def test_tool_spec_no_requires_approval_field() -> None:
    """旧字段 requires_approval / permission_level 已移除。"""
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="check_slots", description="test")
    async def check(x: str) -> ToolResult:
        return ToolResult(ok=True, output=x)

    spec, _ = tool_module._tools["check_slots"]
    assert not hasattr(spec, "requires_approval")
    assert not hasattr(spec, "permission_level")

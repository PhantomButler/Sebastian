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
async def test_registry_wraps_native_tool() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="greet", description="Say hello")
    async def greet(name: str) -> ToolResult:
        return ToolResult(ok=True, output=f"Hello, {name}!")

    reg = CapabilityRegistry()
    specs = reg.get_all_tool_specs()
    names = [s["name"] for s in specs]
    assert "greet" in names

    result = await reg.call(tool_name="greet", name="World")
    assert result.ok
    assert result.output == "Hello, World!"


@pytest.mark.asyncio
async def test_registry_unknown_tool_returns_error() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    result = await reg.call(tool_name="ghost_tool")
    assert not result.ok

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sebastian.core.tool import ToolFn, get_tool, list_tool_specs
from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)

McpToolFn = Callable[..., Awaitable[ToolResult]]


class CapabilityRegistry:
    """Unified access point for native tools and MCP-sourced tools."""

    def __init__(self) -> None:
        self._mcp_tools: dict[str, tuple[dict[str, Any], McpToolFn]] = {}

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return all tool specs in Anthropic API `tools` format."""
        specs: list[dict[str, Any]] = []
        for spec in list_tool_specs():
            specs.append({
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters,
            })
        for name, (spec_dict, _) in self._mcp_tools.items():
            specs.append(spec_dict)
        return specs

    async def call(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name. Native tools take priority over MCP."""
        native = get_tool(tool_name)
        if native is not None:
            _, fn = native
            return await fn(**kwargs)
        mcp_entry = self._mcp_tools.get(tool_name)
        if mcp_entry is not None:
            _, fn = mcp_entry
            return await fn(**kwargs)
        return ToolResult(ok=False, error=f"Unknown tool: {tool_name}")

    def register_mcp_tool(
        self,
        name: str,
        spec: dict[str, Any],
        fn: ToolFn,
    ) -> None:
        """Register a tool sourced from MCP."""
        self._mcp_tools[name] = (spec, fn)
        logger.info("MCP tool registered: %s", name)


# Global singleton shared by all agents
registry = CapabilityRegistry()

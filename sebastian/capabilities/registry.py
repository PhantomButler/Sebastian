from __future__ import annotations

import copy
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sebastian.core.tool import get_tool, list_tool_specs
from sebastian.core.types import ToolResult
from sebastian.permissions.types import (
    ALL_TOOLS,
    AllToolsSentinel,
    ToolAllowlist,
    ToolReviewPreflight,
)

logger = logging.getLogger(__name__)

McpToolFn = Callable[..., Awaitable[ToolResult]]


class CapabilityRegistry:
    """Unified access point for native tools and MCP-sourced tools."""

    def __init__(self) -> None:
        self._mcp_tools: dict[str, tuple[dict[str, Any], McpToolFn]] = {}

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return all tool specs in Anthropic API `tools` format (backward compat)."""
        return self.get_callable_specs(allowed_tools=ALL_TOOLS)

    def get_tool_specs(self, allowed: ToolAllowlist = None) -> list[dict[str, Any]]:
        """Return native + MCP tool specs (excluding skills). ALL_TOOLS means all."""
        specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for spec in list_tool_specs():
            if _tool_allowed(spec.name, allowed):
                specs.append(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "input_schema": spec.parameters,
                    }
                )
                seen.add(spec.name)
        for name, (spec_dict, _) in self._mcp_tools.items():
            if name in seen:
                continue
            if _tool_allowed(name, allowed):
                specs.append(spec_dict)
        return specs

    def get_callable_specs(
        self,
        allowed_tools: ToolAllowlist = None,
    ) -> list[dict[str, Any]]:
        """Return filtered native + MCP tool specs for LLM API calls."""
        return self.get_tool_specs(allowed_tools)

    async def review_preflight(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: Any,
    ) -> ToolReviewPreflight:
        """Run a native tool's optional reviewer preflight hook."""
        native = get_tool(tool_name)
        if native is None:
            return ToolReviewPreflight(ok=True)
        spec, _ = native
        if spec.review_preflight is None:
            return ToolReviewPreflight(ok=True)
        return await spec.review_preflight(copy.deepcopy(inputs), context)

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
        fn: McpToolFn,
    ) -> None:
        """Register a tool sourced from MCP."""
        self._mcp_tools[name] = (spec, fn)
        logger.info("MCP tool registered: %s", name)


# Global singleton shared by all agents
registry = CapabilityRegistry()


def _tool_allowed(name: str, allowed: ToolAllowlist) -> bool:
    if isinstance(allowed, AllToolsSentinel):
        return True
    if not allowed:
        return False
    return name in allowed

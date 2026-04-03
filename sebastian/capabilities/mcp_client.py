from __future__ import annotations

import logging
from typing import Any

from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)


class MCPClient:
    """Wraps an MCP server connection and exposes its tools into the registry.

    Phase 1: connects via stdio transport using mcp.client.
    Each MCP server is a subprocess started on demand.
    """

    def __init__(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self._command = command
        self._env = env or {}
        self._session: Any = None

    async def connect(self) -> bool:
        """Start the MCP server process and initialize the session."""
        try:
            import asyncio

            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command=self._command[0],
                args=self._command[1:],
                env=self._env,
            )
            ctx = stdio_client(server_params)
            self._read, self._write = await asyncio.wait_for(
                ctx.__aenter__(), timeout=10.0
            )
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()
            await self._session.initialize()
            logger.info("MCP client connected: %s", self.name)
            return True
        except Exception:
            logger.exception("MCP client failed to connect: %s", self.name)
            return False

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return tool specs in Anthropic API format."""
        if self._session is None:
            return []
        response = await self._session.list_tools()
        result = []
        for t in response.tools:
            result.append({
                "name": t.name,
                "description": t.description or "",
                "input_schema": (
                    t.inputSchema
                    if hasattr(t, "inputSchema")
                    else {"type": "object", "properties": {}}
                ),
            })
        return result

    async def call_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        if self._session is None:
            return ToolResult(ok=False, error=f"MCP {self.name} not connected")
        try:
            response = await self._session.call_tool(tool_name, arguments=kwargs)
            content = response.content[0].text if response.content else ""
            return ToolResult(ok=True, output={"result": content})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None

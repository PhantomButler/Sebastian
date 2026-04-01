from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


def load_mcps() -> list[Any]:
    """Scan capabilities/mcps/ for config.toml files.
    Returns list of MCPClient instances (not yet connected)."""
    from sebastian.capabilities.mcp_client import MCPClient

    mcps_dir = Path(__file__).parent
    clients: list[MCPClient] = []

    for config_path in sorted(mcps_dir.glob("*/config.toml")):
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            mcp_cfg = config.get("mcp", {})
            name = mcp_cfg.get("name", config_path.parent.name)
            command = mcp_cfg.get("command", [])
            env = mcp_cfg.get("env", {})
            if not command:
                logger.warning("MCP config %s has no command, skipping", config_path)
                continue
            client = MCPClient(name=name, command=command, env=env)
            clients.append(client)
            logger.info("MCP config loaded: %s", name)
        except Exception:
            logger.exception("Failed to load MCP config: %s", config_path)

    return clients


async def connect_all(clients: list[Any], registry: Any) -> None:
    """Connect all MCP clients and register their tools into registry."""
    for client in clients:
        ok = await client.connect()
        if not ok:
            continue
        tools = await client.list_tools()
        for spec in tools:
            tool_name = spec["name"]

            # Capture client and tool_name in closure
            def _make_caller(c: Any, n: str) -> Any:
                async def _call(**kwargs: Any) -> Any:
                    return await c.call_tool(n, **kwargs)
                return _call

            registry.register_mcp_tool(tool_name, spec, _make_caller(client, tool_name))

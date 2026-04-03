from __future__ import annotations

import asyncio

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


@tool(
    name="shell",
    description="Execute a shell command. Returns stdout, stderr, and return code.",
    requires_approval=True,
    permission_level="owner",
)
async def shell(command: str) -> ToolResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        output={
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "returncode": proc.returncode,
        },
        error=stderr.decode(errors="replace") if not ok else None,
    )

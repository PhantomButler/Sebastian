from __future__ import annotations

import asyncio

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="shell",
    description=(
        "Execute a shell command. Returns stdout, stderr, and return code. "
        "Use reason to explain why this specific command is safe for the current task."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def shell(command: str) -> ToolResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return ToolResult(ok=False, error="Shell command timed out after 120 seconds")
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

from __future__ import annotations

import asyncio

from sebastian.config import settings
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_MAX_OUTPUT_CHARS = 10_000
_DEFAULT_TIMEOUT = 600


@tool(
    name="Bash",
    description=(
        "Execute a shell command. Returns stdout, stderr, and return code. "
        "Non-zero return codes are not automatically errors. "
        "Default timeout is 600 seconds."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def bash(command: str, timeout: int | None = None) -> ToolResult:
    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    workspace = settings.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workspace),
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(effective_timeout),
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(ok=False, error=f"Command timed out after {effective_timeout}s")

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    truncated = False

    if len(stdout) > _MAX_OUTPUT_CHARS:
        stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True
    if len(stderr) > _MAX_OUTPUT_CHARS:
        stderr = stderr[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True

    empty_hint = (
        f"Command exited with code {proc.returncode}, no output"
        if not stdout and not stderr
        else None
    )

    if proc.returncode != 0 and stderr:
        display = f"{stdout}\n--- stderr ---\n{stderr}" if stdout else f"--- stderr ---\n{stderr}"
    else:
        display = stdout

    return ToolResult(
        ok=True,
        output={
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode,
            "truncated": truncated,
        },
        display=display,
        empty_hint=empty_hint,
    )

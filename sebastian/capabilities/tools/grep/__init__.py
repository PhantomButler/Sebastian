from __future__ import annotations

import asyncio
import os
import shutil

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_DEFAULT_HEAD_LIMIT = 250
_RG_AVAILABLE: bool | None = None


def _check_rg() -> bool:
    global _RG_AVAILABLE
    if _RG_AVAILABLE is None:
        _RG_AVAILABLE = shutil.which("rg") is not None
    return _RG_AVAILABLE


def _build_rg_cmd(
    pattern: str,
    search_path: str,
    glob_pattern: str | None,
    ignore_case: bool,
    context_lines: int | None,
) -> list[str]:
    cmd = ["rg", "--line-number", "--no-heading"]
    if ignore_case:
        cmd.append("-i")
    if glob_pattern:
        cmd.extend(["--glob", glob_pattern])
    if context_lines is not None:
        cmd.extend(["-C", str(context_lines)])
    cmd.extend([pattern, search_path])
    return cmd


def _build_grep_cmd(
    pattern: str,
    search_path: str,
    glob_pattern: str | None,
    ignore_case: bool,
    context_lines: int | None,
) -> list[str]:
    cmd = ["grep", "-rn"]
    if ignore_case:
        cmd.append("-i")
    if context_lines is not None:
        cmd.extend(["-C", str(context_lines)])
    if glob_pattern:
        cmd.extend(["--include", glob_pattern])
    cmd.extend([pattern, search_path])
    return cmd


async def _run_cmd(cmd: list[str]) -> tuple[str, str, int | None]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        stdout_bytes.decode(errors="replace"),
        stderr_bytes.decode(errors="replace"),
        proc.returncode,
    )


@tool(
    name="Grep",
    description=(
        "Search file contents using regex. Uses ripgrep if available, falls back to grep. "
        "Returns matched lines with optional context. Non-zero exit codes may indicate no matches."
    ),
    permission_tier=PermissionTier.LOW,
)
async def grep(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    ignore_case: bool = False,
    context_lines: int | None = None,
    head_limit: int | None = None,
) -> ToolResult:
    search_path = path if path is not None else os.getcwd()
    effective_limit = head_limit if head_limit is not None else _DEFAULT_HEAD_LIMIT
    use_rg = _check_rg()

    if use_rg:
        cmd = _build_rg_cmd(pattern, search_path, glob_pattern=glob, ignore_case=ignore_case, context_lines=context_lines)
        backend = "ripgrep"
    else:
        cmd = _build_grep_cmd(pattern, search_path, glob_pattern=glob, ignore_case=ignore_case, context_lines=context_lines)
        backend = "grep"

    output, stderr_output, returncode = await _run_cmd(cmd)

    # returncode=2 indicates a real error (invalid pattern, permission denied, etc.)
    if returncode is not None and returncode >= 2:
        return ToolResult(ok=False, error=stderr_output.strip() or f"Search failed with exit code {returncode}")

    lines = output.splitlines(keepends=True)
    truncated = len(lines) > effective_limit
    if truncated:
        output = "".join(lines[:effective_limit]) + "\n...[truncated]"

    return ToolResult(
        ok=True,
        output={
            "output": output,
            "truncated": truncated,
            "backend": backend,
        },
    )

from __future__ import annotations

import asyncio
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
    glob: str | None,
    ignore_case: bool,
    context_lines: int | None,
) -> list[str]:
    cmd = ["rg", "--line-number", "--no-heading", pattern, search_path]
    if ignore_case:
        cmd.insert(1, "-i")
    if glob:
        cmd[1:1] = ["--glob", glob]
    if context_lines:
        cmd[1:1] = ["-C", str(context_lines)]
    return cmd


def _build_grep_cmd(
    pattern: str,
    search_path: str,
    glob: str | None,
    ignore_case: bool,
    context_lines: int | None,
) -> list[str]:
    cmd = ["grep", "-rn"]
    if ignore_case:
        cmd.append("-i")
    if context_lines:
        cmd.extend(["-C", str(context_lines)])
    if glob:
        cmd.extend(["--include", glob])
    cmd.extend([pattern, search_path])
    return cmd


async def _run_cmd(cmd: list[str]) -> tuple[str, int]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, _ = await proc.communicate()
    return stdout_bytes.decode(errors="replace"), proc.returncode or 0


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
    import os

    search_path = path if path is not None else os.getcwd()
    effective_limit = head_limit if head_limit is not None else _DEFAULT_HEAD_LIMIT
    use_rg = _check_rg()

    if use_rg:
        cmd = _build_rg_cmd(pattern, search_path, glob, ignore_case, context_lines)
        backend = "ripgrep"
    else:
        cmd = _build_grep_cmd(pattern, search_path, glob, ignore_case, context_lines)
        backend = "grep"

    output, _ = await _run_cmd(cmd)

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

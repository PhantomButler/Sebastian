from __future__ import annotations

import os

from sebastian.capabilities.tools import _file_state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_DEFAULT_LIMIT = 2000


@tool(
    name="Read",
    description=(
        "Read the contents of a file. Supports optional offset (1-indexed start line) "
        "and limit (number of lines to read). Defaults to first 2000 lines. "
        "Returns content, total_lines, lines_read, and truncated flag."
    ),
    permission_tier=PermissionTier.LOW,
)
async def read(
    file_path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> ToolResult:
    path = os.path.abspath(file_path)
    if not os.path.exists(path):
        return ToolResult(ok=False, error=f"File not found: {path}")
    if os.path.isdir(path):
        return ToolResult(ok=False, error=f"Path is a directory, not a file: {path}")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        start = max(0, (offset - 1) if offset is not None else 0)
        max_lines = limit if limit is not None else _DEFAULT_LIMIT
        end = min(start + max_lines, total_lines)
        selected = lines[start:end]

        _file_state.record_read(path)

        return ToolResult(
            ok=True,
            output={
                "content": "".join(selected),
                "total_lines": total_lines,
                "lines_read": len(selected),
                "truncated": (start + max_lines) < total_lines,
            },
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

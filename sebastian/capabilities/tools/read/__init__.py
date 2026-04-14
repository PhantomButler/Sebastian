from __future__ import annotations

from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_DEFAULT_LIMIT = 2000


@tool(
    name="Read",
    description=(
        "Read the contents of a file. Supports optional offset (1-indexed start line) "
        "and limit (number of lines to read). Defaults to first 2000 lines. "
        "Returns content, total_lines, lines_read, start_line, and truncated flag. "
        "Each line in the returned content is prefixed with its line number in "
        "`cat -n` format (`{line_number}\\t{line_content}`). The line number prefix "
        "is NOT part of the file content — when passing content to Edit/Write tools, "
        "strip the `{N}\\t` prefix first."
    ),
    permission_tier=PermissionTier.LOW,
)
async def read(
    file_path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> ToolResult:
    path = str(resolve_path(file_path))
    if not Path(path).exists():
        return ToolResult(ok=False, error=f"File not found: {path}")
    if Path(path).is_dir():
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

        content = "".join(f"{start + i + 1}\t{line}" for i, line in enumerate(selected))

        if not content and total_lines == 0:
            empty_hint = f"File exists but is empty (0 lines): {path}"
        elif not content and start >= total_lines:
            empty_hint = (
                f"File exists but is shorter than the provided offset ({offset}). "
                f"The file has {total_lines} lines: {path}"
            )
        else:
            empty_hint = None

        output = {
            "content": content,
            "total_lines": total_lines,
            "lines_read": len(selected),
            "start_line": start + 1,
            "truncated": (start + max_lines) < total_lines,
        }
        return ToolResult(
            ok=True,
            output=output,
            display=content,
            empty_hint=empty_hint,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

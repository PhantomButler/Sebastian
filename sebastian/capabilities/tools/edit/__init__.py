from __future__ import annotations

from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="Edit",
    description=(
        "Replace old_string with new_string in a file. "
        "By default (replace_all=false), old_string must appear exactly once — "
        "if it appears 0 times the tool errors, if it appears more than once the tool "
        "errors and asks you to provide more context to make it unique. "
        "Set replace_all=true to replace every occurrence. "
        "IMPORTANT: old_string must match the raw file content exactly. Do NOT "
        "include the `{N}\\t` line-number prefixes that appear in Read tool output — "
        "those are display decoration, not file content."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> ToolResult:
    path = str(resolve_path(file_path))
    try:
        _file_state.check_write(path)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))
    if not Path(path).exists():
        return ToolResult(ok=False, error=f"File not found: {path}")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return ToolResult(ok=False, error=f"old_string not found in file: {path}")
        if count > 1 and not replace_all:
            return ToolResult(
                ok=False,
                error=(
                    f"old_string matches {count} times. "
                    f"Provide more context to make it unique, or use replace_all=true"
                ),
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        _file_state.invalidate(path)
        return ToolResult(ok=True, output={"file_path": path, "replacements": replacements})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

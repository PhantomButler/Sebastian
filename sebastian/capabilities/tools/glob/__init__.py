from __future__ import annotations

import glob as glob_module
import os

from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.config import settings
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_MAX_RESULTS = 100


@tool(
    name="Glob",
    description=(
        "Find files matching a glob pattern. Results are sorted by modification time "
        "(most recently modified first). Returns at most 100 results."
    ),
    permission_tier=PermissionTier.LOW,
)
async def glob(pattern: str, path: str | None = None) -> ToolResult:
    search_root = str(resolve_path(path) if path is not None else settings.workspace_dir)

    if not os.path.isdir(search_root):
        return ToolResult(ok=False, error=f"Path is not a directory: {search_root}")

    matches = glob_module.glob(pattern, root_dir=search_root, recursive=True)

    def _mtime_key(rel_path: str) -> float:
        try:
            return -os.path.getmtime(os.path.join(search_root, rel_path))
        except OSError:
            return float("inf")

    matches.sort(key=_mtime_key)

    truncated = len(matches) > _MAX_RESULTS
    files = matches[:_MAX_RESULTS]

    return ToolResult(
        ok=True,
        output={
            "files": files,
            "count": len(files),
            "truncated": truncated,
        },
    )

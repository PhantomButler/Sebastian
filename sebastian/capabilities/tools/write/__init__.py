from __future__ import annotations

import os
from pathlib import Path

from sebastian.capabilities.tools import _file_state
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="Write",
    description=(
        "Write full content to a file, replacing existing content. "
        "Creates parent directories if needed. "
        "If the file already exists, it must have been previously Read in this session."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def write(file_path: str, content: str) -> ToolResult:
    path = os.path.abspath(file_path)
    try:
        _file_state.check_write(path)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))

    action = "updated" if os.path.exists(path) else "created"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        _file_state.invalidate(path)
        return ToolResult(
            ok=True,
            output={
                "file_path": path,
                "action": action,
                "bytes_written": len(content.encode("utf-8")),
            },
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))

from __future__ import annotations

from pathlib import Path
from typing import Any

from sebastian.capabilities.tools.browser.artifacts import upload_browser_artifact
from sebastian.capabilities.tools.browser.manager import BrowserDownloadRecord
from sebastian.core.types import ToolResult


async def list_downloads(manager: Any) -> list[dict[str, object]]:
    records = await manager.list_download_records()
    return [_public_download(record) for record in reversed(records)]


async def send_download(manager: Any, filename: str | None) -> ToolResult:
    if not filename:
        return ToolResult(
            ok=False,
            error=(
                "browser_downloads send requires a filename from browser_downloads list. "
                "Do not retry automatically; call browser_downloads with action='list' first."
            ),
        )
    try:
        record = await manager.resolve_download(filename)
    except (FileNotFoundError, ValueError):
        return ToolResult(
            ok=False,
            error=(
                "Download is not available in the browser downloads directory. "
                "Do not retry automatically; call browser_downloads with action='list' "
                "and choose a listed filename."
            ),
        )
    except Exception:
        return ToolResult(
            ok=False,
            error=(
                "Browser download lookup failed. Do not retry automatically; "
                "tell the user the download cannot be sent right now."
            ),
        )
    return await upload_browser_artifact(
        path=Path(record.path),
        filename=record.filename,
        mime_type=record.mime,
        kind="download",
    )


def _public_download(record: BrowserDownloadRecord) -> dict[str, object]:
    return {
        "filename": record.filename,
        "mime": record.mime,
        "size": record.size,
        "mtime": record.mtime,
        "original": record.original,
        "source_url": record.source_url,
        "created_at": record.created_at,
    }

from __future__ import annotations

import mimetypes
import sys
from pathlib import Path

from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.store.attachments import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_TYPES,
    ALLOWED_TEXT_EXTENSIONS,
    ALLOWED_TEXT_MIME_TYPES,
    AttachmentValidationError,
)


def _resolve_display_name(display_name: str | None, source_path: Path) -> str:
    if display_name is None:
        return source_path.name
    p = Path(display_name)
    if p.suffix:
        return display_name
    return display_name + source_path.suffix


def _detect_kind(path: Path) -> tuple[str, str] | None:
    suffix = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    if suffix in ALLOWED_IMAGE_EXTENSIONS and mime in ALLOWED_IMAGE_MIME_TYPES:
        return "image", mime
    if suffix in ALLOWED_TEXT_EXTENSIONS:
        if mime not in ALLOWED_TEXT_MIME_TYPES:
            mime = "application/octet-stream"
        return "text_file", mime
    return None


@tool(
    name="send_file",
    description=(
        "Send a file from the server filesystem to the user in this conversation. "
        "Supported types: images (jpg/jpeg/png/webp/gif) and text files (txt/md/csv/json/log). "
        "The file will appear in the chat for the user to view or download. "
        "Use display_name to override the filename shown to the user."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def send_file(file_path: str, display_name: str | None = None) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(
            ok=False,
            error=(
                "send_file requires session context. Do not retry automatically; "
                "tell the user the file could not be sent in this conversation."
            ),
        )

    state = sys.modules.get("sebastian.gateway.state")
    if state is None:
        import sebastian.gateway.state as _state  # noqa: PLC0415

        state = _state

    attachment_store = getattr(state, "attachment_store", None)
    if attachment_store is None:
        return ToolResult(
            ok=False,
            error=(
                "Attachment service is unavailable. Do not retry automatically; "
                "tell the user sending files is currently unavailable."
            ),
        )

    path = resolve_path(file_path)

    if not path.exists():
        return ToolResult(
            ok=False,
            error=(
                f"File not found: {path}. Do not retry automatically; "
                "ask the user to provide an existing file path."
            ),
        )

    if path.is_dir():
        return ToolResult(
            ok=False,
            error=(
                f"Path is a directory, not a file: {path}. Do not retry automatically; "
                "ask the user for a file path."
            ),
        )

    kind_info = _detect_kind(path)
    if kind_info is None:
        return ToolResult(
            ok=False,
            error=(
                f"Unsupported file type: {path.suffix.lower()!r}. Do not retry automatically; "
                "only image and supported text files can be sent."
            ),
        )

    kind, mime_type = kind_info
    filename = _resolve_display_name(display_name, path)
    data = path.read_bytes()

    try:
        uploaded = await attachment_store.upload_bytes(
            filename=filename,
            content_type=mime_type,
            kind=kind,
            data=data,
        )
    except AttachmentValidationError as exc:
        msg = str(exc)
        if "exceeds" in msg or "limit" in msg:
            return ToolResult(
                ok=False,
                error=(
                    f"File {filename!r} is too large to send: {exc}. "
                    "Do not retry automatically; ask the user to choose a smaller file."
                ),
            )
        return ToolResult(
            ok=False,
            error=(
                "Attachment service is unavailable. Do not retry automatically; "
                "tell the user sending files is currently unavailable."
            ),
        )

    record = await attachment_store.mark_agent_sent(
        attachment_id=uploaded.id,
        agent_type=ctx.agent_type,
        session_id=ctx.session_id,
    )

    att_id = record.id
    download_url = f"/api/v1/attachments/{att_id}"

    if kind == "image":
        artifact = {
            "kind": "image",
            "attachment_id": att_id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": uploaded.size_bytes,
            "download_url": download_url,
            "thumbnail_url": f"/api/v1/attachments/{att_id}/thumbnail",
        }
        display_text = f"已向用户发送图片 {filename}"
    else:
        artifact = {
            "kind": "text_file",
            "attachment_id": att_id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": uploaded.size_bytes,
            "download_url": download_url,
            "text_excerpt": uploaded.text_excerpt,
        }
        display_text = f"已向用户发送文件 {filename}"

    return ToolResult(
        ok=True,
        display=display_text,
        output={"artifact": artifact},
    )

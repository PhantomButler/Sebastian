from __future__ import annotations

import sys
from pathlib import Path

from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.store.attachments import AttachmentValidationError


async def upload_browser_artifact(
    *,
    path: Path,
    filename: str,
    mime_type: str,
    kind: str,
    delete_after: bool = False,
) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(
            ok=False,
            error=(
                "Browser artifact sending requires session context. "
                "Do not retry automatically; tell the user the artifact could not be sent."
            ),
        )

    state = _gateway_state()
    attachment_store = getattr(state, "attachment_store", None)
    if attachment_store is None:
        return ToolResult(
            ok=False,
            error=(
                "Attachment service is unavailable. Do not retry automatically; "
                "tell the user browser artifacts cannot be sent right now."
            ),
        )

    try:
        data = path.read_bytes()
    except OSError:
        return ToolResult(
            ok=False,
            error=(
                "Browser artifact could not be read. Do not retry automatically; "
                "tell the user the artifact is unavailable."
            ),
        )

    try:
        uploaded = await attachment_store.upload_bytes(
            filename=filename,
            content_type=mime_type,
            kind=kind,
            data=data,
        )
        record = await attachment_store.mark_agent_sent(
            attachment_id=uploaded.id,
            agent_type=ctx.agent_type,
            session_id=ctx.session_id,
        )
    except AttachmentValidationError as exc:
        return ToolResult(
            ok=False,
            error=(
                f"{exc}. Do not retry automatically; "
                "tell the user the browser artifact could not be sent."
            ),
        )
    except Exception:
        return ToolResult(
            ok=False,
            error=(
                "Attachment service failed while sending browser artifact. "
                "Do not retry automatically; tell the user sending is currently unavailable."
            ),
        )
    finally:
        if delete_after:
            path.unlink(missing_ok=True)

    artifact = {
        "kind": kind,
        "attachment_id": record.id,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": uploaded.size_bytes,
        "download_url": f"/api/v1/attachments/{record.id}",
    }
    if kind == "image":
        artifact["thumbnail_url"] = f"/api/v1/attachments/{record.id}/thumbnail"

    label = "image" if kind == "image" else "download"
    return ToolResult(
        ok=True,
        output={"artifact": artifact},
        display=f"Sent browser {label} {filename}",
    )


def _gateway_state() -> object:
    state = sys.modules.get("sebastian.gateway.state")
    if state is None:
        import sebastian.gateway.state as _state  # noqa: PLC0415

        state = _state
    return state

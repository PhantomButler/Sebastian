from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from sebastian.gateway.auth import require_auth
from sebastian.store.attachments import AttachmentValidationError

router = APIRouter(tags=["attachments"])
AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


@router.post("/attachments", status_code=201)
async def upload_attachment(
    kind: Literal["image", "text_file"] = Form(...),
    file: UploadFile = File(...),
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    store = state.attachment_store
    if store is None:
        raise HTTPException(status_code=503, detail="Attachment store not initialized")
    data = await file.read()
    try:
        uploaded = await store.upload_bytes(
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            kind=kind,
            data=data,
        )
    except AttachmentValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "id": uploaded.id,
        "kind": uploaded.kind,
        "filename": uploaded.filename,
        "mime_type": uploaded.mime_type,
        "size_bytes": uploaded.size_bytes,
        "sha256": uploaded.sha256,
        "text_excerpt": uploaded.text_excerpt,
        "status": uploaded.status,
    }


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    store = state.attachment_store
    if store is None:
        raise HTTPException(status_code=503, detail="Attachment store not initialized")
    record = await store.get(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    blob_path = store.blob_absolute_path(record)
    if not blob_path.exists():
        raise HTTPException(status_code=404, detail="Attachment blob not found")
    data = blob_path.read_bytes()
    return Response(content=data, media_type=record.mime_type)


@router.get("/attachments/{attachment_id}/thumbnail")
async def download_thumbnail(
    attachment_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> Response:
    import sebastian.gateway.state as state

    store = state.attachment_store
    if store is None:
        raise HTTPException(status_code=503, detail="Attachment store not initialized")
    record = await store.get(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    # P0: return the original image as-is (no thumbnail generation yet)
    if record.kind != "image":
        raise HTTPException(status_code=400, detail="Thumbnail only available for images")
    blob_path = store.blob_absolute_path(record)
    if not blob_path.exists():
        raise HTTPException(status_code=404, detail="Attachment blob not found")
    data = blob_path.read_bytes()
    return Response(content=data, media_type=record.mime_type)

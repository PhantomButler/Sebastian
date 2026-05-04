from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile

from sebastian.gateway.auth import require_auth
from sebastian.store.attachments import AttachmentValidationError

router = APIRouter(tags=["attachments"])
AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


@router.post("/attachments", status_code=201)
async def upload_attachment(
    kind: Literal["image", "text_file", "download"] = Form(...),
    file: UploadFile | str = File(...),
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    store = state.attachment_store
    if store is None:
        raise HTTPException(status_code=503, detail="Attachment store not initialized")
    if isinstance(file, StarletteUploadFile):
        data = await file.read()
        filename = (file.filename or "") if kind == "download" else file.filename or "upload"
        content_type = file.content_type or "application/octet-stream"
    else:
        if kind != "download":
            raise HTTPException(status_code=422, detail="Expected uploaded file")
        data = file.encode("utf-8")
        filename = ""
        content_type = "application/octet-stream"
    try:
        uploaded = await store.upload_bytes(
            filename=filename,
            content_type=content_type,
            kind=kind,
            data=data,
        )
    except AttachmentValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "attachment_id": uploaded.id,
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
    return FileResponse(blob_path, media_type=record.mime_type)


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
    if record.kind != "image":
        raise HTTPException(status_code=400, detail="Thumbnail only available for images")

    # SHA 内容寻址：thumb 在生成时只会落到 jpg/png/webp 之一，至多一个候选命中
    for candidate, mime in store.thumb_candidate_paths(record):
        if candidate.exists():
            return Response(content=candidate.read_bytes(), media_type=mime)

    # 缺 thumb 时 fallback 返回原图（兼容老数据 / 生成失败）
    blob_path = store.blob_absolute_path(record)
    if not blob_path.exists():
        raise HTTPException(status_code=404, detail="Attachment blob not found")
    return Response(content=blob_path.read_bytes(), media_type=record.mime_type)

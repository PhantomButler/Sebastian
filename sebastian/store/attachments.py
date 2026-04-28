from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from sebastian.store.models import AttachmentRecord

ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
ALLOWED_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".csv", ".json", ".log"})
ALLOWED_TEXT_MIME_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/x-ndjson",
    "text/x-log",
    "application/octet-stream",
})
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
TEXT_EXCERPT_CHARS = 2000
_UPLOADED_TTL = timedelta(hours=24)   # status="uploaded" blobs expire after 24 h if never referenced
_ORPHAN_TTL = timedelta(hours=24)     # orphaned blobs expire (can differ from uploaded in future)


@dataclass(slots=True)
class UploadedAttachment:
    id: str
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    text_excerpt: str | None
    status: str = "uploaded"


class AttachmentValidationError(ValueError):
    pass


class AttachmentStore:
    def __init__(self, root_dir: Path, db_factory: async_sessionmaker) -> None:
        self._root_dir = root_dir
        self._db_factory = db_factory

    # --- 上传 ---

    async def upload_bytes(
        self,
        *,
        filename: str,
        content_type: str,
        kind: str,
        data: bytes,
    ) -> UploadedAttachment:
        if kind == "image":
            self._validate_image(filename, content_type, data)
        elif kind == "text_file":
            self._validate_text_file(filename, content_type, data)
        else:
            raise AttachmentValidationError(f"Unknown kind: {kind!r}")

        sha = hashlib.sha256(data).hexdigest()
        blob_rel = f"blobs/{sha[:2]}/{sha}"
        blob_abs = self._root_dir / blob_rel
        blob_abs.parent.mkdir(parents=True, exist_ok=True)
        (self._root_dir / "tmp").mkdir(parents=True, exist_ok=True)
        tmp_path = self._root_dir / "tmp" / str(uuid4())
        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, blob_abs)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        text_excerpt: str | None = None
        if kind == "text_file":
            text = data.decode("utf-8")
            text_excerpt = text[:TEXT_EXCERPT_CHARS]

        att_id = str(uuid4())
        record = AttachmentRecord(
            id=att_id,
            kind=kind,
            original_filename=filename,
            mime_type=content_type,
            size_bytes=len(data),
            sha256=sha,
            blob_path=blob_rel,
            text_excerpt=text_excerpt,
            status="uploaded",
            created_at=datetime.now(UTC),
            owner_user_id=None,  # TODO: 多用户前补充 owner_user_id
        )
        try:
            async with self._db_factory() as session:
                session.add(record)
                await session.commit()
        except Exception:
            blob_abs.unlink(missing_ok=True)
            raise

        return UploadedAttachment(
            id=att_id,
            kind=kind,
            filename=filename,
            mime_type=content_type,
            size_bytes=len(data),
            sha256=sha,
            text_excerpt=text_excerpt,
        )

    # --- 读取 ---

    async def get(self, attachment_id: str) -> AttachmentRecord | None:
        async with self._db_factory() as session:
            return await session.get(AttachmentRecord, attachment_id)

    def blob_absolute_path(self, record: AttachmentRecord) -> Path:
        resolved = (self._root_dir / record.blob_path).resolve()
        if not resolved.is_relative_to(self._root_dir.resolve()):
            raise ValueError(f"Blob path escapes root: {record.blob_path!r}")
        return resolved

    def read_text_content(self, record: AttachmentRecord) -> str:
        return self.blob_absolute_path(record).read_text(encoding="utf-8")

    # --- 状态流转 ---

    # NOTE: 单用户假设 — 不校验 owner_user_id。
    # 多用户场景（家人/访客）上线前必须加 ownership 检查以防 IDOR。
    async def validate_attachable(self, attachment_ids: list[str]) -> list[AttachmentRecord]:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AttachmentRecord).where(AttachmentRecord.id.in_(attachment_ids))
            )
            records = list(result.scalars().all())
        found_ids = {r.id for r in records}
        missing = set(attachment_ids) - found_ids
        if missing:
            raise AttachmentValidationError(f"Attachment(s) not found: {missing}")
        for r in records:
            if r.status != "uploaded":
                raise AttachmentValidationError(
                    f"Attachment {r.id!r} is not in 'uploaded' state (status={r.status!r})"
                )
            if r.session_id is not None:
                raise AttachmentValidationError(
                    f"Attachment {r.id!r} is already bound to a session"
                )
        return records

    # Internal only: opens its own DB session and is NOT atomic with timeline writes.
    # The canonical status transition is done inline in SessionStore.append_user_turn_with_attachments.
    async def _mark_attached(
        self,
        attachment_ids: list[str],
        agent_type: str,
        session_id: str,
    ) -> list[AttachmentRecord]:
        now = datetime.now(UTC)
        async with self._db_factory() as session:
            await session.execute(
                update(AttachmentRecord)
                .where(AttachmentRecord.id.in_(attachment_ids))
                .values(
                    status="attached",
                    agent_type=agent_type,
                    session_id=session_id,
                    attached_at=now,
                )
            )
            await session.commit()
            result = await session.execute(
                select(AttachmentRecord).where(AttachmentRecord.id.in_(attachment_ids))
            )
            records = list(result.scalars().all())
        returned_ids = {r.id for r in records}
        missing = set(attachment_ids) - returned_ids
        if missing:
            raise AttachmentValidationError(f"Attachment(s) lost after _mark_attached: {missing}")
        return records

    async def mark_session_orphaned(self, agent_type: str, session_id: str) -> int:
        now = datetime.now(UTC)
        async with self._db_factory() as session:
            result = await session.execute(
                update(AttachmentRecord)
                .where(
                    AttachmentRecord.agent_type == agent_type,
                    AttachmentRecord.session_id == session_id,
                    AttachmentRecord.status == "attached",
                )
                .values(status="orphaned", orphaned_at=now)
            )
            await session.commit()
            return result.rowcount

    async def cleanup(self, now: datetime | None = None) -> int:
        _now = now or datetime.now(UTC)
        uploaded_cutoff = _now - _UPLOADED_TTL
        orphan_cutoff = _now - _ORPHAN_TTL
        async with self._db_factory() as session:
            result = await session.execute(
                select(AttachmentRecord).where(
                    (
                        (AttachmentRecord.status == "uploaded")
                        & (AttachmentRecord.created_at < uploaded_cutoff)
                    )
                    | (
                        (AttachmentRecord.status == "orphaned")
                        & (AttachmentRecord.orphaned_at < orphan_cutoff)
                    )
                )
            )
            records = list(result.scalars().all())
            count = 0
            for r in records:
                blob = self.blob_absolute_path(r)
                blob.unlink(missing_ok=True)
                thumb = self._root_dir / "thumbs" / f"{r.id}.jpg"
                thumb.unlink(missing_ok=True)
                await session.delete(r)
                count += 1
            await session.commit()
        tmp_dir = self._root_dir / "tmp"
        if tmp_dir.exists():
            for tmp_file in tmp_dir.iterdir():
                if tmp_file.is_file():
                    try:
                        mtime = datetime.fromtimestamp(tmp_file.stat().st_mtime, UTC)
                        if mtime < uploaded_cutoff:
                            tmp_file.unlink(missing_ok=True)
                            count += 1
                    except OSError:
                        pass
        return count

    # --- 校验私有方法 ---

    def _validate_image(self, filename: str, content_type: str, data: bytes) -> None:
        suffix = Path(filename).suffix.lower()
        if not suffix:
            raise AttachmentValidationError("Image filename must include a file extension")
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            raise AttachmentValidationError(f"Unsupported image extension: {suffix!r}")
        if content_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise AttachmentValidationError(f"Unsupported image MIME: {content_type!r}")
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentValidationError("Image exceeds 10 MB limit")

    def _validate_text_file(self, filename: str, content_type: str, data: bytes) -> None:
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_TEXT_EXTENSIONS:
            raise AttachmentValidationError(f"Unsupported file extension: {suffix!r}")
        # 明确不支持的 MIME 直接拒绝
        if content_type not in ALLOWED_TEXT_MIME_TYPES:
            raise AttachmentValidationError(f"Unsupported text file MIME: {content_type!r}")
        if len(data) > MAX_TEXT_BYTES:
            raise AttachmentValidationError("Text file exceeds 2 MB limit")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AttachmentValidationError("Text file is not valid UTF-8") from e

from __future__ import annotations

import hashlib
import logging
import os
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import (  # noqa: F401  # UnidentifiedImageError used by Task 5
    Image,
    ImageOps,
    UnidentifiedImageError,
)
from sqlalchemy import (
    func,  # noqa: F401  # used by Task 9
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.store.models import AttachmentRecord

logger = logging.getLogger(__name__)

# DecompressionBomb 防护：Pillow 默认 MAX_IMAGE_PIXELS ≈ 89.5M（超过时仅发 Warning，
# > 2× 才抛 Error）。这里将上限设为 100M，并把 Warning 升级为 Error，
# 使单层阈值即触发硬阻断，而非依赖 Pillow 的双重阈值机制。
Image.MAX_IMAGE_PIXELS = 100_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
ALLOWED_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".csv", ".json", ".log"})
ALLOWED_TEXT_MIME_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/x-ndjson",
        "text/x-log",
        "application/octet-stream",
    }
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
TEXT_EXCERPT_CHARS = 2000
_UPLOADED_TTL = timedelta(hours=24)  # status="uploaded" blobs expire after 24 h if never referenced
_ORPHAN_TTL = timedelta(hours=24)  # orphaned blobs expire (can differ from uploaded in future)

THUMB_MAX_EDGE = 256
JPEG_QUALITY = 85
_THUMB_EXT_BY_FORMAT: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


def _maybe_generate_thumbnail(
    root_dir: Path, sha: str, data: bytes
) -> tuple[Path | None, bool]:
    """对图片字节生成 256×256 缩略图，写到 thumbs/<sha[:2]>/<sha>.<ext>。

    返回 (thumb_abs, created)：
      - thumb_abs is None / created False：未生成（不支持的格式或异常降级）
      - thumb_abs not None / created True：本次新写入了 thumb 文件
      - thumb_abs not None / created False：thumb 已存在，跳过写入（dedup）
    """
    try:
        with Image.open(BytesIO(data)) as img:
            img.load()
            src_format = img.format or ""
            if src_format == "GIF":
                img.seek(0)
                ext = "png"
                save_format = "PNG"
            else:
                ext = _THUMB_EXT_BY_FORMAT.get(src_format)
                if ext is None:
                    return None, False
                save_format = src_format

            # EXIF orientation 校正必须在缩放前
            img = ImageOps.exif_transpose(img)

            # 按输出格式做必要的 mode 转换
            if save_format == "JPEG":
                if img.mode != "RGB":
                    img = img.convert("RGB")
            elif save_format == "PNG":
                if img.mode == "P":
                    if "transparency" in img.info:
                        img = img.convert("RGBA")
                    else:
                        img = img.convert("RGB")
            elif save_format == "WEBP":
                # WebP 同时支持 RGB / RGBA。其他 mode 一律转 RGBA，不损失 alpha。
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")

            img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))

            thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
            thumb_abs = root_dir / thumb_rel
            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
            (root_dir / "tmp").mkdir(parents=True, exist_ok=True)
            tmp_path = root_dir / "tmp" / str(uuid4())
            try:
                save_kwargs: dict = {"format": save_format, "optimize": True}
                if save_format == "JPEG":
                    save_kwargs["quality"] = JPEG_QUALITY
                img.save(tmp_path, **save_kwargs)
                os.replace(tmp_path, thumb_abs)
                return thumb_abs, True
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
    except Exception as exc:
        logger.warning("thumbnail generation skipped for sha=%s: %s", sha[:8], exc)
        return None, False


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


class AttachmentNotFoundError(AttachmentValidationError):
    pass


class AttachmentConflictError(AttachmentValidationError):
    pass


class AttachmentStore:
    def __init__(self, root_dir: Path, db_factory: async_sessionmaker[AsyncSession]) -> None:
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
            raise AttachmentNotFoundError(f"Attachment(s) not found: {missing}")
        for r in records:
            if r.status != "uploaded":
                raise AttachmentConflictError(
                    f"Attachment {r.id!r} is not in 'uploaded' state (status={r.status!r})"
                )
            if r.session_id is not None:
                raise AttachmentConflictError(f"Attachment {r.id!r} is already bound to a session")
        return records

    async def mark_agent_sent(
        self,
        attachment_id: str,
        agent_type: str,
        session_id: str,
    ) -> AttachmentRecord:
        now = datetime.now(UTC)
        async with self._db_factory() as db:
            record = await db.get(AttachmentRecord, attachment_id)
            if record is None:
                raise AttachmentNotFoundError(f"Attachment not found: {attachment_id}")
            if record.status != "uploaded" or record.session_id is not None:
                raise AttachmentConflictError(
                    f"Attachment {attachment_id!r} is not available for agent send"
                )
            record.status = "attached"
            record.agent_type = agent_type
            record.session_id = session_id
            record.attached_at = now
            await db.commit()
            await db.refresh(record)
            return record

    # Internal only: opens its own DB session and is NOT atomic with timeline writes.
    # The canonical status transition is done inline in
    # SessionStore.append_user_turn_with_attachments.
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
            return int(result.rowcount)  # type: ignore[attr-defined]

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

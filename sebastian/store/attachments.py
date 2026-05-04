from __future__ import annotations

import hashlib
import logging
import os
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import (
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.store.models import AttachmentRecord

logger = logging.getLogger(__name__)

# DecompressionBomb 防护：仅设置像素上限常量。
# DecompressionBombWarning → Error 的升级在 _maybe_generate_thumbnail 内部
# 用 warnings.catch_warnings() 作用域化处理，避免进程级副作用。
Image.MAX_IMAGE_PIXELS = 100_000_000

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
ALLOWED_DOWNLOAD_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    }
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
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
_THUMB_EXT_TO_MIME: dict[str, str] = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _maybe_generate_thumbnail(root_dir: Path, sha: str, data: bytes) -> tuple[Path | None, bool]:
    """对图片字节生成 256×256 缩略图，写到 thumbs/<sha[:2]>/<sha>.<ext>。

    返回 (thumb_abs, created)：
      - thumb_abs is None / created False：未生成（不支持的格式或异常降级）
      - thumb_abs not None / created True：本次新写入了 thumb 文件
      - thumb_abs not None / created False：thumb 已存在，跳过写入（dedup）
    """
    try:
        # catch_warnings 将 filter 变更限定在本次调用栈，退出后自动还原，
        # 不污染进程全局 filter list。asyncio 单线程下无线程安全问题。
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as opened:
                opened.load()
                img: Image.Image = opened  # convert/exif_transpose 返回 Image.Image
                src_format = img.format or ""
                if src_format == "GIF":
                    img.seek(0)
                    ext: str = "png"
                    save_format = "PNG"
                else:
                    _ext = _THUMB_EXT_BY_FORMAT.get(src_format)
                    if _ext is None:
                        return None, False
                    ext = _ext
                    save_format = src_format

                thumb_rel = f"thumbs/{sha[:2]}/{sha}.{ext}"
                thumb_abs = root_dir / thumb_rel
                if thumb_abs.exists():
                    return thumb_abs, False

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

                thumb_abs.parent.mkdir(parents=True, exist_ok=True)
                (root_dir / "tmp").mkdir(parents=True, exist_ok=True)
                tmp_path = root_dir / "tmp" / str(uuid4())
                try:
                    save_kwargs: dict[str, Any] = {"format": save_format, "optimize": True}
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
        elif kind == "download":
            self._validate_download(filename, content_type, data)
        else:
            raise AttachmentValidationError(f"Unknown kind: {kind!r}")

        sha = hashlib.sha256(data).hexdigest()
        blob_rel = f"blobs/{sha[:2]}/{sha}"
        blob_abs = self._root_dir / blob_rel

        created_blob = False
        if not blob_abs.exists():
            blob_abs.parent.mkdir(parents=True, exist_ok=True)
            (self._root_dir / "tmp").mkdir(parents=True, exist_ok=True)
            tmp_path = self._root_dir / "tmp" / str(uuid4())
            try:
                tmp_path.write_bytes(data)
                os.replace(tmp_path, blob_abs)
                created_blob = True
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise

        text_excerpt: str | None = None
        if kind == "text_file":
            text = data.decode("utf-8")
            text_excerpt = text[:TEXT_EXCERPT_CHARS]

        created_thumb = False
        thumb_abs: Path | None = None
        if kind == "image":
            thumb_abs, created_thumb = _maybe_generate_thumbnail(self._root_dir, sha, data)

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
            # 二次查询：并发 upload 可能已用同 SHA 成功入库；只有当 DB 中
            # 完全没有该 SHA 的 record 时才能删本次新写入的文件。
            # 若二次查询本身也失败（DB 不可用），保守跳过 unlink 并记录 warning；
            # 孤儿文件留给下次 cleanup，不掩盖原始异常。
            if created_blob or created_thumb:
                try:
                    async with self._db_factory() as session2:
                        cnt = await session2.scalar(
                            select(func.count())
                            .select_from(AttachmentRecord)
                            .where(AttachmentRecord.sha256 == sha)
                        )
                except Exception as requery_exc:
                    logger.warning(
                        "upload rollback: re-query failed for sha=%s, skipping unlink: %s",
                        sha[:8],
                        requery_exc,
                    )
                else:
                    if (cnt or 0) == 0:
                        if created_blob:
                            blob_abs.unlink(missing_ok=True)
                        if created_thumb and thumb_abs is not None:
                            thumb_abs.unlink(missing_ok=True)
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

    def thumb_candidate_paths(self, record: AttachmentRecord) -> list[tuple[Path, str]]:
        """返回该 record 可能存在的 thumbnail 候选路径与对应 MIME。

        thumb 按 SHA 内容寻址，扩展名只可能是 jpg/png/webp 之一（取决于上传时
        生成的格式）。返回所有候选供调用方按顺序探测，命中第一个即可。

        每个返回项是 (absolute path, MIME type) 元组。所有路径均通过
        is_relative_to 检查，保证不会逃出 root_dir。
        """
        thumb_dir = (self._root_dir / "thumbs" / record.sha256[:2]).resolve()
        root_resolved = self._root_dir.resolve()
        if not thumb_dir.is_relative_to(root_resolved):
            raise ValueError(f"Thumb dir escapes root: {record.sha256!r}")

        candidates: list[tuple[Path, str]] = []
        for ext, mime in _THUMB_EXT_TO_MIME.items():
            path = thumb_dir / f"{record.sha256}.{ext}"
            candidates.append((path, mime))
        return candidates

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

    async def _check_still_referenced_shas(self, shas: set[str]) -> set[str]:
        """返回 `shas` 中仍被 AttachmentRecord 引用的 SHA。

        cleanup 在 commit DB 删除 record 之后、unlink 物理文件之前调用此方法做
        二次确认：commit 与 unlink 的窗口内可能有新 upload 命中同 SHA（blob 还在 →
        跳过写入 → 新 record 入库），此时不能 unlink，否则新 record 悬空。
        """
        if not shas:
            return set()
        async with self._db_factory() as session:
            rows = await session.execute(
                select(AttachmentRecord.sha256)
                .where(AttachmentRecord.sha256.in_(shas))
                .group_by(AttachmentRecord.sha256)
            )
            return {row[0] for row in rows.all()}

    async def cleanup(self, now: datetime | None = None) -> int:
        _now = now or datetime.now(UTC)
        uploaded_cutoff = _now - _UPLOADED_TTL
        orphan_cutoff = _now - _ORPHAN_TTL
        count = 0
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

            if not records:
                # 仍需清理 tmp 目录
                count += self._cleanup_tmp(uploaded_cutoff)
                return count

            batch_ids = {r.id for r in records}
            shas_in_batch = {r.sha256 for r in records}

            remaining_rows = await session.execute(
                select(AttachmentRecord.sha256, func.count())
                .where(
                    AttachmentRecord.sha256.in_(shas_in_batch),
                    AttachmentRecord.id.notin_(batch_ids),
                )
                .group_by(AttachmentRecord.sha256)
            )
            remaining_count = {row[0]: row[1] for row in remaining_rows.all()}

            pending_unlink: list[tuple[str, Path]] = []
            seen_shas: set[str] = set()
            for r in records:
                if remaining_count.get(r.sha256, 0) == 0 and r.sha256 not in seen_shas:
                    seen_shas.add(r.sha256)
                    pending_unlink.append((r.sha256, self.blob_absolute_path(r)))
                    thumb_dir = self._root_dir / "thumbs" / r.sha256[:2]
                    if thumb_dir.exists():
                        for thumb_path in thumb_dir.glob(f"{r.sha256}.*"):
                            pending_unlink.append((r.sha256, thumb_path))
                await session.delete(r)
                count += 1

            await session.commit()  # ← DB 必须先成功提交

        shas_to_check = {sha for sha, _ in pending_unlink}
        still_referenced = await self._check_still_referenced_shas(shas_to_check)

        for sha, p in pending_unlink:
            if sha in still_referenced:
                continue  # 新 upload 在窗口内入库，保留物理文件
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("cleanup unlink failed: %s: %s", p, exc)

        count += self._cleanup_tmp(uploaded_cutoff)
        return count

    def _cleanup_tmp(self, uploaded_cutoff: datetime) -> int:
        cleaned = 0
        tmp_dir = self._root_dir / "tmp"
        if tmp_dir.exists():
            for tmp_file in tmp_dir.iterdir():
                if tmp_file.is_file():
                    try:
                        mtime = datetime.fromtimestamp(tmp_file.stat().st_mtime, UTC)
                        if mtime < uploaded_cutoff:
                            tmp_file.unlink(missing_ok=True)
                            cleaned += 1
                    except OSError:
                        pass
        return cleaned

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

    def _validate_download(self, filename: str, content_type: str, data: bytes) -> None:
        if not filename:
            raise AttachmentValidationError("Download filename is required")
        if not data:
            raise AttachmentValidationError("Download data cannot be empty")
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise AttachmentValidationError("Download exceeds 50 MB limit")
        if content_type not in ALLOWED_DOWNLOAD_MIME_TYPES:
            raise AttachmentValidationError(f"Unsupported download MIME: {content_type!r}")

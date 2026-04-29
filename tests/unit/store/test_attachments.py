from __future__ import annotations

import asyncio
import hashlib as _hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.config import Settings
from sebastian.store.attachments import (
    AttachmentStore,
    AttachmentValidationError,
    _maybe_generate_thumbnail,
)
from sebastian.store.models import AttachmentRecord


def test_attachments_dir_lives_under_user_data_dir(tmp_path: Path) -> None:
    settings = Settings(sebastian_data_dir=str(tmp_path))
    assert settings.attachments_dir == tmp_path / "data" / "attachments"


@pytest.fixture
async def sqlite_session_factory(tmp_path):
    import sebastian.store.models  # noqa: F401
    from sebastian.store.database import Base, _apply_idempotent_migrations

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_idempotent_migrations(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


@pytest.fixture
async def attachment_store(tmp_path, sqlite_session_factory):
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return AttachmentStore(root_dir=root, db_factory=sqlite_session_factory)


# Step 1：文本文件上传成功
async def test_text_file_upload_success(attachment_store, tmp_path):
    content = b"# title\nhello world"
    result = await attachment_store.upload_bytes(
        filename="notes.md",
        content_type="text/markdown",
        kind="text_file",
        data=content,
    )
    assert result.kind == "text_file"
    assert result.status == "uploaded"
    # blob 路径按 sha256 前缀分级存储
    import hashlib

    sha = hashlib.sha256(content).hexdigest()
    assert result.sha256 == sha
    blob = attachment_store._root_dir / "blobs" / sha[:2] / sha
    assert blob.exists()
    assert result.text_excerpt is not None and "title" in result.text_excerpt


# Step 2：非法后缀、非 UTF-8、超大小
async def test_text_file_rejects_unsupported_extension(attachment_store):
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="report.pdf",
            content_type="text/plain",
            kind="text_file",
            data=b"hello",
        )


async def test_text_file_rejects_non_utf8(attachment_store):
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="data.txt",
            content_type="text/plain",
            kind="text_file",
            data=bytes([0xFF, 0xFE, 0x00]),
        )


async def test_text_file_rejects_over_size(attachment_store):
    big = b"x" * (2 * 1024 * 1024 + 1)
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="big.txt",
            content_type="text/plain",
            kind="text_file",
            data=big,
        )


# Step 3：文本 MIME 白名单
async def test_text_file_accepts_supported_mime_and_extension(attachment_store):
    result = await attachment_store.upload_bytes(
        filename="data.json",
        content_type="application/json",
        kind="text_file",
        data=b'{"key": "value"}',
    )
    assert result.kind == "text_file"


async def test_text_file_rejects_unsupported_mime_even_with_supported_extension(attachment_store):
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="notes.md",
            content_type="application/pdf",
            kind="text_file",
            data=b"# hello",
        )


# Step 4：图片 MIME 白名单
async def test_image_upload_jpeg_success(attachment_store):
    # 最小有效 JPEG header
    jpeg_bytes = bytes(
        [
            0xFF,
            0xD8,
            0xFF,
            0xE0,
            0x00,
            0x10,
            0x4A,
            0x46,
            0x49,
            0x46,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x01,
            0x00,
            0x01,
            0x00,
            0x00,
        ]
    )
    result = await attachment_store.upload_bytes(
        filename="photo.jpg",
        content_type="image/jpeg",
        kind="image",
        data=jpeg_bytes,
    )
    assert result.kind == "image"


@pytest.mark.asyncio
async def test_image_rejects_extensionless_filename(attachment_store):
    with pytest.raises(AttachmentValidationError, match="extension"):
        await attachment_store.upload_bytes(
            filename="photo",
            content_type="image/jpeg",
            kind="image",
            data=b"jpeg-bytes",
        )


async def test_image_rejects_svg(attachment_store):
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="icon.svg",
            content_type="image/svg+xml",
            kind="image",
            data=b"<svg/>",
        )


async def test_image_rejects_supported_mime_with_unsupported_extension(attachment_store):
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="payload.txt",
            content_type="image/png",
            kind="image",
            data=b"png-bytes",
        )


async def test_image_accepts_jpg_and_jpeg_extensions(attachment_store):
    jpg = await attachment_store.upload_bytes(
        filename="photo.jpg",
        content_type="image/jpeg",
        kind="image",
        data=b"jpeg-bytes-1",
    )
    jpeg = await attachment_store.upload_bytes(
        filename="photo.jpeg",
        content_type="image/jpeg",
        kind="image",
        data=b"jpeg-bytes-2",
    )
    assert jpg.kind == "image"
    assert jpeg.kind == "image"


# Step 5：read_text_content 返回完整内容
async def test_read_text_content_returns_full_not_excerpt(attachment_store):
    from sebastian.store.attachments import TEXT_EXCERPT_CHARS

    long_text = ("A" * 100 + "\n") * 30  # 超过 TEXT_EXCERPT_CHARS
    data = long_text.encode()
    result = await attachment_store.upload_bytes(
        filename="long.md",
        content_type="text/markdown",
        kind="text_file",
        data=data,
    )
    # DB 中 text_excerpt 被截断
    assert result.text_excerpt is not None
    assert len(result.text_excerpt) <= TEXT_EXCERPT_CHARS + 10
    # read_text_content 返回完整内容
    record = await attachment_store.get(result.id)
    assert record is not None
    full = attachment_store.read_text_content(record)
    assert full == long_text


# Step 6：cleanup 只删过期的 uploaded 和 orphaned，不动 attached
async def test_cleanup_deletes_expired_uploaded_and_orphaned_but_not_attached(
    sqlite_session_factory, tmp_path
):
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    store = AttachmentStore(root_dir=root, db_factory=sqlite_session_factory)

    now = datetime.now(UTC)
    expired = now - timedelta(hours=25)
    recent = now - timedelta(hours=1)

    # 为每条记录创建假 blob 文件
    def _make_blob(sha: str) -> str:
        blob_dir = root / "blobs" / sha[:2]
        blob_dir.mkdir(parents=True, exist_ok=True)
        (blob_dir / sha).write_bytes(b"x")
        return f"blobs/{sha[:2]}/{sha}"

    async with sqlite_session_factory() as session:
        r_uploaded = AttachmentRecord(
            id="att-upload-expired",
            kind="text_file",
            original_filename="a.txt",
            mime_type="text/plain",
            size_bytes=1,
            sha256="a" * 64,
            blob_path=_make_blob("a" * 64),
            status="uploaded",
            created_at=expired,
        )
        r_orphaned = AttachmentRecord(
            id="att-orphaned-expired",
            kind="text_file",
            original_filename="b.txt",
            mime_type="text/plain",
            size_bytes=1,
            sha256="b" * 64,
            blob_path=_make_blob("b" * 64),
            status="orphaned",
            created_at=expired,
            orphaned_at=expired,
        )
        r_attached = AttachmentRecord(
            id="att-attached-recent",
            kind="text_file",
            original_filename="c.txt",
            mime_type="text/plain",
            size_bytes=1,
            sha256="c" * 64,
            blob_path=_make_blob("c" * 64),
            status="attached",
            created_at=recent,
            attached_at=recent,
            agent_type="chat",
            session_id="s-keep",
        )
        session.add_all([r_uploaded, r_orphaned, r_attached])
        await session.commit()

    deleted = await store.cleanup(now=now)

    assert deleted == 2
    remaining = await store.get("att-attached-recent")
    assert remaining is not None
    assert await store.get("att-upload-expired") is None
    assert await store.get("att-orphaned-expired") is None


# Step 7：mark_session_orphaned 只流转指定 session 的 attached 记录
async def test_mark_session_orphaned_transitions_attached_only(sqlite_session_factory, tmp_path):
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    store = AttachmentStore(root_dir=root, db_factory=sqlite_session_factory)

    now = datetime.now(UTC)

    def _make_blob(sha: str) -> str:
        blob_dir = root / "blobs" / sha[:2]
        blob_dir.mkdir(parents=True, exist_ok=True)
        (blob_dir / sha).write_bytes(b"x")
        return f"blobs/{sha[:2]}/{sha}"

    async with sqlite_session_factory() as session:
        for i, att_id in enumerate(["att-s1-1", "att-s1-2"]):
            sha = str(i) * 64
            session.add(
                AttachmentRecord(
                    id=att_id,
                    kind="text_file",
                    original_filename=f"{i}.txt",
                    mime_type="text/plain",
                    size_bytes=1,
                    sha256=sha,
                    blob_path=_make_blob(sha),
                    status="attached",
                    created_at=now,
                    attached_at=now,
                    agent_type="chat",
                    session_id="s1",
                )
            )
        sha_s2 = "9" * 64
        session.add(
            AttachmentRecord(
                id="att-s2-1",
                kind="text_file",
                original_filename="s2.txt",
                mime_type="text/plain",
                size_bytes=1,
                sha256=sha_s2,
                blob_path=_make_blob(sha_s2),
                status="attached",
                created_at=now,
                attached_at=now,
                agent_type="chat",
                session_id="s2",
            )
        )
        await session.commit()

    count = await store.mark_session_orphaned(agent_type="chat", session_id="s1")

    assert count == 2

    r1 = await store.get("att-s1-1")
    r2 = await store.get("att-s1-2")
    r_s2 = await store.get("att-s2-1")

    assert r1 is not None and r1.status == "orphaned"
    assert r2 is not None and r2.status == "orphaned"
    assert r_s2 is not None and r_s2.status == "attached"


# ── _maybe_generate_thumbnail tests ─────────────────────────────────────────


def _make_image_bytes(format: str, size: tuple[int, int] = (800, 600), mode: str = "RGB") -> bytes:
    if mode == "P":
        color: int | tuple[int, ...] = 42
    elif mode == "RGBA":
        color = (120, 200, 50, 200)
    else:
        color = (120, 200, 50)
    img = Image.new(mode, size, color=color)
    buf = BytesIO()
    save_kwargs: dict = {"format": format}
    if format == "JPEG":
        save_kwargs["quality"] = 85
    img.save(buf, **save_kwargs)
    return buf.getvalue()


def test_thumbnail_jpeg_happy_path(tmp_path: Path) -> None:
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs is not None
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.jpg"
    assert thumb_abs.exists()
    with Image.open(thumb_abs) as out:
        assert out.format == "JPEG"
        assert max(out.size) <= 256


def test_thumbnail_png_happy_path(tmp_path: Path) -> None:
    data = _make_image_bytes("PNG", mode="RGBA")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.png"
    with Image.open(thumb_abs) as out:
        assert out.format == "PNG"
        assert max(out.size) <= 256


def test_thumbnail_webp_happy_path(tmp_path: Path) -> None:
    data = _make_image_bytes("WEBP")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.webp"
    with Image.open(thumb_abs) as out:
        assert out.format == "WEBP"


def test_thumbnail_gif_first_frame_as_png(tmp_path: Path) -> None:
    data = _make_image_bytes("GIF", mode="P")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    # GIF 强制走 PNG 输出
    assert thumb_abs == tmp_path / "thumbs" / sha[:2] / f"{sha}.png"
    with Image.open(thumb_abs) as out:
        assert out.format == "PNG"


def test_thumbnail_unsupported_format_returns_none(tmp_path: Path) -> None:
    # BMP 不在 _THUMB_EXT_BY_FORMAT 里
    data = _make_image_bytes("BMP")
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs is None
    assert created is False


def test_thumbnail_exif_orientation_corrected(tmp_path: Path) -> None:
    """带 EXIF Orientation=6（顺时针 90°）的 JPEG，缩略图应已校正方向。"""
    img = Image.new("RGB", (800, 400), color=(255, 0, 0))  # 800×400 横图
    buf = BytesIO()
    # 写入 EXIF Orientation=6（旋转 90 CW）
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(buf, format="JPEG", exif=exif.tobytes(), quality=85)
    data = buf.getvalue()
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, _ = _maybe_generate_thumbnail(tmp_path, sha, data)
    assert thumb_abs is not None

    with Image.open(thumb_abs) as out:
        # 校正后原本 800×400 横图应被旋转为竖图，宽 < 高
        assert out.width < out.height


def test_thumbnail_png_palette_with_transparency(tmp_path: Path) -> None:
    """P 模式 + transparency 信息的 PNG：转 RGBA 后输出，alpha 保留。"""
    img = Image.new("P", (200, 200))
    img.putpalette([0, 0, 0] * 256)
    buf = BytesIO()
    img.save(buf, format="PNG", transparency=0)
    data = buf.getvalue()
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert created is True
    assert thumb_abs is not None
    with Image.open(thumb_abs) as out:
        assert out.format == "PNG"
        # 应已转换为 RGBA（保留透明信息），不是 P
        assert out.mode == "RGBA"

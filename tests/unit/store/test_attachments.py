from __future__ import annotations

import asyncio
import hashlib as _hashlib
import logging
import os
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


def test_thumbnail_decompression_bomb_warning_upgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超过 MAX_IMAGE_PIXELS 触发 DecompressionBombWarning。

    应被 simplefilter 升级为 Error 并降级，thumbnail 不生成。
    """

    class _BombingImage:
        format = "JPEG"
        mode = "RGB"
        size = (20000, 20000)

        def load(self):
            import warnings
            warnings.warn("simulated bomb", Image.DecompressionBombWarning)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _fake_open(_buf):
        return _BombingImage()

    monkeypatch.setattr("sebastian.store.attachments.Image.open", _fake_open)

    data = b"\xff\xd8\xff\xe0fake"
    sha = _hashlib.sha256(data).hexdigest()

    thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs is None
    assert created is False
    # 没有写入 thumb
    assert not (tmp_path / "thumbs").exists() or not any((tmp_path / "thumbs").rglob("*"))


def test_thumbnail_generic_exception_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """img.save 抛 MemoryError / RuntimeError 也走外层 except Exception 兜底。"""
    real_open = Image.open

    class _BadSaveImage:
        def __init__(self, real):
            self._real = real
            self.format = real.format
            self.mode = real.mode
            self.size = real.size

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

        def load(self):
            self._real.load()

        def thumbnail(self, *a, **kw):
            self._real.thumbnail(*a, **kw)

        def save(self, *_a, **_kw):
            raise MemoryError("simulated OOM")

    def _fake_open(buf):
        real = real_open(buf)
        return _BadSaveImage(real)

    monkeypatch.setattr("sebastian.store.attachments.Image.open", _fake_open)
    monkeypatch.setattr(
        "sebastian.store.attachments.ImageOps.exif_transpose",
        lambda im: im,
    )

    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()

    with caplog.at_level(logging.WARNING, logger="sebastian.store.attachments"):
        thumb_abs, created = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs is None
    assert created is False
    assert any("thumbnail generation skipped" in m for m in caplog.messages)


async def test_upload_bytes_dedup_skips_blob_write(
    attachment_store: AttachmentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"hello dedup world"
    await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )

    # 第二次上传：mock os.replace 验证未被调用
    call_count = {"n": 0}
    real_replace = os.replace

    def _counting_replace(*args, **kwargs):
        call_count["n"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr("sebastian.store.attachments.os.replace", _counting_replace)

    await attachment_store.upload_bytes(
        filename="b.md", content_type="text/markdown", kind="text_file", data=data
    )
    assert call_count["n"] == 0  # blob 未被重新写入


def test_thumbnail_dedup_skips_save_when_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()

    # 第一次正常生成
    thumb_abs1, created1 = _maybe_generate_thumbnail(tmp_path, sha, data)
    assert created1 is True
    assert thumb_abs1.exists()

    # 第二次：mock os.replace 验证未被调用
    real_replace = os.replace
    call_count = {"n": 0}

    def _counting_replace(*args, **kwargs):
        call_count["n"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr("sebastian.store.attachments.os.replace", _counting_replace)

    thumb_abs2, created2 = _maybe_generate_thumbnail(tmp_path, sha, data)

    assert thumb_abs2 == thumb_abs1
    assert created2 is False
    assert call_count["n"] == 0  # 未执行 os.replace


async def test_upload_bytes_db_failure_keeps_dedup_blob(
    attachment_store: AttachmentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB commit 失败 + blob 是 dedup 命中（非本次新建）→ 不删 blob。"""
    data = b"shared blob content"
    await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha
    assert blob_abs.exists()

    # 让 DB commit 抛异常
    real_factory = attachment_store._db_factory

    def _failing_factory():
        sess = real_factory()

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()

                async def _bad_commit():
                    raise RuntimeError("simulated commit failure")

                self._inner.commit = _bad_commit
                return self._inner

            async def __aexit__(self, *args):
                return await sess.__aexit__(*args)

        return _W()

    monkeypatch.setattr(attachment_store, "_db_factory", _failing_factory)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await attachment_store.upload_bytes(
            filename="b.md", content_type="text/markdown", kind="text_file", data=data
        )

    # blob 必须保留（已有 record 在用）
    assert blob_abs.exists()


async def test_upload_bytes_db_failure_deletes_new_blob_when_no_other_record(
    attachment_store: AttachmentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB commit 失败 + blob 是本次新建 + 无其他 record → 删 blob。"""
    data = b"unique brand new content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    real_factory = attachment_store._db_factory

    def _failing_factory():
        sess = real_factory()

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()

                async def _bad_commit():
                    raise RuntimeError("simulated commit failure")

                self._inner.commit = _bad_commit
                return self._inner

            async def __aexit__(self, *args):
                return await sess.__aexit__(*args)

        return _W()

    monkeypatch.setattr(attachment_store, "_db_factory", _failing_factory)

    with pytest.raises(RuntimeError):
        await attachment_store.upload_bytes(
            filename="x.md", content_type="text/markdown", kind="text_file", data=data
        )

    # blob 必须被删除（没有任何 record 引用它）
    assert not blob_abs.exists()


async def test_upload_bytes_db_failure_keeps_blob_when_concurrent_record_exists(
    attachment_store: AttachmentStore,
    sqlite_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发安全：created_blob=True 但 DB 中已有同 SHA record，二次查询找到 → blob 保留。

    模拟：upload A 新建 blob（created_blob=True），但在 A 的 DB commit 失败前，
    并发 upload B 已用同 SHA 成功入库。回滚时二次查询应找到 B 的 record，
    阻止 A 误删共享 blob。
    """
    from uuid import uuid4

    data = b"concurrent shared content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    # 模拟"并发 upload B 已成功提交 record"
    async with sqlite_session_factory() as session:
        concurrent_rec = AttachmentRecord(
            id=str(uuid4()),
            kind="text_file",
            original_filename="from_concurrent_upload.md",
            mime_type="text/markdown",
            size_bytes=len(data),
            sha256=sha,
            blob_path=f"blobs/{sha[:2]}/{sha}",
            text_excerpt=None,
            status="uploaded",
            created_at=datetime.now(UTC),
            owner_user_id=None,
        )
        session.add(concurrent_rec)
        await session.commit()

    # 强制让本次 upload 走"新建 blob"路径：删掉可能存在的 blob 文件
    blob_abs.unlink(missing_ok=True)
    assert not blob_abs.exists()

    # 让本次 upload 的 DB commit 失败（触发回滚分支）
    real_factory = attachment_store._db_factory

    def _failing_factory():
        sess = real_factory()

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()

                async def _bad_commit():
                    raise RuntimeError("simulated commit failure")

                self._inner.commit = _bad_commit
                return self._inner

            async def __aexit__(self, *args):
                return await sess.__aexit__(*args)

        return _W()

    monkeypatch.setattr(attachment_store, "_db_factory", _failing_factory)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await attachment_store.upload_bytes(
            filename="a.md",
            content_type="text/markdown",
            kind="text_file",
            data=data,
        )

    # 关键断言：created_blob=True 但二次查询发现 B 的 record，blob 必须保留
    assert blob_abs.exists()


async def test_cleanup_keeps_blob_when_other_record_uses_same_sha(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """两条 record 同 SHA：一条过期一条活跃 → 清理后 blob 保留。"""
    data = b"shared content for cleanup"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    # 第一条：手动写成已过期的 uploaded
    r1 = await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    # 第二条：活跃 uploaded
    await attachment_store.upload_bytes(
        filename="b.md", content_type="text/markdown", kind="text_file", data=data
    )

    # 把 r1 created_at 改成 2 天前，触发 uploaded TTL
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r1.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    deleted = await attachment_store.cleanup()
    assert deleted >= 1
    assert blob_abs.exists()  # 第二条仍持有引用


async def test_cleanup_deletes_blob_when_last_record_removed(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """同 SHA 两条 record 都过期 → blob 被删（最后一条引用消失）。"""
    data = b"dies together content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r1 = await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    r2 = await attachment_store.upload_bytes(
        filename="b.md", content_type="text/markdown", kind="text_file", data=data
    )

    async with sqlite_session_factory() as session:
        for rid in (r1.id, r2.id):
            rec = await session.get(AttachmentRecord, rid)
            rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    deleted = await attachment_store.cleanup()
    assert deleted >= 2
    assert not blob_abs.exists()


async def test_cleanup_deletes_thumbnail_via_glob(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """image record 过期且 SHA 无其他引用 → thumbs/<sha[:2]>/<sha>.* 被删。"""
    data = _make_image_bytes("JPEG")
    sha = _hashlib.sha256(data).hexdigest()
    thumb_abs = attachment_store._root_dir / "thumbs" / sha[:2] / f"{sha}.jpg"

    r = await attachment_store.upload_bytes(
        filename="x.jpg", content_type="image/jpeg", kind="image", data=data
    )
    assert thumb_abs.exists()

    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    await attachment_store.cleanup()
    assert not thumb_abs.exists()


async def test_cleanup_db_failure_keeps_files(
    attachment_store: AttachmentStore, sqlite_session_factory, monkeypatch
) -> None:
    """cleanup commit 失败时不能 unlink 物理文件（违反不变量）。"""
    data = b"db failure content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r = await attachment_store.upload_bytes(
        filename="a.md", content_type="text/markdown", kind="text_file", data=data
    )
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    # mock：让 cleanup 内部的 commit 抛错
    real_factory = attachment_store._db_factory
    fail_first = {"done": False}

    def _factory_with_failing_commit():
        sess = real_factory()

        class _W:
            async def __aenter__(self):
                self._inner = await sess.__aenter__()
                if not fail_first["done"]:
                    fail_first["done"] = True

                    async def _bad_commit():
                        raise RuntimeError("simulated cleanup commit failure")

                    self._inner.commit = _bad_commit
                return self._inner

            async def __aexit__(self, *args):
                return await sess.__aexit__(*args)

        return _W()

    monkeypatch.setattr(attachment_store, "_db_factory", _factory_with_failing_commit)

    with pytest.raises(RuntimeError, match="simulated cleanup commit failure"):
        await attachment_store.cleanup()

    # blob 必须保留
    assert blob_abs.exists()


async def test_cleanup_skips_unlink_when_confirm_finds_references(
    attachment_store: AttachmentStore,
    sqlite_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟 commit 与 unlink 之间出现新 upload：把 _check_still_referenced_shas
    monkeypatch 成"全部仍有引用"，验证 unlink 被跳过、blob 保留。"""
    data = b"two-step confirm content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r = await attachment_store.upload_bytes(
        filename="x.md", content_type="text/markdown", kind="text_file", data=data
    )
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    async def _fake_check(_self, shas):
        # 模拟二次确认时，所有 SHA 都仍有引用（被并发 upload 占用）
        return set(shas)

    monkeypatch.setattr(
        AttachmentStore,
        "_check_still_referenced_shas",
        _fake_check,
    )

    await attachment_store.cleanup()
    assert blob_abs.exists()


async def test_cleanup_unlinks_when_confirm_returns_empty(
    attachment_store: AttachmentStore, sqlite_session_factory
) -> None:
    """二次确认返回空集合（确实无并发引用）→ blob 被 unlink。
    顺带覆盖 _check_still_referenced_shas 默认实现的 happy path。"""
    data = b"safe to delete content"
    sha = _hashlib.sha256(data).hexdigest()
    blob_abs = attachment_store._root_dir / "blobs" / sha[:2] / sha

    r = await attachment_store.upload_bytes(
        filename="x.md", content_type="text/markdown", kind="text_file", data=data
    )
    async with sqlite_session_factory() as session:
        rec = await session.get(AttachmentRecord, r.id)
        rec.created_at = datetime.now(UTC) - timedelta(hours=48)
        await session.commit()

    await attachment_store.cleanup()
    assert not blob_abs.exists()

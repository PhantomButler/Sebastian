from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.config import Settings
from sebastian.store.attachments import AttachmentStore


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
    with pytest.raises(Exception):
        await attachment_store.upload_bytes(
            filename="report.pdf",
            content_type="text/plain",
            kind="text_file",
            data=b"hello",
        )


async def test_text_file_rejects_non_utf8(attachment_store):
    with pytest.raises(Exception):
        await attachment_store.upload_bytes(
            filename="data.txt",
            content_type="text/plain",
            kind="text_file",
            data=bytes([0xFF, 0xFE, 0x00]),
        )


async def test_text_file_rejects_over_size(attachment_store):
    big = b"x" * (2 * 1024 * 1024 + 1)
    with pytest.raises(Exception):
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
    with pytest.raises(Exception):
        await attachment_store.upload_bytes(
            filename="notes.md",
            content_type="application/pdf",
            kind="text_file",
            data=b"# hello",
        )


# Step 4：图片 MIME 白名单
async def test_image_upload_jpeg_success(attachment_store):
    # 最小有效 JPEG header
    jpeg_bytes = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
    ])
    result = await attachment_store.upload_bytes(
        filename="photo.jpg",
        content_type="image/jpeg",
        kind="image",
        data=jpeg_bytes,
    )
    assert result.kind == "image"


async def test_image_rejects_svg(attachment_store):
    with pytest.raises(Exception):
        await attachment_store.upload_bytes(
            filename="icon.svg",
            content_type="image/svg+xml",
            kind="image",
            data=b"<svg/>",
        )


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

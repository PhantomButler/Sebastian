from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.tool_context import _current_tool_ctx
from sebastian.permissions.types import ToolCallContext
from sebastian.store.attachments import (
    AttachmentConflictError,
    AttachmentStore,
)


@pytest.fixture
async def sqlite_session_factory(tmp_path: Path):
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
async def attachment_store(tmp_path: Path, sqlite_session_factory):
    root = tmp_path / "attachments"
    for sub in ("blobs", "thumbs", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return AttachmentStore(root_dir=root, db_factory=sqlite_session_factory)


@pytest.fixture
def patched_state(attachment_store, sqlite_session_factory):
    from sebastian.store.todo_store import TodoStore

    todo_store = TodoStore(db_factory=sqlite_session_factory)

    fake_state = MagicMock()
    fake_state.todo_store = todo_store
    fake_state.attachment_store = attachment_store
    fake_state.event_bus = MagicMock()
    fake_state.event_bus.publish = AsyncMock()

    with patch.dict("sys.modules", {"sebastian.gateway.state": fake_state}):
        yield fake_state, attachment_store


@pytest.fixture
def set_ctx():
    tokens = []

    def _set(session_id: str = "s1", agent_type: str = "sebastian") -> None:
        ctx = ToolCallContext(
            task_goal="t",
            session_id=session_id,
            task_id=None,
            agent_type=agent_type,
        )
        tokens.append(_current_tool_ctx.set(ctx))

    yield _set
    for tok in tokens:
        try:
            _current_tool_ctx.reset(tok)
        except ValueError:
            pass


# ── Part A: mark_agent_sent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_agent_sent_binds_uploaded_attachment(attachment_store: AttachmentStore) -> None:
    uploaded = await attachment_store.upload_bytes(
        filename="notes.md",
        content_type="text/markdown",
        kind="text_file",
        data=b"# hello",
    )

    record = await attachment_store.mark_agent_sent(
        attachment_id=uploaded.id,
        agent_type="sebastian",
        session_id="s1",
    )

    assert record.status == "attached"
    assert record.agent_type == "sebastian"
    assert record.session_id == "s1"
    assert record.attached_at is not None


@pytest.mark.asyncio
async def test_mark_agent_sent_raises_conflict_on_already_attached(
    attachment_store: AttachmentStore,
) -> None:
    uploaded = await attachment_store.upload_bytes(
        filename="notes.md",
        content_type="text/markdown",
        kind="text_file",
        data=b"# hello",
    )

    await attachment_store.mark_agent_sent(
        attachment_id=uploaded.id,
        agent_type="sebastian",
        session_id="s1",
    )

    with pytest.raises(AttachmentConflictError):
        await attachment_store.mark_agent_sent(
            attachment_id=uploaded.id,
            agent_type="sebastian",
            session_id="s1",
        )


@pytest.mark.asyncio
async def test_mark_agent_sent_raises_not_found(attachment_store: AttachmentStore) -> None:
    from sebastian.store.attachments import AttachmentNotFoundError

    with pytest.raises(AttachmentNotFoundError):
        await attachment_store.mark_agent_sent(
            attachment_id="nonexistent-id",
            agent_type="sebastian",
            session_id="s1",
        )


# ── Part B: send_file tool ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_file_uploads_text_file_and_returns_artifact(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")

    file_path = tmp_path / "notes.md"
    file_path.write_text("# hello", encoding="utf-8")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is True
    artifact = result.output["artifact"]
    assert artifact["kind"] == "text_file"
    assert artifact["filename"] == "notes.md"
    assert artifact["download_url"].startswith("/api/v1/attachments/")
    assert "text_excerpt" not in artifact
    assert "thumbnail_url" not in artifact
    assert result.display == "已向用户发送文件 notes.md"

    att_id = artifact["attachment_id"]
    record = await store.get(att_id)
    assert record is not None
    assert record.status == "attached"
    assert record.agent_type == "sebastian"


@pytest.mark.asyncio
async def test_send_file_uploads_image_and_returns_artifact(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 10
    file_path = tmp_path / "photo.jpg"
    file_path.write_bytes(jpeg_bytes)

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is True
    artifact = result.output["artifact"]
    assert artifact["kind"] == "image"
    assert artifact["filename"] == "photo.jpg"
    assert "thumbnail_url" in artifact
    assert "text_excerpt" not in artifact
    assert result.display == "已向用户发送图片 photo.jpg"


@pytest.mark.asyncio
async def test_send_file_display_name_overrides_filename(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")

    file_path = tmp_path / "notes.md"
    file_path.write_text("hello", encoding="utf-8")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path), display_name="renamed")

    assert result.ok is True
    artifact = result.output["artifact"]
    assert artifact["filename"] == "renamed.md"
    assert result.display == "已向用户发送文件 renamed.md"


@pytest.mark.asyncio
async def test_send_file_display_name_with_suffix_used_as_is(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")

    file_path = tmp_path / "notes.md"
    file_path.write_text("hello", encoding="utf-8")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path), display_name="my_doc.txt")

    assert result.ok is True
    artifact = result.output["artifact"]
    assert artifact["filename"] == "my_doc.txt"


@pytest.mark.asyncio
async def test_send_file_no_context_returns_error(patched_state, tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("hello", encoding="utf-8")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is False
    assert "send_file requires session context" in result.error
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_send_file_missing_file_returns_error(patched_state, set_ctx, tmp_path: Path) -> None:
    set_ctx("s1", "sebastian")
    missing = str(tmp_path / "no_such_file.md")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(missing)

    assert result.ok is False
    assert "File not found" in result.error
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_send_file_directory_returns_error(patched_state, set_ctx, tmp_path: Path) -> None:
    set_ctx("s1", "sebastian")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(tmp_path))

    assert result.ok is False
    assert "directory" in result.error.lower()
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_send_file_unsupported_type_returns_error(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    set_ctx("s1", "sebastian")

    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"PK\x03\x04")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is False
    assert "Unsupported file type" in result.error
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_send_file_too_large_returns_error(patched_state, set_ctx, tmp_path: Path) -> None:
    MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2MB
    too_large = tmp_path / "big.txt"
    too_large.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    set_ctx("s1", "sebastian")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(too_large))

    assert result.ok is False
    assert "Do not retry automatically" in result.error
    size_words = ["large", "exceeds", "limit", "bytes", "mb"]
    assert any(word in result.error.lower() for word in size_words)


@pytest.mark.asyncio
async def test_send_file_read_error_returns_stable_error(
    patched_state, set_ctx, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("hello", encoding="utf-8")
    set_ctx("s1", "sebastian")

    def deny_read(self: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", deny_read)

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is False
    assert str(file_path) in result.error
    assert "denied" in result.error
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_send_file_attachment_store_unavailable(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    fake_state, _ = patched_state
    fake_state.attachment_store = None
    set_ctx("s1", "sebastian")

    file_path = tmp_path / "notes.md"
    file_path.write_text("hello", encoding="utf-8")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is False
    assert "unavailable" in result.error.lower()
    assert "Do not retry automatically" in result.error

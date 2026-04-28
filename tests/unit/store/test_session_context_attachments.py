from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.store.session_context import build_context_messages


@pytest.fixture
def user_message_item() -> dict[str, Any]:
    return {
        "kind": "user_message",
        "content": "总结",
        "exchange_id": "exch-1",
    }


@pytest.fixture
def text_attachment_item() -> dict[str, Any]:
    return {
        "kind": "attachment",
        "exchange_id": "exch-1",
        "payload": {
            "attachment_id": "att-1",
            "kind": "text_file",
            "original_filename": "notes.md",
            "mime_type": "text/markdown",
        },
    }


def _make_text_store(text_content: str = "hello") -> MagicMock:
    store = MagicMock()
    record = MagicMock()
    record.mime_type = "text/markdown"
    store.get = AsyncMock(return_value=record)
    store.read_text_content = MagicMock(return_value=text_content)
    store.blob_absolute_path = MagicMock()
    return store


async def test_text_attachment_projected_as_fenced_text_block(
    user_message_item: dict[str, Any],
    text_attachment_item: dict[str, Any],
) -> None:
    store = _make_text_store("hello")
    items = [user_message_item, text_attachment_item]
    messages = await build_context_messages(items, "anthropic", attachment_store=store)
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    text_blocks = [b for b in content if b.get("type") == "text"]
    combined_text = "\n".join(b["text"] for b in text_blocks)
    assert "notes.md" in combined_text
    assert "hello" in combined_text
    assert "```" in combined_text  # fenced code block


async def test_text_attachment_user_message_text_also_present(
    user_message_item: dict[str, Any],
    text_attachment_item: dict[str, Any],
) -> None:
    store = _make_text_store("content here")
    items = [user_message_item, text_attachment_item]
    messages = await build_context_messages(items, "anthropic", attachment_store=store)
    content = messages[0]["content"]
    assert isinstance(content, list)
    # First block should be the original user text
    assert content[0] == {"type": "text", "text": "总结"}
    # Second block should be the attachment
    assert content[1]["type"] == "text"
    assert "notes.md" in content[1]["text"]


async def test_text_attachment_uses_full_content_not_excerpt(
    user_message_item: dict[str, Any],
) -> None:
    long_text = "x" * 3000  # > TEXT_EXCERPT_CHARS=2000
    store = _make_text_store(long_text)
    att_item: dict[str, Any] = {
        "kind": "attachment",
        "exchange_id": "exch-1",
        "payload": {
            "attachment_id": "att-1",
            "kind": "text_file",
            "original_filename": "big.txt",
            "mime_type": "text/plain",
            "text_excerpt": "x" * 2000,  # truncated excerpt
        },
    }
    items = [user_message_item, att_item]
    messages = await build_context_messages(items, "anthropic", attachment_store=store)
    content = messages[0]["content"]
    combined = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
    assert len(combined) >= 3000


async def test_require_attachments_true_raises_when_store_none(
    user_message_item: dict[str, Any],
    text_attachment_item: dict[str, Any],
) -> None:
    items = [user_message_item, text_attachment_item]
    with pytest.raises(ValueError, match="attachment_store is required"):
        await build_context_messages(
            items, "anthropic", attachment_store=None, require_attachments=True
        )


async def test_require_attachments_false_skips_silently(
    user_message_item: dict[str, Any],
    text_attachment_item: dict[str, Any],
) -> None:
    items = [user_message_item, text_attachment_item]
    messages = await build_context_messages(
        items, "anthropic", attachment_store=None, require_attachments=False
    )
    # Should produce 1 user message with just the text, no attachment block
    assert len(messages) == 1
    # Content is a plain string (simplified from single-text content_list)
    assert messages[0]["content"] == "总结"


async def test_image_attachment_projected_as_base64_block() -> None:
    fake_bytes = b"\x89PNG\r\n"
    store = MagicMock()
    record = MagicMock()
    record.mime_type = "image/png"
    store.get = AsyncMock(return_value=record)
    blob_path = MagicMock()
    blob_path.read_bytes = MagicMock(return_value=fake_bytes)
    store.blob_absolute_path = MagicMock(return_value=blob_path)

    items: list[dict[str, Any]] = [
        {"kind": "user_message", "content": "看图", "exchange_id": "exch-2"},
        {
            "kind": "attachment",
            "exchange_id": "exch-2",
            "payload": {
                "attachment_id": "att-2",
                "kind": "image",
                "original_filename": "photo.png",
                "mime_type": "image/png",
            },
        },
    ]
    messages = await build_context_messages(items, "anthropic", attachment_store=store)
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    image_blocks = [b for b in content if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["type"] == "base64"
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == base64.b64encode(fake_bytes).decode()


async def test_attachment_without_matching_exchange_is_skipped() -> None:
    """Attachment with different exchange_id from pending user → silently skipped."""
    store = _make_text_store("text")
    items: list[dict[str, Any]] = [
        {"kind": "user_message", "content": "hello", "exchange_id": "exch-A"},
        {
            "kind": "attachment",
            "exchange_id": "exch-B",  # different exchange_id
            "payload": {
                "attachment_id": "att-x",
                "kind": "text_file",
                "original_filename": "orphan.txt",
                "mime_type": "text/plain",
            },
        },
    ]
    messages = await build_context_messages(items, "anthropic", attachment_store=store)
    # user message emitted normally, orphan attachment skipped
    assert len(messages) == 1
    assert messages[0]["content"] == "hello"


async def test_multiple_attachments_same_exchange() -> None:
    """Two attachments on the same exchange both get merged into the user message."""
    store = MagicMock()
    record = MagicMock()
    record.mime_type = "text/plain"
    store.get = AsyncMock(return_value=record)
    store.read_text_content = MagicMock(return_value="file content")

    items: list[dict[str, Any]] = [
        {"kind": "user_message", "content": "两个文件", "exchange_id": "exch-3"},
        {
            "kind": "attachment",
            "exchange_id": "exch-3",
            "payload": {
                "attachment_id": "att-3a",
                "kind": "text_file",
                "original_filename": "a.txt",
                "mime_type": "text/plain",
            },
        },
        {
            "kind": "attachment",
            "exchange_id": "exch-3",
            "payload": {
                "attachment_id": "att-3b",
                "kind": "text_file",
                "original_filename": "b.txt",
                "mime_type": "text/plain",
            },
        },
    ]
    messages = await build_context_messages(items, "anthropic", attachment_store=store)
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    # 1 user text block + 2 attachment blocks
    assert len(content) == 3
    filenames = [b.get("text", "") for b in content if b.get("type") == "text"]
    combined = "\n".join(filenames)
    assert "a.txt" in combined
    assert "b.txt" in combined


@pytest.mark.asyncio
async def test_orphan_attachment_raises_when_require_attachments_true() -> None:
    """Orphan attachment (no matching pending user exchange) must raise when require_attachments=True and store=None."""
    items = [
        {
            "kind": "attachment",
            "seq": 1,
            "exchange_id": "exc-orphan",
            "role": "user",
            "content": "photo.jpg",
            "payload": {"attachment_id": "att-1", "kind": "image"},
        }
    ]
    with pytest.raises(ValueError, match="attachment_store is required"):
        await build_context_messages(
            items,
            provider_format="anthropic",
            attachment_store=None,
            require_attachments=True,
        )


@pytest.mark.asyncio
async def test_orphan_attachment_skipped_when_require_attachments_false() -> None:
    """Orphan attachment must be silently skipped when require_attachments=False and store=None."""
    items = [
        {
            "kind": "attachment",
            "seq": 1,
            "exchange_id": "exc-orphan",
            "role": "user",
            "content": "photo.jpg",
            "payload": {"attachment_id": "att-1", "kind": "image"},
        }
    ]
    result = await build_context_messages(
        items,
        provider_format="anthropic",
        attachment_store=None,
        require_attachments=False,
    )
    assert result == []


async def test_openai_attachment_skipped() -> None:
    """OpenAI format silently skips attachment items."""
    items: list[dict[str, Any]] = [
        {"kind": "user_message", "content": "hi", "exchange_id": "exch-1"},
        {
            "kind": "attachment",
            "exchange_id": "exch-1",
            "payload": {
                "attachment_id": "att-1",
                "kind": "text_file",
                "original_filename": "f.txt",
                "mime_type": "text/plain",
            },
        },
    ]
    messages = await build_context_messages(items, "openai", attachment_store=None)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hi"

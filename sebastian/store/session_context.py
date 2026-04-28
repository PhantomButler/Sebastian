"""Timeline → LLM provider context message projection.

Converts a flat list of timeline item dicts (as returned by
SessionTimelineStore.get_context_items) into the message format expected by
Anthropic or OpenAI-compatible providers.

Only produces plain ``dict`` output — no provider SDK types involved.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def build_context_messages(
    items: list[dict[str, Any]],
    provider_format: str,
    *,
    include_thinking: bool = False,
    attachment_store: Any | None = None,
    require_attachments: bool = True,
) -> list[dict[str, Any]]:
    """Project timeline items into provider-specific message dicts.

    Args:
        items: Timeline item dicts ordered by (effective_seq, seq).
        provider_format: ``"anthropic"`` or ``"openai"``.
        include_thinking: When True, include thinking blocks in Anthropic output.
        attachment_store: AttachmentStore instance for reading attachment content.
            Required when timeline contains ``attachment`` items and
            ``require_attachments=True``.
        require_attachments: When True (default), raise ValueError if an
            attachment item is encountered but ``attachment_store`` is None.
            When False, silently skip attachment items without a store.

    Returns:
        List of message dicts ready to pass to the provider SDK.
    """
    if provider_format == "anthropic":
        return await _build_anthropic(
            items,
            include_thinking=include_thinking,
            attachment_store=attachment_store,
            require_attachments=require_attachments,
        )
    if provider_format in ("openai", "openai_compat"):
        return await _build_openai(
            items,
            attachment_store=attachment_store,
            require_attachments=require_attachments,
        )
    raise ValueError(f"Unknown provider_format: {provider_format!r}")


def build_legacy_messages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 timeline items 投影为 UI 兼容的 role/content 消息列表。

    仅包含 user_message、assistant_message、context_summary。
    不含 provider-specific blocks (tool_calls, content block lists)。
    """
    result: list[dict[str, Any]] = []
    for item in items:
        kind = item.get("kind", "")
        if kind == "user_message":
            result.append(
                {
                    "role": "user",
                    "content": item.get("content", ""),
                    "seq": item.get("seq"),
                    "created_at": item.get("created_at"),
                }
            )
        elif kind == "assistant_message":
            result.append(
                {
                    "role": "assistant",
                    "content": item.get("content", ""),
                    "seq": item.get("seq"),
                    "created_at": item.get("created_at"),
                }
            )
        elif kind == "context_summary":
            result.append(
                {
                    "role": "system",
                    "content": item.get("content", ""),
                    "seq": item.get("seq"),
                    "created_at": item.get("created_at"),
                }
            )
        # tool_call, tool_result, thinking, raw_block, system_event, attachment
        # 不进入 legacy messages
    return result


# ---------------------------------------------------------------------------
# Anthropic projection
# ---------------------------------------------------------------------------


async def _build_anthropic(
    items: list[dict[str, Any]],
    *,
    include_thinking: bool,
    attachment_store: Any | None,
    require_attachments: bool,
) -> list[dict[str, Any]]:
    """Build Anthropic-format messages from timeline items.

    Rules:
    - user_message → {"role": "user", "content": str} (or list when attachments follow)
    - attachment items that share the same exchange_id as the preceding user_message
      are merged into that user message's content list
    - assistant_message, tool_call, thinking within the same
      (assistant_turn_id, provider_call_index) group → merged into one assistant message
      whose content is a list of blocks.
    - tool_result → appended as a tool_result block to the next user message
      (or a standalone user message if none follows).
    - context_summary → {"role": "user", "content": str}
    - system_event → skipped
    """
    messages: list[dict[str, Any]] = []

    # Pending tool_result blocks to attach to the next user message.
    _pending_tool_results: list[dict[str, Any]] = []

    # Pending user turn accumulation for attachment merging.
    # When we encounter a user_message we don't emit immediately; we buffer it
    # so that subsequent attachment items (same exchange_id) can be merged in.
    _pending_user_exchange: str | None = None
    _pending_user_content_list: list[dict[str, Any]] | None = None

    # Group consecutive items that share the same (assistant_turn_id, provider_call_index)
    # so we can merge assistant blocks correctly.
    groups = _group_by_call(items)

    async def _flush_pending_user() -> None:
        nonlocal _pending_user_exchange, _pending_user_content_list
        if _pending_user_content_list is None:
            return
        content_list = _pending_user_content_list
        _pending_user_exchange = None
        _pending_user_content_list = None
        _flush_tool_results_into_user_list(messages, _pending_tool_results, content_list)

    for group in groups:
        first = group[0]
        kind = first["kind"]

        # --- attachment --------------------------------------------------------
        if kind == "attachment":
            exchange_id = first.get("exchange_id")
            if (
                exchange_id
                and exchange_id == _pending_user_exchange
                and _pending_user_content_list is not None
            ):
                # Merge into the buffered user message
                payload = first.get("payload") or {}
                att_id = payload.get("attachment_id")
                att_kind = payload.get("kind")
                filename = payload.get("original_filename", "file")

                if attachment_store is None:
                    if require_attachments:
                        raise ValueError(
                            "attachment_store is required for attachment timeline items"
                        )
                    # else: silently skip this attachment
                elif att_kind == "text_file":
                    record = await attachment_store.get(att_id)
                    if record is not None:
                        text = await asyncio.to_thread(attachment_store.read_text_content, record)
                        fenced = f"用户上传了文本文件：{filename}\n```{filename}\n{text}\n```"
                        _pending_user_content_list.append({"type": "text", "text": fenced})
                elif att_kind == "image":
                    record = await attachment_store.get(att_id)
                    if record is not None:
                        blob_path = attachment_store.blob_absolute_path(record)
                        data = await asyncio.to_thread(blob_path.read_bytes)
                        encoded = base64.b64encode(data).decode()
                        _pending_user_content_list.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": record.mime_type,
                                    "data": encoded,
                                },
                            }
                        )
            else:
                # Attachment with no matching pending user context: guard then flush then skip.
                if attachment_store is None and require_attachments:
                    raise ValueError("attachment_store is required for attachment timeline items")
                await _flush_pending_user()
            continue

        # Flush any pending user turn before processing a non-attachment group
        await _flush_pending_user()

        # --- context_summary ---------------------------------------------------
        if kind == "context_summary":
            _flush_tool_results(messages, _pending_tool_results)
            # TODO: role:user projection causes consecutive user messages when followed by
            # a user_message group. Safe for Phase 1 (no compression worker). Fix before
            # enabling compression: merge context_summary into the subsequent user message's
            # content list instead of injecting a standalone role:user turn.
            messages.append({"role": "user", "content": first["content"]})
            continue

        # --- system_event ------------------------------------------------------
        if kind == "system_event":
            continue

        # --- pure user_message group -------------------------------------------
        if all(item["kind"] == "user_message" for item in group):
            # Buffer for potential subsequent attachment merging
            user_content = first["content"]
            _pending_user_exchange = first.get("exchange_id")
            _pending_user_content_list = (
                [{"type": "text", "text": user_content}] if user_content else []
            )
            continue

        # --- tool_result -------------------------------------------------------
        if all(item["kind"] == "tool_result" for item in group):
            for item in group:
                payload = item.get("payload") or {}
                _pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": payload.get("tool_call_id", ""),
                        "content": payload.get("model_content", item.get("content", "")),
                    }
                )
            continue

        # --- assistant-side group (assistant_message, tool_call, thinking) -----
        if any(item["kind"] in ("assistant_message", "tool_call", "thinking") for item in group):
            blocks = _build_anthropic_assistant_blocks(group, include_thinking=include_thinking)

            if blocks:
                # Flush any accumulated tool results before this assistant turn
                _flush_tool_results(messages, _pending_tool_results)
                _pending_tool_results = []

                if len(blocks) == 1 and blocks[0].get("type") == "text":
                    # Simplify single text block to string
                    messages.append({"role": "assistant", "content": blocks[0]["text"]})
                else:
                    messages.append({"role": "assistant", "content": blocks})
            continue

    # Flush any remaining pending user turn
    await _flush_pending_user()

    # Flush any remaining pending tool results as a standalone user message
    _flush_tool_results(messages, _pending_tool_results)

    return messages


def _build_anthropic_assistant_blocks(
    items: list[dict[str, Any]],
    *,
    include_thinking: bool,
) -> list[dict[str, Any]]:
    """Build Anthropic content block list from assistant-side timeline items."""
    blocks: list[dict[str, Any]] = []
    # Sort by block_index within the group so ordering is deterministic
    sorted_items = sorted(items, key=lambda i: i.get("block_index") or 0)

    for item in sorted_items:
        kind = item["kind"]
        payload = item.get("payload") or {}

        if kind == "thinking":
            if include_thinking:
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": item.get("content", ""),
                        "signature": payload.get("signature", ""),
                    }
                )

        elif kind == "tool_call":
            input_data = payload.get("input", {})
            blocks.append(
                {
                    "type": "tool_use",
                    "id": payload.get("tool_call_id", ""),
                    "name": payload.get("tool_name", ""),
                    "input": input_data if isinstance(input_data, dict) else {},
                }
            )

        elif kind == "assistant_message":
            content = item.get("content", "")
            if content:
                blocks.append({"type": "text", "text": content})

    return blocks


def _flush_tool_results(
    messages: list[dict[str, Any]],
    pending: list[dict[str, Any]],
) -> None:
    """If there are pending tool_result blocks, emit a standalone user message."""
    if not pending:
        return
    messages.append({"role": "user", "content": list(pending)})
    pending.clear()


def _flush_tool_results_into_user_list(
    messages: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    content_list: list[dict[str, Any]],
) -> None:
    """Combine pending tool_result blocks with a user content list, then emit.

    If there are pending results, prepend them to the content list.
    Simplifies back to a plain string if the result is a single text block
    with no pending tool results (preserves backward compat).
    """
    if pending:
        combined: list[dict[str, Any]] = list(pending) + content_list
        pending.clear()
        messages.append({"role": "user", "content": combined})
        return

    # No pending tool results
    if len(content_list) == 1 and content_list[0].get("type") == "text":
        # Single text block → simplify to string for backward compat
        messages.append({"role": "user", "content": content_list[0]["text"]})
    elif content_list:
        messages.append({"role": "user", "content": content_list})
    # else: content_list is empty and no pending tool results → nothing to emit


def _flush_tool_results_into_user(
    messages: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    user_content: str,
) -> None:
    """Combine pending tool_result blocks with an incoming user message.

    If there are pending results, the user message content becomes a list
    with the tool_result blocks first, then the user text (if non-empty).
    """
    if not pending:
        messages.append({"role": "user", "content": user_content})
        return

    content_list: list[dict[str, Any]] = list(pending)
    pending.clear()
    if user_content:
        content_list.append({"type": "text", "text": user_content})
    messages.append({"role": "user", "content": content_list})


# ---------------------------------------------------------------------------
# OpenAI projection
# ---------------------------------------------------------------------------


async def _build_openai(
    items: list[dict[str, Any]],
    *,
    attachment_store: Any | None,
    require_attachments: bool,
) -> list[dict[str, Any]]:
    """Build OpenAI-format messages from timeline items.

    Rules:
    - user_message → buffered for potential attachment merging
    - attachment same exchange_id as pending user → merged into that user message
      - text_file: appended as fenced text block to string content
      - image: content converted to list with text + image_url blocks
    - attachment with no matching pending user or no store → skip (or raise)
    - assistant_message → {"role": "assistant", "content": str}
    - tool_call(s) within same provider_call_index → single assistant message
      with tool_calls list
    - tool_result → {"role": "tool", "tool_call_id": ..., "content": ...}
    - context_summary → {"role": "user", "content": str}
    - thinking → skipped (OpenAI format does not support thinking blocks)
    - system_event → skipped
    """
    messages: list[dict[str, Any]] = []
    groups = _group_by_call(items)

    # Pending user turn state for attachment buffering
    _pending_user_exchange: str | None = None
    _pending_user_content: str = ""
    # None = string mode; list = already converted to content-block list mode
    _pending_user_blocks: list[dict[str, Any]] | None = None

    def _flush_pending_user() -> None:
        nonlocal _pending_user_exchange, _pending_user_content, _pending_user_blocks
        if _pending_user_exchange is None:
            return
        if _pending_user_blocks is not None:
            messages.append({"role": "user", "content": _pending_user_blocks})
        else:
            messages.append({"role": "user", "content": _pending_user_content})
        _pending_user_exchange = None
        _pending_user_content = ""
        _pending_user_blocks = None

    for group in groups:
        first = group[0]
        kind = first["kind"]

        if kind == "context_summary":
            _flush_pending_user()
            messages.append({"role": "user", "content": first["content"]})
            continue

        if kind == "system_event":
            _flush_pending_user()
            continue

        if kind == "thinking":
            # OpenAI has no thinking format — skip
            _flush_pending_user()
            continue

        if kind == "attachment":
            exchange_id = first.get("exchange_id")
            if exchange_id and exchange_id == _pending_user_exchange:
                # Merge into buffered user message
                payload = first.get("payload") or {}
                att_id = payload.get("attachment_id")
                att_kind = payload.get("kind")
                filename = payload.get("original_filename", "file")

                if attachment_store is None:
                    if require_attachments:
                        raise ValueError(
                            "attachment_store is required for attachment timeline items"
                        )
                    # else: silently skip this attachment
                elif att_kind == "text_file":
                    record = await attachment_store.get(att_id)
                    if record is not None:
                        text = await asyncio.to_thread(attachment_store.read_text_content, record)
                        fenced = f"用户上传了文本文件：{filename}\n```{filename}\n{text}\n```"
                        if _pending_user_blocks is not None:
                            _pending_user_blocks.append({"type": "text", "text": fenced})
                        else:
                            # Append to string content
                            _pending_user_content = (
                                f"{_pending_user_content}\n\n{fenced}"
                                if _pending_user_content
                                else fenced
                            )
                elif att_kind == "image":
                    record = await attachment_store.get(att_id)
                    if record is not None:
                        blob_path = attachment_store.blob_absolute_path(record)
                        data = await asyncio.to_thread(blob_path.read_bytes)
                        encoded = base64.b64encode(data).decode()
                        # Convert to block list mode if not already
                        if _pending_user_blocks is None:
                            _pending_user_blocks = []
                            if _pending_user_content:
                                _pending_user_blocks.append(
                                    {"type": "text", "text": _pending_user_content}
                                )
                        _pending_user_blocks.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{record.mime_type};base64,{encoded}"},
                            }
                        )
            else:
                # Attachment with no matching pending user context: guard then flush then skip.
                if attachment_store is None and require_attachments:
                    raise ValueError("attachment_store is required for attachment timeline items")
                _flush_pending_user()
            continue

        if all(item["kind"] == "user_message" for item in group):
            # Flush any previous pending user before buffering this one
            _flush_pending_user()
            _pending_user_exchange = first.get("exchange_id")
            _pending_user_content = first.get("content", "")
            _pending_user_blocks = None
            continue

        # All non-user groups flush pending first
        _flush_pending_user()

        if all(item["kind"] == "tool_result" for item in group):
            for item in group:
                payload = item.get("payload") or {}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": payload.get("tool_call_id", ""),
                        "content": payload.get("model_content", item.get("content", "")),
                    }
                )
            continue

        # --- assistant-side group -------------------------------------------
        tool_calls_items = [i for i in group if i["kind"] == "tool_call"]
        tool_result_items = [i for i in group if i["kind"] == "tool_result"]
        text_items = [i for i in group if i["kind"] == "assistant_message"]

        # Emit assistant message(s)
        if tool_calls_items:
            tool_calls = []
            for item in sorted(tool_calls_items, key=lambda i: i.get("block_index") or 0):
                payload = item.get("payload") or {}
                input_data = payload.get("input", {})
                tool_calls.append(
                    {
                        "id": payload.get("tool_call_id", ""),
                        "type": "function",
                        "function": {
                            "name": payload.get("tool_name", ""),
                            "arguments": (
                                json.dumps(input_data)
                                if isinstance(input_data, dict)
                                else str(input_data)
                            ),
                        },
                    }
                )
            # Merge text into content of the same assistant message
            # (OpenAI allows content + tool_calls in a single message)
            text_content = (
                " ".join(i.get("content", "") for i in text_items if i.get("content")).strip()
                or None
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": text_content,
                    "tool_calls": tool_calls,
                }
            )
        elif text_items:
            content = " ".join(i.get("content", "") for i in text_items if i.get("content"))
            messages.append({"role": "assistant", "content": content})

        # Emit tool results that appear in this group
        for item in tool_result_items:
            payload = item.get("payload") or {}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": payload.get("tool_call_id", ""),
                    "content": payload.get("model_content", item.get("content", "")),
                }
            )

    # Flush any remaining pending user turn
    _flush_pending_user()

    return messages


# ---------------------------------------------------------------------------
# Grouping helper
# ---------------------------------------------------------------------------


def _group_by_call(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group timeline items for projection.

    Only assistant-side items (assistant_message, tool_call, thinking) that
    share the same (assistant_turn_id, provider_call_index) are merged into a single
    group.  Everything else is a singleton:
    - user_message: always singleton (becomes a user message)
    - tool_result: always singleton (held as pending in Anthropic, emitted as
      role=tool in OpenAI)
    - context_summary / system_event / attachment: always singleton
    - items missing assistant_turn_id or provider_call_index: singleton

    Within each group items retain their original order (already sorted by
    effective_seq, seq from the DB).
    """
    _ASSISTANT_GROUPABLE = frozenset({"assistant_message", "tool_call", "thinking"})

    groups: list[list[dict[str, Any]]] = []
    current_key: tuple[str | None, int | None] | None = None
    current_group: list[dict[str, Any]] = []

    for item in items:
        kind = item.get("kind", "")

        # Always-singleton kinds flush and emit immediately
        if kind not in _ASSISTANT_GROUPABLE:
            if current_group:
                groups.append(current_group)
                current_group = []
                current_key = None
            groups.append([item])
            continue

        assistant_turn_id = item.get("assistant_turn_id") or item.get("turn_id")
        pci = item.get("provider_call_index")

        # Assistant items without grouping keys → singleton
        if assistant_turn_id is None or pci is None:
            if current_group:
                groups.append(current_group)
                current_group = []
                current_key = None
            groups.append([item])
            continue

        key = (assistant_turn_id, pci)
        if key != current_key:
            if current_group:
                groups.append(current_group)
            current_group = [item]
            current_key = key
        else:
            current_group.append(item)

    if current_group:
        groups.append(current_group)

    return groups

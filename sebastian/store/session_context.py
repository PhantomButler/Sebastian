"""Timeline → LLM provider context message projection.

Converts a flat list of timeline item dicts (as returned by
SessionTimelineStore.get_context_items) into the message format expected by
Anthropic or OpenAI-compatible providers.

Only produces plain ``dict`` output — no provider SDK types involved.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_context_messages(
    items: list[dict[str, Any]],
    provider_format: str,
    *,
    include_thinking: bool = False,
) -> list[dict[str, Any]]:
    """Project timeline items into provider-specific message dicts.

    Args:
        items: Timeline item dicts ordered by (effective_seq, seq).
        provider_format: ``"anthropic"`` or ``"openai"``.
        include_thinking: When True, include thinking blocks in Anthropic output.

    Returns:
        List of message dicts ready to pass to the provider SDK.
    """
    if provider_format == "anthropic":
        return _build_anthropic(items, include_thinking=include_thinking)
    if provider_format in ("openai", "openai_compat"):
        return _build_openai(items)
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
            result.append({
                "role": "user",
                "content": item.get("content", ""),
                "seq": item.get("seq"),
                "created_at": item.get("created_at"),
            })
        elif kind == "assistant_message":
            result.append({
                "role": "assistant",
                "content": item.get("content", ""),
                "seq": item.get("seq"),
                "created_at": item.get("created_at"),
            })
        elif kind == "context_summary":
            result.append({
                "role": "system",
                "content": item.get("content", ""),
                "seq": item.get("seq"),
                "created_at": item.get("created_at"),
            })
        # tool_call, tool_result, thinking, raw_block, system_event 不进入 legacy messages
    return result


# ---------------------------------------------------------------------------
# Anthropic projection
# ---------------------------------------------------------------------------

def _build_anthropic(
    items: list[dict[str, Any]],
    *,
    include_thinking: bool,
) -> list[dict[str, Any]]:
    """Build Anthropic-format messages from timeline items.

    Rules:
    - user_message → {"role": "user", "content": str}
    - assistant_message, tool_call, thinking within the same
      (turn_id, provider_call_index) group → merged into one assistant message
      whose content is a list of blocks.
    - tool_result → appended as a tool_result block to the next user message
      (or a standalone user message if none follows).
    - context_summary → {"role": "user", "content": str}
    - system_event → skipped
    """
    messages: list[dict[str, Any]] = []

    # Pending tool_result blocks to attach to the next user message.
    _pending_tool_results: list[dict[str, Any]] = []

    # Group consecutive items that share the same (turn_id, provider_call_index)
    # so we can merge assistant blocks correctly.
    groups = _group_by_call(items)

    for group in groups:
        first = group[0]
        kind = first["kind"]

        # --- context_summary ---------------------------------------------------
        if kind == "context_summary":
            _flush_tool_results(messages, _pending_tool_results)
            messages.append({"role": "user", "content": first["content"]})
            continue

        # --- system_event ------------------------------------------------------
        if kind == "system_event":
            continue

        # --- pure user_message group -------------------------------------------
        if all(item["kind"] == "user_message" for item in group):
            _flush_tool_results_into_user(messages, _pending_tool_results, first["content"])
            _pending_tool_results = []
            continue

        # --- tool_result -------------------------------------------------------
        if all(item["kind"] == "tool_result" for item in group):
            for item in group:
                payload = item.get("payload") or {}
                _pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": payload.get("tool_call_id", ""),
                    "content": payload.get("model_content", item.get("content", "")),
                })
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
    sorted_items = sorted(items, key=lambda i: (i.get("block_index") or 0))

    for item in sorted_items:
        kind = item["kind"]
        payload = item.get("payload") or {}

        if kind == "thinking":
            if include_thinking:
                blocks.append({
                    "type": "thinking",
                    "thinking": item.get("content", ""),
                    "signature": payload.get("signature", ""),
                })

        elif kind == "tool_call":
            input_data = payload.get("input", {})
            blocks.append({
                "type": "tool_use",
                "id": payload.get("tool_call_id", ""),
                "name": payload.get("tool_name", ""),
                "input": input_data if isinstance(input_data, dict) else {},
            })

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

def _build_openai(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build OpenAI-format messages from timeline items.

    Rules:
    - user_message → {"role": "user", "content": str}
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

    for group in groups:
        first = group[0]
        kind = first["kind"]

        if kind == "context_summary":
            messages.append({"role": "user", "content": first["content"]})
            continue

        if kind == "system_event":
            continue

        if kind == "thinking":
            # OpenAI has no thinking format — skip
            continue

        if all(item["kind"] == "user_message" for item in group):
            messages.append({"role": "user", "content": first["content"]})
            continue

        if all(item["kind"] == "tool_result" for item in group):
            for item in group:
                payload = item.get("payload") or {}
                messages.append({
                    "role": "tool",
                    "tool_call_id": payload.get("tool_call_id", ""),
                    "content": payload.get("model_content", item.get("content", "")),
                })
            continue

        # --- assistant-side group -------------------------------------------
        tool_calls_items = [i for i in group if i["kind"] == "tool_call"]
        tool_result_items = [i for i in group if i["kind"] == "tool_result"]
        text_items = [i for i in group if i["kind"] == "assistant_message"]

        # Emit assistant message(s)
        if tool_calls_items:
            tool_calls = []
            for item in sorted(tool_calls_items, key=lambda i: (i.get("block_index") or 0)):
                payload = item.get("payload") or {}
                input_data = payload.get("input", {})
                tool_calls.append({
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
                })
            # Merge text into content of the same assistant message
            # (OpenAI allows content + tool_calls in a single message)
            text_content = (
                " ".join(i.get("content", "") for i in text_items if i.get("content")).strip()
                or None
            )
            messages.append({
                "role": "assistant",
                "content": text_content,
                "tool_calls": tool_calls,
            })
        elif text_items:
            content = " ".join(i.get("content", "") for i in text_items if i.get("content"))
            messages.append({"role": "assistant", "content": content})

        # Emit tool results that appear in this group
        for item in tool_result_items:
            payload = item.get("payload") or {}
            messages.append({
                "role": "tool",
                "tool_call_id": payload.get("tool_call_id", ""),
                "content": payload.get("model_content", item.get("content", "")),
            })

    return messages


# ---------------------------------------------------------------------------
# Grouping helper
# ---------------------------------------------------------------------------

def _group_by_call(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group timeline items for projection.

    Only assistant-side items (assistant_message, tool_call, thinking) that
    share the same (turn_id, provider_call_index) are merged into a single
    group.  Everything else is a singleton:
    - user_message: always singleton (becomes a user message)
    - tool_result: always singleton (held as pending in Anthropic, emitted as
      role=tool in OpenAI)
    - context_summary / system_event: always singleton
    - items missing turn_id or provider_call_index: singleton

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

        turn_id = item.get("turn_id")
        pci = item.get("provider_call_index")

        # Assistant items without grouping keys → singleton
        if turn_id is None or pci is None:
            if current_group:
                groups.append(current_group)
                current_group = []
                current_key = None
            groups.append([item])
            continue

        key = (turn_id, pci)
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

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CompactionRange:
    source_seq_start: int
    source_seq_end: int
    source_exchange_start: int | None
    source_exchange_end: int | None
    items: list[dict[str, Any]]


def select_compaction_range(
    items: list[dict[str, Any]],
    *,
    retain_recent_exchanges: int = 8,
    min_items: int = 12,
) -> CompactionRange | None:
    candidates = [item for item in items if not item.get("archived")]
    groups = _group_by_exchange(candidates)
    if len(groups) <= retain_recent_exchanges:
        return None
    source_groups = groups[:-retain_recent_exchanges]
    source_items = [it for group in source_groups for it in group]
    if len(source_items) < min_items:
        return None
    if _has_incomplete_tool_chain(source_items):
        return None
    seqs = [int(it["seq"]) for it in source_items]
    exchange_indexes = [
        it.get("exchange_index")
        for it in source_items
        if it.get("exchange_index") is not None
    ]
    return CompactionRange(
        source_seq_start=min(seqs),
        source_seq_end=max(seqs),
        source_exchange_start=min(exchange_indexes) if exchange_indexes else None,
        source_exchange_end=max(exchange_indexes) if exchange_indexes else None,
        items=source_items,
    )


def _group_by_exchange(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group items by exchange_index when present, else start a new group at each user_message."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_key: Any = object()  # sentinel distinct from None and any int
    for it in items:
        exch = it.get("exchange_index")
        if exch is not None:
            if exch != current_key:
                if current:
                    groups.append(current)
                current = []
                current_key = exch
            current.append(it)
        else:
            # Fallback: start a new group on each user_message
            if it.get("kind") == "user_message":
                if current:
                    groups.append(current)
                current = []
                current_key = None
            current.append(it)
    if current:
        groups.append(current)
    return groups


def _has_incomplete_tool_chain(items: list[dict[str, Any]]) -> bool:
    call_ids: set[str] = set()
    result_ids: set[str] = set()
    for it in items:
        payload = it.get("payload") or {}
        tool_id = payload.get("tool_call_id")
        if not tool_id:
            continue
        if it.get("kind") == "tool_call":
            call_ids.add(tool_id)
        elif it.get("kind") == "tool_result":
            result_ids.add(tool_id)
    return bool(call_ids - result_ids)

from __future__ import annotations

from sebastian.context.compaction import select_compaction_range


def item(seq: int, kind: str, exchange_index: int | None = None, tool_id: str | None = None):
    payload = {}
    if tool_id:
        payload["tool_call_id"] = tool_id
    return {
        "seq": seq,
        "kind": kind,
        "exchange_index": exchange_index,
        "exchange_id": f"ex-{exchange_index}" if exchange_index is not None else None,
        "payload": payload,
        "archived": False,
        "content": f"item {seq}",
    }


def test_select_compaction_range_keeps_recent_exchanges() -> None:
    items = []
    seq = 1
    for exchange in range(1, 12):
        items.append(item(seq, "user_message", exchange))
        seq += 1
        items.append(item(seq, "assistant_message", exchange))
        seq += 1

    result = select_compaction_range(items, retain_recent_exchanges=3, min_items=1)

    assert result is not None
    assert result.source_seq_start == 1
    assert result.source_seq_end == 16
    assert result.source_exchange_start == 1
    assert result.source_exchange_end == 8


def test_select_compaction_range_skips_incomplete_tool_chain() -> None:
    items = [
        item(1, "user_message", 1),
        item(2, "tool_call", 1, "tool-1"),
        item(3, "user_message", 2),
        item(4, "assistant_message", 2),
    ]

    assert select_compaction_range(items, retain_recent_exchanges=1, min_items=1) is None

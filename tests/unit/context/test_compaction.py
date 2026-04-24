from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

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


def test_select_compaction_range_fallback_groups_by_user_message() -> None:
    # All items lack exchange_index; grouping falls back to user_message boundaries
    items = []
    seq = 1
    for _ in range(11):
        items.append(item(seq, "user_message"))
        seq += 1
        items.append(item(seq, "assistant_message"))
        seq += 1

    result = select_compaction_range(items, retain_recent_exchanges=3, min_items=1)

    assert result is not None
    assert result.source_seq_start == 1
    assert result.source_seq_end == 16
    assert result.source_exchange_start is None
    assert result.source_exchange_end is None


def test_select_compaction_range_rejects_below_min_items() -> None:
    items = []
    seq = 1
    for ex in range(1, 12):
        items.append(item(seq, "user_message", ex))
        seq += 1
        items.append(item(seq, "assistant_message", ex))
        seq += 1

    # 8 source exchanges × 2 items = 16 items; min_items=20 should reject
    result = select_compaction_range(items, retain_recent_exchanges=3, min_items=20)

    assert result is None


def test_select_compaction_range_filters_archived_and_summary() -> None:
    items = []
    seq = 1
    # one archived item + one context_summary + enough regular exchanges
    items.append({**item(seq, "user_message", 1), "archived": True})
    seq += 1
    items.append(item(seq, "context_summary", 1))
    seq += 1
    for ex in range(2, 13):
        items.append(item(seq, "user_message", ex))
        seq += 1
        items.append(item(seq, "assistant_message", ex))
        seq += 1

    result = select_compaction_range(items, retain_recent_exchanges=3, min_items=1)

    assert result is not None
    # archived and context_summary are excluded from source
    kinds = {it["kind"] for it in result.items}
    assert "context_summary" not in kinds
    assert all(not it.get("archived") for it in result.items)


# ---------------------------------------------------------------------------
# Worker tests
# ---------------------------------------------------------------------------


class FakeSessionStore:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.compact_calls: list[dict[str, Any]] = []

    async def get_context_timeline_items(
        self, session_id: str, agent_type: str
    ) -> list[dict[str, Any]]:
        return self._items

    async def compact_range(
        self,
        session_id: str,
        agent_type: str,
        *,
        source_seq_start: int,
        source_seq_end: int,
        summary_content: str,
        summary_payload: dict[str, Any],
    ) -> Any:
        self.compact_calls.append({
            "source_seq_start": source_seq_start,
            "source_seq_end": source_seq_end,
            "summary_content": summary_content,
            "summary_payload": summary_payload,
        })
        from sebastian.store.session_timeline import CompactRangeResult
        return CompactRangeResult(
            status="compacted",
            summary_item={"id": "sum-1", "seq": 99, "effective_seq": source_seq_start},
            archived_item_count=(source_seq_end - source_seq_start + 1),
        )


class FakeLLMProvider:
    """Fake provider that yields a single TextDelta then ProviderCallEnd."""

    def __init__(self, text: str = "mock summary") -> None:
        self._text = text
        self.model_id = "fake-model-1"

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        from sebastian.core.stream_events import ProviderCallEnd, TextDelta

        if self._text:
            yield TextDelta(block_id="b0", delta=self._text)
        yield ProviderCallEnd(stop_reason="end_turn")


class _ResolvedProvider:
    """Minimal stand-in for ResolvedProvider."""

    def __init__(self, provider: FakeLLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model
        self.thinking_effort = None
        self.capability = None


class FakeLLMRegistry:
    def __init__(self, provider: FakeLLMProvider) -> None:
        self._provider = provider

    async def get_provider(self, agent_type: str | None = None) -> _ResolvedProvider:
        return _ResolvedProvider(self._provider, self._provider.model_id)


@pytest.mark.asyncio
async def test_worker_skips_when_range_too_small() -> None:
    from sebastian.context.compaction import SessionContextCompactionWorker

    store = FakeSessionStore(items=[])
    registry = FakeLLMRegistry(FakeLLMProvider())
    worker = SessionContextCompactionWorker(session_store=store, llm_registry=registry)

    result = await worker.compact_session("s1", "sebastian", reason="manual")

    assert result.status == "skipped"
    assert result.reason == "range_too_small"


@pytest.mark.asyncio
async def test_worker_compacts_and_returns_metadata() -> None:
    from sebastian.context.compaction import SessionContextCompactionWorker

    items = []
    seq = 1
    # 16 exchanges: retain_recent_exchanges=8 → 8 source groups × 2 items = 16 ≥ min_items=12
    for ex in range(1, 17):
        items.append({
            "seq": seq, "kind": "user_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": f"u{ex}", "role": "user",
        })
        seq += 1
        items.append({
            "seq": seq, "kind": "assistant_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": f"a{ex}" * 200, "role": "assistant",
        })
        seq += 1

    store = FakeSessionStore(items=items)
    registry = FakeLLMRegistry(FakeLLMProvider("generated summary"))
    worker = SessionContextCompactionWorker(session_store=store, llm_registry=registry)

    result = await worker.compact_session("s1", "sebastian", reason="manual")

    assert result.status == "compacted"
    assert result.source_seq_start == 1
    assert result.source_seq_end is not None
    assert result.archived_item_count > 0
    assert result.source_token_estimate is not None and result.source_token_estimate > 0
    assert result.summary_token_estimate is not None and result.summary_token_estimate > 0

    assert len(store.compact_calls) == 1
    call = store.compact_calls[0]
    payload = call["summary_payload"]
    for key in [
        "summary_version", "source_seq_start", "source_seq_end",
        "source_exchange_start", "source_exchange_end",
        "source_token_estimate", "summary_token_estimate",
        "retained_recent_exchanges", "model", "reason",
    ]:
        assert key in payload, f"missing key: {key}"
    assert payload["summary_version"] == "context_compaction_v1"
    assert payload["reason"] == "manual"


@pytest.mark.asyncio
async def test_worker_dry_run_skips_llm_and_returns_dry_run_status() -> None:
    """dry_run=True must return status='dry_run' without calling the LLM or compact_range."""
    from sebastian.context.compaction import SessionContextCompactionWorker

    items = []
    seq = 1
    for ex in range(1, 17):
        items.append({
            "seq": seq, "kind": "user_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": f"u{ex}", "role": "user",
        })
        seq += 1
        items.append({
            "seq": seq, "kind": "assistant_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": f"a{ex}" * 200, "role": "assistant",
        })
        seq += 1

    store = FakeSessionStore(items=items)
    fake_provider = FakeLLMProvider("should not be called")
    registry = FakeLLMRegistry(fake_provider)
    worker = SessionContextCompactionWorker(session_store=store, llm_registry=registry)

    # Track whether the provider was called by monkey-patching stream
    provider_called = False
    original_stream = fake_provider.stream

    async def _guarded_stream(**kwargs: Any) -> Any:
        nonlocal provider_called
        provider_called = True
        async for ev in original_stream(**kwargs):
            yield ev

    fake_provider.stream = _guarded_stream  # type: ignore[method-assign]

    result = await worker.compact_session("s1", "sebastian", reason="manual", dry_run=True)

    assert result.status == "dry_run"
    assert result.summary_item_id is None
    assert result.source_seq_start is not None
    assert result.source_seq_end is not None
    # No LLM call and no compact_range call
    assert not provider_called
    assert len(store.compact_calls) == 0


@pytest.mark.asyncio
async def test_worker_skips_when_llm_returns_empty_summary() -> None:
    from sebastian.context.compaction import SessionContextCompactionWorker

    items = []
    seq = 1
    for ex in range(1, 17):
        items.append({
            "seq": seq, "kind": "user_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": f"u{ex}", "role": "user",
        })
        seq += 1
        items.append({
            "seq": seq, "kind": "assistant_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": f"a{ex}" * 200, "role": "assistant",
        })
        seq += 1

    store = FakeSessionStore(items=items)
    # FakeLLMProvider with empty text yields no TextDelta → summary_text stays ""
    registry = FakeLLMRegistry(FakeLLMProvider(""))
    worker = SessionContextCompactionWorker(session_store=store, llm_registry=registry)

    result = await worker.compact_session("s1", "sebastian", reason="manual")

    assert result.status == "skipped"
    assert result.reason == "empty_summary"
    # compact_range should NOT have been called
    assert len(store.compact_calls) == 0


@pytest.mark.asyncio
async def test_worker_dry_run_returns_dry_run_even_below_min_source_tokens() -> None:
    """dry_run=True must return status='dry_run' even when token count is below
    min_source_tokens — the dry_run short-circuit fires before the token gate."""
    from unittest.mock import AsyncMock

    from sebastian.context.compaction import SessionContextCompactionWorker

    # Build just enough exchanges for a valid compaction range (>8 + retain)
    items = []
    seq = 1
    for ex in range(1, 17):
        items.append({
            "seq": seq, "kind": "user_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": "hi",  # tiny content → tiny token estimate
            "role": "user",
        })
        seq += 1
        items.append({
            "seq": seq, "kind": "assistant_message", "exchange_index": ex,
            "exchange_id": f"ex-{ex}", "archived": False,
            "payload": {}, "content": "ok",  # tiny → ensures token estimate < 1_000_000
            "role": "assistant",
        })
        seq += 1

    store = FakeSessionStore(items=items)
    # Mock compact_range so we can assert it was never called
    store.compact_range = AsyncMock()  # type: ignore[method-assign]

    fake_provider = FakeLLMProvider("should not be called")
    fake_provider.stream = AsyncMock()  # type: ignore[method-assign]
    registry = FakeLLMRegistry(fake_provider)

    # min_source_tokens set impossibly high so normal compaction would be skipped
    worker = SessionContextCompactionWorker(
        session_store=store,
        llm_registry=registry,
        min_source_tokens=1_000_000,
    )

    result = await worker.compact_session("s1", "sebastian", reason="auto_token", dry_run=True)

    # dry_run must win — status is "dry_run", not "skipped"
    assert result.status == "dry_run"
    assert result.source_seq_start is not None
    assert result.source_seq_end is not None
    # No LLM call, no store.compact_range call
    fake_provider.stream.assert_not_called()
    store.compact_range.assert_not_called()


# ---------------------------------------------------------------------------
# TurnEndCompactionScheduler tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeDecision:
    should_compact: bool
    reason: str = "token_limit"


class _FakeMeter:
    def __init__(self, decision: _FakeDecision) -> None:
        self._decision = decision

    def should_compact(self, *, usage: Any, estimate: int) -> _FakeDecision:
        return self._decision


class _FakeEstimator:
    def estimate_messages(self, messages: Any, *, system_prompt: str = "") -> int:
        return 100


@pytest.mark.asyncio
async def test_scheduler_skips_when_should_compact_false() -> None:
    """Scheduler must not call worker when meter returns should_compact=False."""
    from sebastian.context.compaction import TurnEndCompactionScheduler

    worker_mock = AsyncMock()
    scheduler = TurnEndCompactionScheduler(
        worker=worker_mock,
        token_meter=_FakeMeter(_FakeDecision(should_compact=False)),
        estimator=_FakeEstimator(),
    )

    await scheduler.maybe_schedule_after_turn(
        session_id="s1",
        agent_type="sebastian",
        usage=None,
        messages=[],
        system_prompt="",
    )
    # Give event loop a chance to run any background tasks
    await asyncio.sleep(0)

    worker_mock.compact_session.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_dispatches_when_should_compact_true() -> None:
    """Scheduler must call worker.compact_session with correct kwargs when meter fires."""
    from sebastian.context.compaction import CompactionResult, TurnEndCompactionScheduler

    worker_mock = AsyncMock()
    worker_mock.compact_session.return_value = CompactionResult(status="compacted")

    scheduler = TurnEndCompactionScheduler(
        worker=worker_mock,
        token_meter=_FakeMeter(_FakeDecision(should_compact=True, reason="token_limit")),
        estimator=_FakeEstimator(),
    )

    await scheduler.maybe_schedule_after_turn(
        session_id="s1",
        agent_type="sebastian",
        usage=None,
        messages=[],
        system_prompt="",
    )
    # Drain the background task spawned by asyncio.create_task
    await asyncio.sleep(0)

    worker_mock.compact_session.assert_called_once_with(
        "s1",
        "sebastian",
        reason="auto_token_limit",
    )


@pytest.mark.asyncio
async def test_scheduler_swallows_worker_exception(caplog: Any) -> None:
    """Worker raising an exception must not propagate out of the scheduler."""
    from sebastian.context.compaction import TurnEndCompactionScheduler

    worker_mock = AsyncMock()
    worker_mock.compact_session.side_effect = RuntimeError("boom")

    scheduler = TurnEndCompactionScheduler(
        worker=worker_mock,
        token_meter=_FakeMeter(_FakeDecision(should_compact=True, reason="token_limit")),
        estimator=_FakeEstimator(),
    )

    # Call must not raise even though the worker raises
    with caplog.at_level(logging.WARNING, logger="sebastian.context.compaction"):
        await scheduler.maybe_schedule_after_turn(
            session_id="s1",
            agent_type="sebastian",
            usage=None,
            messages=[],
            system_prompt="",
        )
        # Drain the background task so the exception is handled
        await asyncio.sleep(0)

    # Worker was called (it raised), no exception propagated
    worker_mock.compact_session.assert_called_once()
    # Warning should have been logged
    assert any("context compaction failed" in r.message for r in caplog.records)

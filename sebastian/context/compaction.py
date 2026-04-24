from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sebastian.context.usage import TokenUsage

logger = logging.getLogger(__name__)


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
    candidates = [
        item for item in items
        if not item.get("archived") and item.get("kind") != "context_summary"
    ]
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
    return bool(call_ids ^ result_ids)


# ---------------------------------------------------------------------------
# CompactionResult
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CompactionResult:
    status: str  # "compacted" | "skipped"
    reason: str | None = None
    summary_item_id: str | None = None
    source_seq_start: int | None = None
    source_seq_end: int | None = None
    archived_item_count: int = 0
    source_token_estimate: int | None = None
    summary_token_estimate: int | None = None


# ---------------------------------------------------------------------------
# Worker constants
# ---------------------------------------------------------------------------

_MAX_SUMMARY_TOKENS = 8192
_MIN_SUMMARY_TOKENS = 2048
_SUMMARY_BUDGET_RATIO = 0.20
_DEFAULT_RETAIN_RECENT_EXCHANGES = 8
_DEFAULT_MIN_SOURCE_TOKENS = 8000


# ---------------------------------------------------------------------------
# SessionContextCompactionWorker
# ---------------------------------------------------------------------------


class SessionContextCompactionWorker:
    """Orchestrate a single context-compaction pass for one session.

    Dependencies are injected so the worker is easy to unit-test without a
    real database or LLM provider.

    LLM resolution:
        ``llm_registry.get_provider("context_compactor")`` is called first.
        The registry already handles fallback to the global default when no
        explicit binding exists for the given agent_type string, so there is
        no need for a second fallback here — the registry raises RuntimeError
        if no provider is configured at all.
    """

    def __init__(
        self,
        *,
        session_store: Any,
        llm_registry: Any,
        retain_recent_exchanges: int = _DEFAULT_RETAIN_RECENT_EXCHANGES,
        min_source_tokens: int = _DEFAULT_MIN_SOURCE_TOKENS,
    ) -> None:
        self._session_store = session_store
        self._llm_registry = llm_registry
        self._retain_recent_exchanges = retain_recent_exchanges
        self._min_source_tokens = min_source_tokens

    async def compact_session(
        self,
        session_id: str,
        agent_type: str,
        *,
        reason: str,
    ) -> CompactionResult:
        from sebastian.context.estimator import TokenEstimator
        from sebastian.context.prompts import CONTEXT_COMPACTION_SYSTEM_PROMPT
        from sebastian.core.stream_events import TextDelta

        estimator = TokenEstimator()

        # 1. Fetch timeline items
        items: list[dict[str, Any]] = await self._session_store.get_context_timeline_items(
            session_id, agent_type
        )

        # 2. Estimate source tokens (full timeline, not just compaction range)
        source_token_estimate = estimator.estimate_messages(items)

        # 3. Select compaction range
        compaction_range = select_compaction_range(
            items,
            retain_recent_exchanges=self._retain_recent_exchanges,
        )

        # 4. No valid range → skip
        if compaction_range is None:
            return CompactionResult(status="skipped", reason="range_too_small")

        # 5. Enforce min_source_tokens gate for non-manual triggers
        if reason != "manual" and source_token_estimate < self._min_source_tokens:
            return CompactionResult(status="skipped", reason="range_too_small")

        # 6. Build compaction input text from source items
        lines: list[str] = []
        for it in compaction_range.items:
            role = it.get("role") or it.get("kind", "unknown")
            content = it.get("content") or ""
            lines.append(f"**{role}**: {content}")
        compaction_input = "\n\n".join(lines)

        # 7. Resolve LLM provider
        # get_provider("context_compactor") uses agent_type-based binding lookup
        # and already falls back to the global default provider if no explicit
        # binding exists for "context_compactor".
        resolved = await self._llm_registry.get_provider("context_compactor")
        max_tokens = min(
            _MAX_SUMMARY_TOKENS,
            max(_MIN_SUMMARY_TOKENS, int(source_token_estimate * _SUMMARY_BUDGET_RATIO)),
        )

        # 8. Call LLM (accumulate streaming text deltas)
        summary_text = ""
        async for event in resolved.provider.stream(
            system=CONTEXT_COMPACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": compaction_input}],
            tools=[],
            model=resolved.model,
            max_tokens=max_tokens,
        ):
            if isinstance(event, TextDelta):
                summary_text += event.delta

        # 9. Guard: empty summary means LLM produced nothing useful
        if not summary_text.strip():
            return CompactionResult(status="skipped", reason="empty_summary")

        # 10. Estimate summary tokens
        summary_token_estimate = estimator.estimate_text(summary_text)

        # 11. Build payload
        payload: dict[str, Any] = {
            "summary_version": "context_compaction_v1",
            "source_seq_start": compaction_range.source_seq_start,
            "source_seq_end": compaction_range.source_seq_end,
            "source_exchange_start": compaction_range.source_exchange_start,
            "source_exchange_end": compaction_range.source_exchange_end,
            "source_token_estimate": source_token_estimate,
            "summary_token_estimate": summary_token_estimate,
            "retained_recent_exchanges": self._retain_recent_exchanges,
            "model": resolved.model,
            "reason": reason,
        }

        # 12. Persist via store
        result = await self._session_store.compact_range(
            session_id,
            agent_type,
            source_seq_start=compaction_range.source_seq_start,
            source_seq_end=compaction_range.source_seq_end,
            summary_content=summary_text,
            summary_payload=payload,
        )

        # 13. Handle already-compacted race
        if result.status == "already_compacted":
            return CompactionResult(status="skipped", reason="already_compacted")

        # 14. Return compaction metadata
        summary_item_id: str | None = None
        if result.summary_item is not None:
            summary_item_id = str(result.summary_item.get("id", ""))

        return CompactionResult(
            status="compacted",
            summary_item_id=summary_item_id,
            source_seq_start=compaction_range.source_seq_start,
            source_seq_end=compaction_range.source_seq_end,
            archived_item_count=result.archived_item_count,
            source_token_estimate=source_token_estimate,
            summary_token_estimate=summary_token_estimate,
        )


# ---------------------------------------------------------------------------
# CompactionScheduler protocol + TurnEndCompactionScheduler
# ---------------------------------------------------------------------------


class CompactionScheduler(Protocol):
    """Protocol consumed by BaseAgent to schedule post-turn compaction."""

    async def maybe_schedule_after_turn(
        self,
        *,
        session_id: str,
        agent_type: str,
        usage: TokenUsage | None,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> None: ...


class TurnEndCompactionScheduler:
    """Decides whether compaction is needed and fires it as a background task.

    The decision uses the last ProviderCallEnd usage (authoritative token count
    from the provider) when available, falling back to a local estimate derived
    from the message list.  If compaction is triggered, it is fired with
    ``asyncio.create_task`` so it never blocks the response stream.
    """

    def __init__(
        self,
        *,
        worker: SessionContextCompactionWorker,
        token_meter: Any,
        estimator: Any,
    ) -> None:
        self._worker = worker
        self._token_meter = token_meter
        self._estimator = estimator

    async def maybe_schedule_after_turn(
        self,
        *,
        session_id: str,
        agent_type: str,
        usage: TokenUsage | None,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> None:
        estimate = self._estimator.estimate_messages(messages, system_prompt=system_prompt)
        decision = self._token_meter.should_compact(usage=usage, estimate=estimate)
        if not decision.should_compact:
            return

        async def _run() -> None:
            try:
                await self._worker.compact_session(
                    session_id,
                    agent_type,
                    reason=f"auto_{decision.reason}",
                )
            except Exception as exc:
                logger.warning(
                    "context compaction failed session=%s agent=%s: %s",
                    session_id,
                    agent_type,
                    exc,
                    exc_info=True,
                )

        asyncio.create_task(_run())

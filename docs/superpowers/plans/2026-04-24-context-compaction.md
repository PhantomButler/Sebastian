# 上下文自动压缩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sebastian 增加短期 session 上下文自动/手动压缩能力，优先使用 provider token usage，保留完整 audit timeline，并用 `context_summary` 缩短 LLM 当前上下文。

**Architecture:** 新增 `sebastian/context/` 管理 usage、估算、阈值、范围选择和压缩 worker；`llm/` 只负责 usage 归一化，`core/` 只传递 usage 和调度压缩，`store/` 只提供原子 timeline 更新。新增 `exchange_id/exchange_index` 表示一次用户输入及其触发的完整交互，压缩范围按完整 exchange 切分。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy async、SQLite、pytest/pytest-asyncio、Kotlin Jetpack Compose。

---

## 参考文档

- Spec：`docs/superpowers/specs/2026-04-24-context-compaction-design.md`
- 架构索引：`docs/architecture/spec/INDEX.md`
- Store README：`sebastian/store/README.md`
- Core README：`sebastian/core/README.md`
- LLM README：`sebastian/llm/README.md`
- Gateway README：`sebastian/gateway/README.md`
- Android README：`ui/mobile-android/README.md`

## 文件结构

新增：

- `sebastian/context/__init__.py`：context 包入口。
- `sebastian/context/usage.py`：`TokenUsage` dataclass 与 usage helper。
- `sebastian/context/estimator.py`：本地 token 估算器。
- `sebastian/context/token_meter.py`：context window 与阈值判断。
- `sebastian/context/prompts.py`：压缩摘要 prompt。
- `sebastian/context/compaction.py`：范围选择、摘要生成、worker 编排。
- `tests/unit/context/test_usage.py`
- `tests/unit/context/test_estimator.py`
- `tests/unit/context/test_token_meter.py`
- `tests/unit/context/test_compaction.py`
- `tests/integration/gateway/test_context_compaction.py`

修改：

- `sebastian/core/stream_events.py`：`ProviderCallEnd.usage`。
- `sebastian/core/agent_loop.py`：透传 provider usage。
- `sebastian/core/base_agent.py`：收集 usage、分配 exchange、调度 compaction。
- `sebastian/llm/anthropic.py`：解析 Anthropic usage。
- `sebastian/llm/openai_compat.py`：开启 `stream_options.include_usage` 并解析 usage chunk。
- `sebastian/llm/README.md`：记录 usage 归一化约定。
- `sebastian/store/models.py`：`sessions.next_exchange_index`、`session_items.exchange_id/exchange_index`。
- `sebastian/store/database.py`：幂等 schema migration。
- `sebastian/store/session_records.py`：session record 字段映射。
- `sebastian/store/session_timeline.py`：exchange 字段写入、`compact_range()`。
- `sebastian/store/session_store.py`：exchange 分配与 compaction facade。
- `sebastian/store/README.md`：更新 timeline/exchange/compaction 导航。
- `sebastian/gateway/app.py`：初始化 context compaction worker。
- `sebastian/gateway/state.py`：新增 worker/runtime 单例。
- `sebastian/gateway/routes/sessions.py`：手动 compact 与 status endpoints。
- `sebastian/gateway/README.md`：新增 API 导航。
- `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt`：增加 exchange 字段。
- `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineItemDtoTest.kt`：DTO 解析测试。
- `docs/architecture/spec/store/session-storage.md`：同步 exchange 与 compaction 状态。
- `docs/superpowers/specs/2026-04-24-context-compaction-design.md`：实现中如发现细节调整，同步修订。

---

### Task 1: Provider Usage Plumbing

**Files:**
- Create: `sebastian/context/__init__.py`
- Create: `sebastian/context/usage.py`
- Modify: `sebastian/core/stream_events.py`
- Modify: `sebastian/core/agent_loop.py`
- Modify: `sebastian/llm/anthropic.py`
- Modify: `sebastian/llm/openai_compat.py`
- Modify: `sebastian/llm/README.md`
- Test: `tests/unit/context/test_usage.py`
- Test: existing `tests/unit/llm/` tests if present

- [ ] **Step 1: 写 `TokenUsage` 归一化测试**

Create `tests/unit/context/test_usage.py`:

```python
from sebastian.context.usage import TokenUsage


def test_token_usage_effective_input_includes_cache_tokens() -> None:
    usage = TokenUsage(
        input_tokens=10,
        cache_creation_input_tokens=20,
        cache_read_input_tokens=30,
        output_tokens=5,
    )

    assert usage.effective_input_tokens == 60
    assert usage.effective_total_tokens == 65


def test_token_usage_missing_values_are_zero_for_effective_counts() -> None:
    usage = TokenUsage(output_tokens=7)

    assert usage.effective_input_tokens is None
    assert usage.effective_total_tokens is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/context/test_usage.py -q`

Expected: FAIL because `sebastian.context.usage` does not exist.

- [ ] **Step 3: 实现 `TokenUsage`**

Create `sebastian/context/__init__.py` empty.

Create `sebastian/context/usage.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    raw: dict[str, Any] | None = None

    @property
    def effective_input_tokens(self) -> int | None:
        parts = [
            self.input_tokens,
            self.cache_creation_input_tokens,
            self.cache_read_input_tokens,
        ]
        if all(part is None for part in parts):
            return None
        return sum(part or 0 for part in parts)

    @property
    def effective_total_tokens(self) -> int | None:
        if self.total_tokens is not None:
            return self.total_tokens
        if self.effective_input_tokens is None or self.output_tokens is None:
            return None
        return self.effective_input_tokens + self.output_tokens
```

- [ ] **Step 4: 扩展 stream event**

Modify `sebastian/core/stream_events.py`:

```python
from sebastian.context.usage import TokenUsage


@dataclass
class ProviderCallEnd:
    stop_reason: str
    usage: TokenUsage | None = None
```

- [ ] **Step 5: AgentLoop 透传 ProviderCallEnd**

Modify `sebastian/core/agent_loop.py`:

```python
provider_call_usage: TokenUsage | None = None

...
if isinstance(event, ProviderCallEnd):
    stop_reason = event.stop_reason
    provider_call_usage = event.usage
    yield event
    continue
```

Ensure existing behavior still consumes `stop_reason`.

- [ ] **Step 6: Anthropic provider 映射 usage**

Modify `sebastian/llm/anthropic.py` after `final = await stream.get_final_message()`:

```python
usage = getattr(final, "usage", None)
token_usage = None
if usage is not None:
    token_usage = TokenUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None),
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None),
        raw=usage.model_dump() if hasattr(usage, "model_dump") else None,
    )
yield ProviderCallEnd(stop_reason=final.stop_reason or "end_turn", usage=token_usage)
```

- [ ] **Step 7: OpenAI-compatible provider 开启 usage chunk**

Modify `sebastian/llm/openai_compat.py` request kwargs:

```python
"stream_options": {"include_usage": True},
```

In the streaming loop, before `if not chunk.choices`, capture `chunk.usage`:

```python
last_usage: TokenUsage | None = None
raw_usage = getattr(chunk, "usage", None)
if raw_usage is not None:
    last_usage = TokenUsage(
        input_tokens=getattr(raw_usage, "prompt_tokens", None),
        output_tokens=getattr(raw_usage, "completion_tokens", None),
        total_tokens=getattr(raw_usage, "total_tokens", None),
        reasoning_tokens=(
            getattr(getattr(raw_usage, "completion_tokens_details", None), "reasoning_tokens", None)
        ),
        raw=raw_usage.model_dump() if hasattr(raw_usage, "model_dump") else None,
    )
if not chunk.choices:
    continue
```

At end:

```python
yield ProviderCallEnd(stop_reason=stop_reason, usage=last_usage)
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
pytest tests/unit/context/test_usage.py -q
pytest tests/unit/core/test_base_agent_provider.py -q
pytest tests/unit/store/test_session_context.py -q
```

Expected: PASS.

- [ ] **Step 9: 更新 LLM README**

Add a short section to `sebastian/llm/README.md` explaining:

- Providers should emit `ProviderCallEnd(usage=TokenUsage(...))` when available.
- OpenAI-compatible adapters should request `stream_options.include_usage=true`.
- Missing usage is allowed and handled by `TokenEstimator`.

- [ ] **Step 10: Commit**

```bash
git add sebastian/context/__init__.py sebastian/context/usage.py sebastian/core/stream_events.py sebastian/core/agent_loop.py sebastian/llm/anthropic.py sebastian/llm/openai_compat.py sebastian/llm/README.md tests/unit/context/test_usage.py
git commit -m "feat(context): 归一化 provider token usage"
```

---

### Task 2: Exchange Schema And Write Path

**Files:**
- Modify: `sebastian/store/models.py`
- Modify: `sebastian/store/database.py`
- Modify: `sebastian/store/session_records.py`
- Modify: `sebastian/store/session_timeline.py`
- Modify: `sebastian/store/session_store.py`
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/store/README.md`
- Test: `tests/unit/store/test_session_timeline.py`
- Test: `tests/unit/core/test_base_agent_provider.py`

- [ ] **Step 1: 写 exchange 字段持久化测试**

Append to `tests/unit/store/test_session_timeline.py`:

```python
async def test_append_message_persists_exchange_fields(store, session_in_db) -> None:
    await store.append_message(
        session_in_db.id,
        "user",
        "hello",
        "sebastian",
        exchange_id="ex-1",
        exchange_index=1,
    )

    items = await store.get_timeline_items(session_in_db.id, "sebastian")

    assert items[0]["exchange_id"] == "ex-1"
    assert items[0]["exchange_index"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/store/test_session_timeline.py::test_append_message_persists_exchange_fields -q`

Expected: FAIL because `append_message` does not accept exchange fields.

- [ ] **Step 3: Add ORM columns**

Modify `sebastian/store/models.py`:

```python
class SessionRecord(Base):
    ...
    next_exchange_index: Mapped[int] = mapped_column(Integer, default=1)


class SessionItemRecord(Base):
    ...
    exchange_id: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Add index:

```python
Index("ix_session_items_exchange", "agent_type", "session_id", "exchange_index", "seq")
```

- [ ] **Step 4: Add idempotent migrations**

Modify `sebastian/store/database.py`:

```sql
ALTER TABLE sessions ADD COLUMN next_exchange_index INTEGER DEFAULT 1
ALTER TABLE session_items ADD COLUMN exchange_id VARCHAR
ALTER TABLE session_items ADD COLUMN exchange_index INTEGER
CREATE INDEX IF NOT EXISTS ix_session_items_exchange
  ON session_items(agent_type, session_id, exchange_index, seq)
```

Follow the existing `_apply_idempotent_migrations` pattern.

- [ ] **Step 5: Update SessionRecord mapping**

Modify `sebastian/store/session_records.py` to read/write `next_exchange_index`.

- [ ] **Step 6: Update timeline item input/output**

Modify `sebastian/store/session_timeline.py`:

- add `exchange_id` and `exchange_index` to `TimelineItemInput`
- include them in `_record_to_dict`
- persist them in `SessionItemRecord(...)`
- `_message_to_items()` accepts exchange values or lets caller add them

- [ ] **Step 7: Update SessionStore facade**

Modify `sebastian/store/session_store.py`:

```python
async def allocate_exchange(self, session_id: str, agent_type: str) -> tuple[str, int]:
    ...
```

Implementation:

- generate `exchange_id = str(ULID())`
- in one transaction, increment `sessions.next_exchange_index`
- return old value as `exchange_index`

Also extend:

```python
append_message(..., exchange_id: str | None = None, exchange_index: int | None = None)
append_timeline_items(... items include exchange fields)
```

- [ ] **Step 8: Propagate exchange in BaseAgent**

Modify `sebastian/core/base_agent.py`:

- allocate exchange before appending user message
- pass `exchange_id/exchange_index` into user append
- pass exchange into `_stream_inner(...)`
- include exchange fields in all assistant blocks and cancel partial flushes

- [ ] **Step 9: Update tests for BaseAgent**

Extend `tests/unit/core/test_base_agent_provider.py` assertions:

```python
assert all(block["exchange_id"] is not None for block in blocks)
assert {block["exchange_index"] for block in blocks} == {1}
```

Adapt test stubs to provide `allocate_exchange`.

- [ ] **Step 10: Run focused tests**

Run:

```bash
pytest tests/unit/store/test_session_timeline.py -q
pytest tests/unit/core/test_base_agent_provider.py -q
pytest tests/unit/store/test_session_store.py -q
```

Expected: PASS.

- [ ] **Step 11: Update store README**

Document:

- `exchange_id/exchange_index`
- `next_exchange_index`
- compression range should use exchange, not `assistant_turn_id`

- [ ] **Step 12: Commit**

```bash
git add sebastian/store/models.py sebastian/store/database.py sebastian/store/session_records.py sebastian/store/session_timeline.py sebastian/store/session_store.py sebastian/core/base_agent.py sebastian/store/README.md tests/unit/store/test_session_timeline.py tests/unit/core/test_base_agent_provider.py tests/unit/store/test_session_store.py
git commit -m "feat(store): 增加 session exchange 边界字段"
```

---

### Task 3: Token Estimator And Meter

**Files:**
- Create: `sebastian/context/estimator.py`
- Create: `sebastian/context/token_meter.py`
- Test: `tests/unit/context/test_estimator.py`
- Test: `tests/unit/context/test_token_meter.py`

- [ ] **Step 1: Write estimator tests**

Create `tests/unit/context/test_estimator.py`:

```python
from sebastian.context.estimator import TokenEstimator


def test_estimator_counts_chinese_conservatively() -> None:
    estimator = TokenEstimator()

    assert estimator.estimate_text("你好世界，这是一个测试") >= 6


def test_estimator_counts_message_structure_overhead() -> None:
    estimator = TokenEstimator()
    tokens = estimator.estimate_messages(
        [{"role": "user", "content": "hello"}],
        system_prompt="system",
    )

    assert tokens > estimator.estimate_text("hellosystem")
```

- [ ] **Step 2: Write token meter tests**

Create `tests/unit/context/test_token_meter.py`:

```python
from sebastian.context.token_meter import ContextTokenMeter
from sebastian.context.usage import TokenUsage


def test_meter_uses_reported_usage_threshold() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=TokenUsage(input_tokens=70_000), estimate=None)

    assert decision.should_compact is True
    assert decision.reason == "usage_threshold"


def test_meter_uses_lower_estimate_threshold() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=None, estimate=65_000)

    assert decision.should_compact is True
    assert decision.reason == "estimate_threshold"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/unit/context/test_estimator.py tests/unit/context/test_token_meter.py -q
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement TokenEstimator**

Create `sebastian/context/estimator.py`:

```python
from __future__ import annotations

import json
import math
from typing import Any


class TokenEstimator:
    """Conservative local token estimator used when provider usage is unavailable."""

    def estimate_text(self, text: str) -> int:
        if not text:
            return 0
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        return math.ceil(cjk / 1.5) + math.ceil(other / 4)

    def estimate_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        system_prompt: str = "",
    ) -> int:
        total = self.estimate_text(system_prompt) + 8
        for message in messages:
            total += 6
            total += self.estimate_text(json.dumps(message, ensure_ascii=False, default=str))
        return total
```

- [ ] **Step 5: Implement ContextTokenMeter**

Create `sebastian/context/token_meter.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from sebastian.context.usage import TokenUsage


@dataclass(slots=True)
class CompactionDecision:
    should_compact: bool
    reason: str
    token_count: int | None
    threshold: int


class ContextTokenMeter:
    def __init__(
        self,
        *,
        context_window: int,
        usage_ratio: float = 0.70,
        estimate_ratio: float = 0.65,
    ) -> None:
        self._context_window = context_window
        self._usage_threshold = int(context_window * usage_ratio)
        self._estimate_threshold = int(context_window * estimate_ratio)

    def should_compact(
        self,
        *,
        usage: TokenUsage | None,
        estimate: int | None,
    ) -> CompactionDecision:
        usage_tokens = usage.effective_input_tokens if usage is not None else None
        if usage_tokens is not None:
            return CompactionDecision(
                should_compact=usage_tokens >= self._usage_threshold,
                reason="usage_threshold",
                token_count=usage_tokens,
                threshold=self._usage_threshold,
            )
        return CompactionDecision(
            should_compact=estimate is not None and estimate >= self._estimate_threshold,
            reason="estimate_threshold",
            token_count=estimate,
            threshold=self._estimate_threshold,
        )
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/unit/context/test_estimator.py tests/unit/context/test_token_meter.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sebastian/context/estimator.py sebastian/context/token_meter.py tests/unit/context/test_estimator.py tests/unit/context/test_token_meter.py
git commit -m "feat(context): 增加上下文 token 估算与阈值判断"
```

---

### Task 4: Range Selection And Compaction Prompt

**Files:**
- Create: `sebastian/context/prompts.py`
- Create: `sebastian/context/compaction.py`
- Test: `tests/unit/context/test_compaction.py`

- [ ] **Step 1: Write range selection tests**

Create `tests/unit/context/test_compaction.py`:

```python
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
        items.append(item(seq, "user_message", exchange)); seq += 1
        items.append(item(seq, "assistant_message", exchange)); seq += 1

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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/context/test_compaction.py -q`

Expected: FAIL because `select_compaction_range` does not exist.

- [ ] **Step 3: Implement prompt builder**

Create `sebastian/context/prompts.py`:

```python
from __future__ import annotations


CONTEXT_COMPACTION_SYSTEM_PROMPT = """You compress old session context for Sebastian.

Write a faithful runtime handoff summary. Preserve continuation state and
memory-relevant facts. Do not invent, generalize, or turn temporary context into
long-term facts.

Use this Markdown structure exactly:

## Compressed Session Context

### User Goal

### Current Working State

### Key Decisions And Constraints

### Tool Results And Artifacts

### Memory-Relevant Facts Preserved

### Open Threads

### Handoff Notes
"""
```

- [ ] **Step 4: Implement range selection**

Create `sebastian/context/compaction.py` with focused dataclasses:

```python
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
    source_items = [item for group in source_groups for item in group]
    if len(source_items) < min_items:
        return None
    if _has_incomplete_tool_chain(source_items):
        return None
    seqs = [int(item["seq"]) for item in source_items]
    exchange_indexes = [
        item.get("exchange_index")
        for item in source_items
        if item.get("exchange_index") is not None
    ]
    return CompactionRange(
        source_seq_start=min(seqs),
        source_seq_end=max(seqs),
        source_exchange_start=min(exchange_indexes) if exchange_indexes else None,
        source_exchange_end=max(exchange_indexes) if exchange_indexes else None,
        items=source_items,
    )
```

Implement helpers:

- `_group_by_exchange()` groups by `exchange_index`, fallback starts a new group at each `user_message`.
- `_has_incomplete_tool_chain()` compares `tool_call.payload.tool_call_id` and `tool_result.payload.tool_call_id`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/context/test_compaction.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/context/prompts.py sebastian/context/compaction.py tests/unit/context/test_compaction.py
git commit -m "feat(context): 增加压缩范围选择与摘要提示词"
```

---

### Task 5: Atomic Timeline Compaction

**Files:**
- Modify: `sebastian/store/session_timeline.py`
- Modify: `sebastian/store/session_store.py`
- Test: `tests/unit/store/test_session_timeline.py`

- [ ] **Step 1: Write compact_range tests**

Append to `tests/unit/store/test_session_timeline.py`:

```python
async def test_compact_range_archives_source_and_inserts_summary(store, session_in_db) -> None:
    await store.append_timeline_items(
        session_in_db.id,
        "sebastian",
        [
            {"kind": "user_message", "role": "user", "content": "u1", "exchange_index": 1},
            {"kind": "assistant_message", "role": "assistant", "content": "a1", "exchange_index": 1},
            {"kind": "user_message", "role": "user", "content": "u2", "exchange_index": 2},
        ],
    )

    result = await store.compact_range(
        session_in_db.id,
        "sebastian",
        source_seq_start=1,
        source_seq_end=2,
        summary_content="summary",
        summary_payload={"summary_version": "context_compaction_v1"},
    )

    assert result.status == "compacted"
    context_items = await store.get_context_timeline_items(session_in_db.id, "sebastian")
    assert [item["kind"] for item in context_items] == ["context_summary", "user_message"]
    audit_items = await store.get_timeline_items(session_in_db.id, "sebastian", include_archived=True)
    assert audit_items[0]["archived"] is True
    assert audit_items[1]["archived"] is True
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/unit/store/test_session_timeline.py::test_compact_range_archives_source_and_inserts_summary -q
```

Expected: FAIL because `compact_range` does not exist.

- [ ] **Step 3: Implement result dataclass**

In `sebastian/store/session_timeline.py`:

```python
@dataclass(slots=True)
class CompactRangeResult:
    status: str
    summary_item: dict[str, Any] | None
    archived_item_count: int
```

- [ ] **Step 4: Implement `SessionTimelineStore.compact_range()`**

Requirements:

- lock by session using `_get_session_lock`
- transactionally select rows by `seq BETWEEN start/end`
- if any row missing or already archived: return `already_compacted`
- update rows to `archived=True`
- insert `context_summary` via existing seq allocation logic or direct insert inside same transaction
- set `effective_seq=source_seq_start`
- payload must include source seq fields

- [ ] **Step 5: Add SessionStore facade**

Modify `sebastian/store/session_store.py`:

```python
async def compact_range(...):
    if self._timeline is None:
        raise RuntimeError("compact_range requires db_factory")
    return await self._timeline.compact_range(...)
```

- [ ] **Step 6: Run store tests**

Run:

```bash
pytest tests/unit/store/test_session_timeline.py -q
pytest tests/unit/store/test_session_store.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sebastian/store/session_timeline.py sebastian/store/session_store.py tests/unit/store/test_session_timeline.py tests/unit/store/test_session_store.py
git commit -m "feat(store): 支持 timeline 原子上下文压缩"
```

---

### Task 6: SessionContextCompactionWorker

**Files:**
- Modify: `sebastian/context/compaction.py`
- Test: `tests/unit/context/test_compaction.py`

- [ ] **Step 1: Write worker dry-run test**

Add to `tests/unit/context/test_compaction.py`:

```python
async def test_worker_skips_when_range_too_small(fake_session_store, fake_llm_registry) -> None:
    worker = SessionContextCompactionWorker(
        session_store=fake_session_store,
        llm_registry=fake_llm_registry,
    )

    result = await worker.compact_session("s1", "sebastian", reason="manual")

    assert result.status == "skipped"
    assert result.reason == "range_too_small"
```

Create light fakes in the test file. The fake store should return too few context items.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/context/test_compaction.py::test_worker_skips_when_range_too_small -q`

Expected: FAIL because worker does not exist.

- [ ] **Step 3: Implement worker result dataclasses**

In `sebastian/context/compaction.py`:

```python
@dataclass(slots=True)
class CompactionResult:
    status: str
    reason: str | None = None
    summary_item_id: str | None = None
    source_seq_start: int | None = None
    source_seq_end: int | None = None
    archived_item_count: int = 0
    source_token_estimate: int | None = None
    summary_token_estimate: int | None = None
```

- [ ] **Step 4: Implement `SessionContextCompactionWorker.compact_session()`**

Core flow:

1. Read `session_store.get_context_timeline_items(session_id, agent_type)`.
2. Estimate source tokens.
3. Select range using `select_compaction_range()`.
4. If no range, return skipped.
5. Build compaction input text from source items.
6. Call LLM using a dedicated binding name, e.g. `context_compactor`.
7. Estimate summary tokens.
8. Call `session_store.compact_range(...)`.
9. Return metadata.

Keep first implementation simple:

- use `llm_registry.get_provider("context_compactor")`
- fallback to default provider can be deferred unless current registry pattern already supports it cleanly
- max_tokens for summary should be `min(8192, max(2048, int(source_tokens * 0.20)))`

- [ ] **Step 5: Add tests for payload fields**

Assert worker passes payload keys:

- `summary_version`
- `source_seq_start`
- `source_seq_end`
- `source_token_estimate`
- `summary_token_estimate`
- `retained_recent_exchanges`
- `reason`

- [ ] **Step 6: Run context tests**

Run: `pytest tests/unit/context -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sebastian/context/compaction.py tests/unit/context/test_compaction.py
git commit -m "feat(context): 增加 session 上下文压缩 worker"
```

---

### Task 7: Runtime Auto Scheduling

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/gateway/state.py`
- Test: `tests/unit/core/test_base_agent_provider.py`

- [ ] **Step 1: Add BaseAgent scheduling test**

In `tests/unit/core/test_base_agent_provider.py`, add a fake compaction scheduler and assert it is called after `TurnDone` when usage crosses threshold.

Expected shape:

```python
class FakeCompactionScheduler:
    def __init__(self) -> None:
        self.calls = []

    async def maybe_schedule_after_turn(self, **kwargs) -> None:
        self.calls.append(kwargs)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/core/test_base_agent_provider.py::test_stream_inner_schedules_compaction_after_turn -q`

Expected: FAIL because scheduler hook does not exist.

- [ ] **Step 3: Add runtime singleton**

Modify `sebastian/gateway/state.py`:

```python
context_compaction_worker: Any | None = None
```

- [ ] **Step 4: Initialize worker in app lifespan**

Modify `sebastian/gateway/app.py` after LLM registry/session store initialization:

```python
state.context_compaction_worker = SessionContextCompactionWorker(
    session_store=state.session_store,
    llm_registry=state.llm_registry,
)
```

On shutdown, clear it if needed.

- [ ] **Step 5: Collect usage in BaseAgent**

Modify `_stream_inner()`:

- keep `last_provider_usage: TokenUsage | None`
- when receiving `ProviderCallEnd`, update it
- after assistant message is persisted on `TurnDone`, call a small helper `_schedule_context_compaction_if_needed(...)`

- [ ] **Step 6: Implement helper**

In `BaseAgent`:

```python
async def _schedule_context_compaction_if_needed(
    self,
    *,
    session_id: str,
    agent_type: str,
    usage: TokenUsage | None,
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> None:
    ...
```

The helper imports `sebastian.gateway.state` lazily and calls worker scheduling only if present. It must swallow/log exceptions so normal turns are unaffected.

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/unit/core/test_base_agent_provider.py -q
pytest tests/unit/context -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/core/base_agent.py sebastian/gateway/app.py sebastian/gateway/state.py tests/unit/core/test_base_agent_provider.py
git commit -m "feat(core): turn 完成后调度上下文压缩"
```

---

### Task 8: Manual API And Status Endpoint

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `sebastian/gateway/README.md`
- Test: `tests/integration/gateway/test_context_compaction.py`

- [ ] **Step 1: Write API tests**

Create `tests/integration/gateway/test_context_compaction.py` with tests for:

- `POST /api/v1/sessions/{id}/compact` returns compacted/skipped metadata.
- active stream returns 409.
- `GET /api/v1/sessions/{id}/compaction/status` returns estimate/status fields.

Use existing gateway test fixtures and auth helpers; mirror patterns from `tests/integration/gateway`.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/integration/gateway/test_context_compaction.py -q`

Expected: FAIL because endpoints do not exist.

- [ ] **Step 3: Add request/response models**

In `sebastian/gateway/routes/sessions.py`:

```python
class CompactSessionBody(BaseModel):
    mode: Literal["manual"] = "manual"
    retain_recent_exchanges: int = 8
    dry_run: bool = False
```

Add response dicts with `status`, `reason`, and metadata.

- [ ] **Step 4: Implement manual compact endpoint**

Endpoint:

```python
@router.post("/sessions/{session_id}/compact")
async def compact_session(...):
```

Rules:

- resolve session
- if active stream/session state indicates running, return 409
- call `state.context_compaction_worker.compact_session(...)`
- return result

- [ ] **Step 5: Implement status endpoint**

Endpoint:

```python
@router.get("/sessions/{session_id}/compaction/status")
async def get_compaction_status(...):
```

Compute:

- current context token estimate
- last summary item seq from timeline items
- compactable exchange count
- retained_recent_exchanges default

- [ ] **Step 6: Run gateway tests**

Run:

```bash
pytest tests/integration/gateway/test_context_compaction.py -q
pytest tests/integration/gateway -q
```

Expected: PASS.

- [ ] **Step 7: Update gateway README**

Document:

- `POST /sessions/{id}/compact`
- `GET /sessions/{id}/compaction/status`
- active stream returns 409

- [ ] **Step 8: Commit**

```bash
git add sebastian/gateway/routes/sessions.py sebastian/gateway/README.md tests/integration/gateway/test_context_compaction.py
git commit -m "feat(gateway): 增加上下文压缩接口"
```

---

### Task 9: Android DTO And Debug Entry

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineItemDtoTest.kt`
- Optional Modify: settings/debug UI files after locating current Settings screen
- Modify: `ui/mobile-android/README.md`

- [ ] **Step 1: Add DTO test for exchange fields**

Modify `TimelineItemDtoTest.kt` to parse:

```json
{
  "exchange_id": "ex-1",
  "exchange_index": 3
}
```

Assert:

```kotlin
assertEquals("ex-1", item.exchangeId)
assertEquals(3, item.exchangeIndex)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests '*TimelineItemDtoTest*'
```

Expected: FAIL because fields do not exist.

- [ ] **Step 3: Add DTO fields**

Modify `TimelineItemDto.kt`:

```kotlin
@param:Json(name = "exchange_id") val exchangeId: String? = null,
@param:Json(name = "exchange_index") val exchangeIndex: Long? = null,
```

- [ ] **Step 4: Run DTO tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests '*TimelineItemDtoTest*'
```

Expected: PASS.

- [ ] **Step 5: Add manual compact debug action**

Locate current Settings/debug screen with:

```bash
rg -n "Settings|Debug|memory|logging" ui/mobile-android/app/src/main/java
```

Add a minimal `Compact context` action only if there is an existing debug/settings pattern for backend actions. Keep UI small. If no natural location exists, defer UI button and update README/API only.

- [ ] **Step 6: Update Android README**

Document that timeline items include exchange fields and `context_summary` remains rendered via `SummaryBlock`.

- [ ] **Step 7: Run Android unit tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineItemDtoTest.kt ui/mobile-android/README.md
git commit -m "feat(android): 解析上下文压缩 exchange 元数据"
```

If a UI button is implemented, add its exact files to `git add`.

---

### Task 10: Docs, Full Verification, And Cleanup

**Files:**
- Modify: `docs/architecture/spec/store/session-storage.md`
- Modify: `docs/superpowers/specs/2026-04-24-context-compaction-design.md`
- Modify: `CHANGELOG.md` if this proceeds to implementation PR

- [ ] **Step 1: Update architecture spec**

Update `docs/architecture/spec/store/session-storage.md`:

- session model includes `next_exchange_index`
- session item model includes `exchange_id/exchange_index`
- context compression model status moves from “view only” to “implemented/in-progress” as appropriate
- mention provider usage + estimator trigger

- [ ] **Step 2: Update context compaction spec with implementation discoveries**

If implementation changed names, thresholds, endpoint shapes, or payload fields, update `docs/superpowers/specs/2026-04-24-context-compaction-design.md`.

- [ ] **Step 3: Run backend lint and tests**

Run:

```bash
ruff check sebastian/ tests/
pytest tests/unit/context -q
pytest tests/unit/store -q
pytest tests/unit/core -q
pytest tests/integration/gateway -q
```

Expected: PASS.

- [ ] **Step 4: Run Android tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest
./gradlew :app:compileDebugKotlin
```

Expected: PASS.

- [ ] **Step 5: Update CHANGELOG**

Add an `[Unreleased]` entry:

```markdown
### Added
- 新增 session 上下文自动/手动压缩能力，长会话可保留完整历史并缩短 LLM 当前上下文。
```

- [ ] **Step 6: Final commit**

```bash
git add docs/architecture/spec/store/session-storage.md docs/superpowers/specs/2026-04-24-context-compaction-design.md CHANGELOG.md
git commit -m "docs: 更新上下文压缩架构文档"
```

---

## Implementation Notes

- 不要使用 `git add .` 或 `git add -A`。
- 每个 task 独立提交，便于 review 和回滚。
- 如果某个文件超过 800 行，暂停并和用户确认是否拆分。
- `context_summary` 的 provider projection 必须在启用压缩前修正，避免 Anthropic/OpenAI 输入出现无效连续结构。
- 自动压缩失败只记录日志，不影响正常 turn。
- 手动压缩遇到 active stream 必须返回 409，不能边写边压缩。


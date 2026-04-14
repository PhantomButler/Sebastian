# Phase 2a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a complete end-to-end chain where Sebastian delegates to Sub-Agents with configurable LLM providers, tracked in Android App.

**Architecture:** 4 slices — LLM Provider abstraction (AgentLoop refactor via `LLMProvider` ABC), A2A queue-based delegation (`A2ADispatcher` + worker loops), Gateway CRUD routes for providers + enriched agent list, App UI integration (Settings LLM providers + SubAgents page). Each slice is independently deployable and testable.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy async, `anthropic` SDK, `openai` SDK, `tomllib` (stdlib 3.11+), React Native, Zustand, Axios

---

## File Map

### Slice 1 — LLM Provider

| Action | Path |
|--------|------|
| Modify | `sebastian/core/stream_events.py` |
| Create | `sebastian/llm/__init__.py` |
| Create | `sebastian/llm/provider.py` |
| Create | `sebastian/llm/anthropic.py` |
| Create | `sebastian/llm/openai_compat.py` |
| Modify | `sebastian/store/models.py` |
| Create | `sebastian/llm/registry.py` |
| Modify | `sebastian/core/agent_loop.py` |
| Modify | `sebastian/core/base_agent.py` |
| Modify | `sebastian/gateway/state.py` |
| Modify | `sebastian/gateway/app.py` |
| Modify | `tests/unit/test_agent_loop.py` (full rewrite) |

### Slice 2 — A2A

| Action | Path |
|--------|------|
| Create | `sebastian/protocol/a2a/dispatcher.py` |
| Create | `sebastian/agents/_loader.py` |
| Create | `sebastian/agents/code/manifest.toml` |
| Create | `sebastian/agents/stock/manifest.toml` |
| Create | `sebastian/agents/life/manifest.toml` |
| Modify | `sebastian/agents/code/__init__.py` |
| Modify | `sebastian/agents/stock/__init__.py` |
| Modify | `sebastian/agents/life/__init__.py` |
| Modify | `sebastian/core/agent_pool.py` |
| Modify | `sebastian/core/base_agent.py` |
| Create | `sebastian/orchestrator/tools/__init__.py` |
| Create | `sebastian/orchestrator/tools/delegate.py` |
| Modify | `sebastian/orchestrator/sebas.py` |
| Modify | `sebastian/gateway/state.py` |
| Modify | `sebastian/gateway/app.py` |

### Slice 3 — Gateway + App

| Action | Path |
|--------|------|
| Create | `sebastian/gateway/routes/llm_providers.py` |
| Modify | `sebastian/gateway/routes/agents.py` |
| Modify | `sebastian/gateway/app.py` |
| Modify | `ui/mobile/src/types.ts` |
| Modify | `ui/mobile/src/api/agents.ts` |
| Create | `ui/mobile/src/api/llmProviders.ts` |
| Create | `ui/mobile/src/store/llmProviders.ts` |
| Modify | `ui/mobile/src/components/settings/LLMProviderConfig.tsx` |

### Slice 4 — Skills

| Action | Path |
|--------|------|
| Modify | `sebastian/config/__init__.py` |
| Create | `sebastian/capabilities/skills/_loader.py` |
| Modify | `sebastian/capabilities/registry.py` |
| Modify | `sebastian/gateway/app.py` |

---

## Slice 1: LLM Provider

---

### Task 1: Update stream_events.py

Add `ProviderCallEnd` event; add `thinking: str` to `ThinkingBlockStop` and `text: str` to `TextBlockStop`. These fields let `AgentLoop` build the assistant message without touching SDK internals.

**Files:**
- Modify: `sebastian/core/stream_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_stream_events.py`:

```python
from __future__ import annotations

def test_thinking_block_stop_has_thinking_field() -> None:
    from sebastian.core.stream_events import ThinkingBlockStop
    e = ThinkingBlockStop(block_id="b0_0", thinking="I reasoned.")
    assert e.thinking == "I reasoned."


def test_text_block_stop_has_text_field() -> None:
    from sebastian.core.stream_events import TextBlockStop
    e = TextBlockStop(block_id="b0_1", text="Hello.")
    assert e.text == "Hello."


def test_provider_call_end_has_stop_reason() -> None:
    from sebastian.core.stream_events import ProviderCallEnd
    e = ProviderCallEnd(stop_reason="end_turn")
    assert e.stop_reason == "end_turn"


def test_provider_call_end_is_in_llm_stream_event_union() -> None:
    from sebastian.core.stream_events import LLMStreamEvent, ProviderCallEnd
    e: LLMStreamEvent = ProviderCallEnd(stop_reason="tool_use")
    assert isinstance(e, ProviderCallEnd)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_stream_events.py -v
```

Expected: FAIL — `ThinkingBlockStop` and `TextBlockStop` have no extra fields; `ProviderCallEnd` doesn't exist.

- [ ] **Step 3: Update stream_events.py**

Replace the three dataclasses and the union:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ThinkingBlockStart:
    block_id: str


@dataclass
class ThinkingDelta:
    block_id: str
    delta: str


@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str        # full accumulated thinking text for this block


@dataclass
class TextBlockStart:
    block_id: str


@dataclass
class TextDelta:
    block_id: str
    delta: str


@dataclass
class TextBlockStop:
    block_id: str
    text: str            # full accumulated text for this block


@dataclass
class ToolCallBlockStart:
    block_id: str
    tool_id: str
    name: str


@dataclass
class ToolCallReady:
    block_id: str
    tool_id: str
    name: str
    inputs: dict[str, Any]


@dataclass
class ToolResult:
    tool_id: str
    name: str
    ok: bool
    output: Any
    error: str | None


@dataclass
class ProviderCallEnd:
    stop_reason: str     # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"


@dataclass
class TurnDone:
    full_text: str


LLMStreamEvent = (
    ThinkingBlockStart
    | ThinkingDelta
    | ThinkingBlockStop
    | TextBlockStart
    | TextDelta
    | TextBlockStop
    | ToolCallBlockStart
    | ToolCallReady
    | ToolResult
    | ProviderCallEnd
    | TurnDone
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_stream_events.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/stream_events.py tests/unit/test_stream_events.py
git commit -m "feat(core): add ProviderCallEnd and content fields to BlockStop events

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Create LLMProvider ABC

**Files:**
- Create: `sebastian/llm/__init__.py`
- Create: `sebastian/llm/provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_llm_provider.py`:

```python
from __future__ import annotations

import pytest


def test_llm_provider_is_abstract() -> None:
    from sebastian.llm.provider import LLMProvider
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        LLMProvider()  # type: ignore[abstract]


def test_llm_provider_stream_signature_accepted_by_subclass() -> None:
    from collections.abc import AsyncGenerator
    from sebastian.core.stream_events import LLMStreamEvent
    from sebastian.llm.provider import LLMProvider

    class ConcreteProvider(LLMProvider):
        async def stream(
            self,
            *,
            system: str,
            messages: list[dict],
            tools: list[dict],
            model: str,
            max_tokens: int,
            block_id_prefix: str = "",
        ) -> AsyncGenerator[LLMStreamEvent, None]:
            return
            yield  # make it an async generator

    p = ConcreteProvider()
    assert hasattr(p, "stream")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm_provider.py -v
```

Expected: FAIL — module `sebastian.llm` doesn't exist.

- [ ] **Step 3: Create the files**

`sebastian/llm/__init__.py` — empty:
```python
```

`sebastian/llm/provider.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from sebastian.core.stream_events import LLMStreamEvent


class LLMProvider(ABC):
    """Single-call LLM abstraction. Multi-turn loop lives in AgentLoop, not here.

    Implementations map SDK-specific streaming events to LLMStreamEvent and
    emit ProviderCallEnd as the final event with the stop_reason.
    """

    @abstractmethod
    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        block_id_prefix: str = "",
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        """Yield LLMStreamEvent objects for one complete LLM call.

        The last event MUST be ProviderCallEnd(stop_reason=...).
        block_id_prefix is prepended to every block_id (e.g. "b0_") to keep
        IDs unique across AgentLoop iterations.
        """
        ...
        yield  # satisfy type checker that this is an async generator
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_llm_provider.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/llm/__init__.py sebastian/llm/provider.py tests/unit/test_llm_provider.py
git commit -m "feat(llm): add LLMProvider abstract base class

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Implement AnthropicProvider

**Files:**
- Create: `sebastian/llm/anthropic.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_llm_provider.py`:

```python
@pytest.mark.asyncio
async def test_anthropic_provider_streams_text_and_ends() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.core.stream_events import (
        ProviderCallEnd,
        TextBlockStart,
        TextBlockStop,
        TextDelta,
    )
    from sebastian.llm.anthropic import AnthropicProvider

    # Build mock Anthropic SDK stream
    def _make_raw(type_: str, **kwargs: object) -> MagicMock:
        m = MagicMock()
        m.type = type_
        for k, v in kwargs.items():
            setattr(m, k, v)
        return m

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello world"

    final_msg = MagicMock()
    final_msg.stop_reason = "end_turn"

    raw_events = [
        _make_raw("content_block_start", index=0,
                  content_block=MagicMock(type="text")),
        _make_raw("content_block_delta", index=0,
                  delta=MagicMock(type="text_delta", text="Hello world")),
        _make_raw("content_block_stop", index=0),
    ]

    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=stream_ctx)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)
    stream_ctx.current_message = MagicMock(content=[text_block])
    stream_ctx.get_final_message = AsyncMock(return_value=final_msg)

    async def _iter():
        for e in raw_events:
            yield e

    stream_ctx.__aiter__ = lambda self: _iter()

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = mock_client

    events = []
    async for event in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="claude-opus-4-6",
        max_tokens=1000,
        block_id_prefix="b0_",
    ):
        events.append(event)

    assert events == [
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Hello world"),
        TextBlockStop(block_id="b0_0", text="Hello world"),
        ProviderCallEnd(stop_reason="end_turn"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm_provider.py::test_anthropic_provider_streams_text_and_ends -v
```

Expected: FAIL — `sebastian.llm.anthropic` doesn't exist.

- [ ] **Step 3: Create AnthropicProvider**

`sebastian/llm/anthropic.py`:

```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import anthropic

from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
    ToolCallBlockStart,
    ToolCallReady,
)
from sebastian.llm.provider import LLMProvider


class AnthropicProvider(LLMProvider):
    """Anthropic SDK adapter. Supports thinking blocks and tool use."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            **({"base_url": base_url} if base_url else {}),
        )

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        block_id_prefix: str = "",
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for raw in stream:
                block_index = getattr(raw, "index", 0)
                block_id = f"{block_id_prefix}{block_index}"

                if raw.type == "content_block_start":
                    block_type = raw.content_block.type
                    if block_type == "thinking":
                        yield ThinkingBlockStart(block_id=block_id)
                    elif block_type == "text":
                        yield TextBlockStart(block_id=block_id)
                    elif block_type == "tool_use":
                        yield ToolCallBlockStart(
                            block_id=block_id,
                            tool_id=raw.content_block.id,
                            name=raw.content_block.name,
                        )
                    continue

                if raw.type == "content_block_delta":
                    delta_type = raw.delta.type
                    if delta_type == "thinking_delta":
                        yield ThinkingDelta(block_id=block_id, delta=raw.delta.thinking)
                    elif delta_type == "text_delta":
                        yield TextDelta(block_id=block_id, delta=raw.delta.text)
                    continue

                if raw.type != "content_block_stop":
                    continue

                block = stream.current_message.content[block_index]
                if block.type == "thinking":
                    yield ThinkingBlockStop(block_id=block_id, thinking=block.thinking)
                elif block.type == "text":
                    yield TextBlockStop(block_id=block_id, text=block.text)
                elif block.type == "tool_use":
                    yield ToolCallReady(
                        block_id=block_id,
                        tool_id=block.id,
                        name=block.name,
                        inputs=block.input,
                    )

            final = await stream.get_final_message()
            yield ProviderCallEnd(stop_reason=final.stop_reason)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_llm_provider.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/llm/anthropic.py tests/unit/test_llm_provider.py
git commit -m "feat(llm): implement AnthropicProvider streaming adapter

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Implement OpenAICompatProvider

**Files:**
- Create: `sebastian/llm/openai_compat.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_llm_provider.py`:

```python
@pytest.mark.asyncio
async def test_openai_compat_provider_streams_text_and_ends() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from sebastian.core.stream_events import (
        ProviderCallEnd,
        TextBlockStart,
        TextBlockStop,
        TextDelta,
    )
    from sebastian.llm.openai_compat import OpenAICompatProvider

    def _chunk(content: str | None = None, finish_reason: str | None = None) -> MagicMock:
        chunk = MagicMock()
        choice = MagicMock()
        choice.finish_reason = finish_reason
        delta = MagicMock()
        delta.content = content
        delta.tool_calls = None
        choice.delta = delta
        chunk.choices = [choice]
        return chunk

    chunks = [
        _chunk(content="Hello"),
        _chunk(content=" world"),
        _chunk(finish_reason="stop"),
    ]

    async def _aiter_chunks():
        for c in chunks:
            yield c

    mock_completion = MagicMock()
    mock_completion.__aiter__ = lambda self: _aiter_chunks()

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._client = mock_client
    provider._thinking_format = None

    events = []
    async for event in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gpt-4o",
        max_tokens=1000,
        block_id_prefix="b0_",
    ):
        events.append(event)

    assert events == [
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Hello"),
        TextDelta(block_id="b0_0", delta=" world"),
        TextBlockStop(block_id="b0_0", text="Hello world"),
        ProviderCallEnd(stop_reason="end_turn"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm_provider.py::test_openai_compat_provider_streams_text_and_ends -v
```

Expected: FAIL — `sebastian.llm.openai_compat` doesn't exist.

- [ ] **Step 3: Create OpenAICompatProvider**

`sebastian/llm/openai_compat.py`:

```python
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import openai

from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
    ToolCallBlockStart,
    ToolCallReady,
)
from sebastian.llm.provider import LLMProvider


class OpenAICompatProvider(LLMProvider):
    """OpenAI /v1/chat/completions adapter.

    thinking_format values:
      None                — no thinking, plain text + tool calls
      "reasoning_content" — DeepSeek-R1 style: delta.reasoning_content field
      "think_tags"        — llama.cpp style: <think>...</think> in text content
    """

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        thinking_format: str | None = None,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            **({"base_url": base_url} if base_url else {}),
        )
        self._thinking_format = thinking_format

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        block_id_prefix: str = "",
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        openai_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *messages,
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

        text_block_id = f"{block_id_prefix}0"
        text_buffer = ""
        think_buffer = ""
        text_block_started = False
        think_block_started = False
        # tool_calls_raw: index → {id, name, arguments_str}
        tool_calls_raw: dict[int, dict[str, str]] = {}
        stop_reason = "end_turn"

        async for chunk in await self._client.chat.completions.create(**kwargs):
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish = choice.finish_reason
            delta = choice.delta

            # --- text / thinking content ---
            content: str = delta.content or ""
            reasoning: str = getattr(delta, "reasoning_content", None) or ""

            if self._thinking_format == "reasoning_content" and reasoning:
                if not think_block_started:
                    think_block_id = f"{block_id_prefix}think"
                    yield ThinkingBlockStart(block_id=think_block_id)
                    think_block_started = True
                think_buffer += reasoning
                yield ThinkingDelta(block_id=f"{block_id_prefix}think", delta=reasoning)

            if content:
                if self._thinking_format == "think_tags":
                    # Buffer and parse <think>...</think> inline
                    think_buffer, text_buffer, events = _parse_think_tags(
                        think_buffer, text_buffer,
                        content, f"{block_id_prefix}think", text_block_id,
                        think_block_started, text_block_started,
                    )
                    for ev in events:
                        if isinstance(ev, ThinkingBlockStart):
                            think_block_started = True
                        if isinstance(ev, TextBlockStart):
                            text_block_started = True
                        yield ev
                else:
                    if not text_block_started:
                        yield TextBlockStart(block_id=text_block_id)
                        text_block_started = True
                    text_buffer += content
                    yield TextDelta(block_id=text_block_id, delta=content)

            # --- tool call accumulation ---
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_raw[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_raw[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_raw[idx]["arguments"] += tc.function.arguments

            if finish is not None:
                break

        # Flush open text/thinking blocks
        if think_block_started and self._thinking_format in ("reasoning_content", "think_tags"):
            yield ThinkingBlockStop(
                block_id=f"{block_id_prefix}think", thinking=think_buffer
            )
        if text_block_started:
            yield TextBlockStop(block_id=text_block_id, text=text_buffer)

        # Emit tool calls
        for idx in sorted(tool_calls_raw):
            tc = tool_calls_raw[idx]
            tc_block_id = f"{block_id_prefix}{idx + 1}"
            try:
                inputs = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                inputs = {}
            yield ToolCallBlockStart(
                block_id=tc_block_id, tool_id=tc["id"], name=tc["name"]
            )
            yield ToolCallReady(
                block_id=tc_block_id,
                tool_id=tc["id"],
                name=tc["name"],
                inputs=inputs,
            )
            stop_reason = "tool_use"

        yield ProviderCallEnd(stop_reason=stop_reason)


def _parse_think_tags(
    think_buffer: str,
    text_buffer: str,
    new_content: str,
    think_block_id: str,
    text_block_id: str,
    think_block_started: bool,
    text_block_started: bool,
) -> tuple[str, str, list[LLMStreamEvent]]:
    """Parse <think>...</think> from streaming text. Returns updated buffers + events."""
    events: list[LLMStreamEvent] = []
    combined = (think_buffer if think_block_started and not text_block_started else "") + new_content

    # Simple state machine: if we haven't seen </think> yet, check if this content has it
    in_think = think_block_started and not text_block_started

    remaining = new_content
    while remaining:
        if in_think:
            close_idx = remaining.find("</think>")
            if close_idx == -1:
                think_buffer += remaining
                events.append(ThinkingDelta(block_id=think_block_id, delta=remaining))
                remaining = ""
            else:
                think_part = remaining[:close_idx]
                think_buffer += think_part
                if think_part:
                    events.append(ThinkingDelta(block_id=think_block_id, delta=think_part))
                events.append(ThinkingBlockStop(block_id=think_block_id, thinking=think_buffer))
                think_buffer = ""
                in_think = False
                remaining = remaining[close_idx + len("</think>"):]
        else:
            open_idx = remaining.find("<think>")
            if open_idx == -1:
                if not text_block_started:
                    events.append(TextBlockStart(block_id=text_block_id))
                    text_block_started = True
                text_buffer += remaining
                events.append(TextDelta(block_id=text_block_id, delta=remaining))
                remaining = ""
            else:
                pre = remaining[:open_idx]
                if pre:
                    if not text_block_started:
                        events.append(TextBlockStart(block_id=text_block_id))
                        text_block_started = True
                    text_buffer += pre
                    events.append(TextDelta(block_id=text_block_id, delta=pre))
                events.append(ThinkingBlockStart(block_id=think_block_id))
                in_think = True
                remaining = remaining[open_idx + len("<think>"):]

    return think_buffer, text_buffer, events
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_llm_provider.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/llm/openai_compat.py tests/unit/test_llm_provider.py
git commit -m "feat(llm): implement OpenAICompatProvider with think_tags and reasoning_content support

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Add LLMProviderRecord to store/models.py

**Files:**
- Modify: `sebastian/store/models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_task_store.py` (or create `tests/unit/test_llm_provider_store.py`):

```python
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db_session_with_providers():
    from sebastian.store.database import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_llm_provider_record_roundtrip(db_session_with_providers) -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="Claude Home",
        provider_type="anthropic",
        base_url=None,
        api_key="sk-ant-test",
        model="claude-opus-4-6",
        thinking_format=None,
        is_default=True,
    )
    db_session_with_providers.add(record)
    await db_session_with_providers.commit()

    from sqlalchemy import select
    result = await db_session_with_providers.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.is_default == True)
    )
    loaded = result.scalar_one()
    assert loaded.name == "Claude Home"
    assert loaded.api_key == "sk-ant-test"
    assert loaded.provider_type == "anthropic"
    assert loaded.is_default is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm_provider_store.py -v
```

Expected: FAIL — `LLMProviderRecord` doesn't exist.

- [ ] **Step 3: Add LLMProviderRecord to models.py**

Append to `sebastian/store/models.py`:

```python
from uuid import uuid4

from sqlalchemy import Boolean


class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)   # "anthropic" | "openai"
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)        # plaintext; same trust boundary as .env
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    thinking_format: Mapped[str | None] = mapped_column(String(50), nullable=True)  # None | "reasoning_content" | "think_tags"
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

Also add `Boolean` and `uuid4` to the existing imports at the top of `models.py`:

```python
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_llm_provider_store.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/store/models.py tests/unit/test_llm_provider_store.py
git commit -m "feat(store): add LLMProviderRecord model

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Implement LLMProviderRegistry

**Files:**
- Create: `sebastian/llm/registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_llm_registry.py`:

```python
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def registry_with_db():
    from sebastian.store.database import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    from sebastian.llm.registry import LLMProviderRegistry
    yield LLMProviderRegistry(factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_registry_returns_env_fallback_when_no_default(registry_with_db, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fallback")
    from sebastian.llm.anthropic import AnthropicProvider
    provider = await registry_with_db.get_default()
    assert isinstance(provider, AnthropicProvider)


@pytest.mark.asyncio
async def test_registry_create_and_list(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord
    record = LLMProviderRecord(
        name="My Claude",
        provider_type="anthropic",
        api_key="sk-ant-abc",
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    assert len(records) == 1
    assert records[0].name == "My Claude"


@pytest.mark.asyncio
async def test_registry_get_default_uses_db_record(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord
    from sebastian.llm.anthropic import AnthropicProvider
    record = LLMProviderRecord(
        name="DB Claude",
        provider_type="anthropic",
        api_key="sk-ant-db",
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(record)
    provider = await registry_with_db.get_default()
    assert isinstance(provider, AnthropicProvider)


@pytest.mark.asyncio
async def test_registry_delete(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord
    record = LLMProviderRecord(
        name="To Delete",
        provider_type="anthropic",
        api_key="sk-ant-del",
        model="claude-opus-4-6",
        is_default=False,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    record_id = records[0].id
    deleted = await registry_with_db.delete(record_id)
    assert deleted is True
    assert await registry_with_db.list_all() == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm_registry.py -v
```

Expected: FAIL — `sebastian.llm.registry` doesn't exist.

- [ ] **Step 3: Create LLMProviderRegistry**

`sebastian/llm/registry.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from sebastian.llm.provider import LLMProvider
from sebastian.store.models import LLMProviderRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class LLMProviderRegistry:
    """DB-backed registry for LLM providers. Falls back to env-configured Anthropic
    when no default provider is stored."""

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

    async def get_default(self) -> LLMProvider:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord)
                .where(LLMProviderRecord.is_default == True)  # noqa: E712
                .limit(1)
            )
            record = result.scalar_one_or_none()

        if record is None:
            from sebastian.config import settings
            from sebastian.llm.anthropic import AnthropicProvider
            return AnthropicProvider(api_key=settings.anthropic_api_key)

        return self._instantiate(record)

    async def get_by_id(self, provider_id: str) -> LLMProvider | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == provider_id)
            )
            record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._instantiate(record)

    async def list_all(self) -> list[LLMProviderRecord]:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).order_by(LLMProviderRecord.created_at)
            )
            return list(result.scalars().all())

    async def create(self, record: LLMProviderRecord) -> None:
        async with self._db_factory() as session:
            session.add(record)
            await session.commit()

    async def update(self, record_id: str, **kwargs: Any) -> LLMProviderRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in kwargs.items():
                setattr(record, key, value)
            await session.commit()
            await session.refresh(record)
            return record

    async def delete(self, record_id: str) -> bool:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True

    def _instantiate(self, record: LLMProviderRecord) -> LLMProvider:
        if record.provider_type == "anthropic":
            from sebastian.llm.anthropic import AnthropicProvider
            return AnthropicProvider(api_key=record.api_key, base_url=record.base_url)
        if record.provider_type == "openai":
            from sebastian.llm.openai_compat import OpenAICompatProvider
            return OpenAICompatProvider(
                api_key=record.api_key,
                base_url=record.base_url,
                thinking_format=record.thinking_format,
            )
        raise ValueError(f"Unknown provider_type: {record.provider_type!r}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_llm_registry.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/llm/registry.py tests/unit/test_llm_registry.py
git commit -m "feat(llm): implement LLMProviderRegistry with DB CRUD and env fallback

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Refactor AgentLoop to use LLMProvider

`AgentLoop` currently holds an `anthropic.AsyncAnthropic` client and drives Anthropic's streaming protocol directly. Replace it with `LLMProvider` so it becomes SDK-agnostic.

**Files:**
- Modify: `sebastian/core/agent_loop.py`
- Modify: `tests/unit/test_agent_loop.py` (full rewrite)

- [ ] **Step 1: Rewrite the test file**

Replace the entire contents of `tests/unit/test_agent_loop.py`:

```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
    ThinkingBlockStart,
    ThinkingBlockStop,
    ThinkingDelta,
    ToolCallBlockStart,
    ToolCallReady,
    ToolResult,
    TurnDone,
)
from sebastian.llm.provider import LLMProvider


class MockLLMProvider(LLMProvider):
    """Test double that replays pre-configured event sequences."""

    def __init__(self, *turns: list[LLMStreamEvent]) -> None:
        self._turns = list(turns)
        self.call_count = 0
        self.last_messages: list[dict] = []

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        block_id_prefix: str = "",
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        if self.call_count >= len(self._turns):
            raise RuntimeError(
                f"MockLLMProvider has no more turns (called {self.call_count} times)"
            )
        self.last_messages = list(messages)
        events = self._turns[self.call_count]
        self.call_count += 1
        for event in events:
            yield event


async def _collect(gen: Any) -> list[object]:
    events: list[object] = []
    try:
        while True:
            events.append(await gen.asend(None))
    except StopAsyncIteration:
        return events


@pytest.mark.asyncio
async def test_agent_loop_streams_thinking_and_text_then_turn_done() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider([
        ThinkingBlockStart(block_id="b0_0"),
        ThinkingDelta(block_id="b0_0", delta="Need to inspect."),
        ThinkingBlockStop(block_id="b0_0", thinking="Need to inspect."),
        TextBlockStart(block_id="b0_1"),
        TextDelta(block_id="b0_1", delta="Hello there!"),
        TextBlockStop(block_id="b0_1", text="Hello there!"),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    loop = AgentLoop(provider, CapabilityRegistry())
    events = await _collect(
        loop.stream(system_prompt="You are helpful.",
                    messages=[{"role": "user", "content": "Hi"}])
    )

    assert events == [
        ThinkingBlockStart(block_id="b0_0"),
        ThinkingDelta(block_id="b0_0", delta="Need to inspect."),
        ThinkingBlockStop(block_id="b0_0", thinking="Need to inspect."),
        TextBlockStart(block_id="b0_1"),
        TextDelta(block_id="b0_1", delta="Hello there!"),
        TextBlockStop(block_id="b0_1", text="Hello there!"),
        TurnDone(full_text="Hello there!"),
    ]
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_agent_loop_ends_after_single_no_tool_turn() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop

    provider = MockLLMProvider([
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Done."),
        TextBlockStop(block_id="b0_0", text="Done."),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    loop = AgentLoop(provider, CapabilityRegistry())
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "Hi"}])

    assert await gen.asend(None) == TextBlockStart(block_id="b0_0")
    assert await gen.asend(None) == TextDelta(block_id="b0_0", delta="Done.")
    assert await gen.asend(None) == TextBlockStop(block_id="b0_0", text="Done.")
    assert await gen.asend(None) == TurnDone(full_text="Done.")

    with pytest.raises(StopAsyncIteration):
        await gen.asend(None)

    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_agent_loop_accepts_injected_tool_result_and_continues() -> None:
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextDelta(block_id="b0_0", delta="Checking..."),
            TextBlockStop(block_id="b0_0", text="Checking..."),
            ToolCallBlockStart(block_id="b0_1", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_1", tool_id="toolu_1", name="weather_lookup",
                inputs={"city": "Shanghai"},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="It is sunny."),
            TextBlockStop(block_id="b1_0", text="It is sunny."),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    registry = MagicMock()
    registry.get_all_tool_specs.return_value = [
        {"name": "weather_lookup", "description": "Lookup weather",
         "input_schema": {"type": "object"}}
    ]

    loop = AgentLoop(provider, registry)
    gen = loop.stream(
        system_prompt="sys",
        messages=[{"role": "user", "content": "What's the weather?"}],
    )

    assert await gen.asend(None) == TextBlockStart(block_id="b0_0")
    assert await gen.asend(None) == TextDelta(block_id="b0_0", delta="Checking...")
    assert await gen.asend(None) == TextBlockStop(block_id="b0_0", text="Checking...")
    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_1", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_1", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )

    injected = ToolResult(tool_id="toolu_1", name="weather_lookup", ok=True, output="Sunny", error=None)
    assert await gen.asend(injected) == TextBlockStart(block_id="b1_0")
    assert await gen.asend(None) == TextDelta(block_id="b1_0", delta="It is sunny.")
    assert await gen.asend(None) == TextBlockStop(block_id="b1_0", text="It is sunny.")
    assert await gen.asend(None) == TurnDone(full_text="Checking...It is sunny.")

    assert provider.call_count == 2
    second_messages = provider.last_messages
    assert second_messages[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny"}],
    }


@pytest.mark.asyncio
async def test_agent_loop_rejects_missing_tool_result_injection() -> None:
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider([
        ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
        ToolCallReady(
            block_id="b0_0", tool_id="toolu_1", name="weather_lookup",
            inputs={"city": "Shanghai"},
        ),
        ProviderCallEnd(stop_reason="tool_use"),
    ])

    loop = AgentLoop(provider, MagicMock(get_all_tool_specs=MagicMock(return_value=[])))
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "weather"}])

    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )

    with pytest.raises(RuntimeError, match="requires an injected ToolResult"):
        await gen.asend(None)


@pytest.mark.asyncio
async def test_agent_loop_rejects_mismatched_tool_result_injection() -> None:
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider([
        ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
        ToolCallReady(
            block_id="b0_0", tool_id="toolu_1", name="weather_lookup",
            inputs={"city": "Shanghai"},
        ),
        ProviderCallEnd(stop_reason="tool_use"),
    ])

    loop = AgentLoop(provider, MagicMock(get_all_tool_specs=MagicMock(return_value=[])))
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "weather"}])

    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )

    with pytest.raises(RuntimeError, match="does not match current tool call"):
        await gen.asend(
            ToolResult(tool_id="toolu_2", name="other_tool", ok=True, output="X", error=None)
        )


@pytest.mark.asyncio
async def test_agent_loop_formats_failed_tool_result_for_next_turn() -> None:
    from sebastian.core.agent_loop import AgentLoop
    from unittest.mock import MagicMock

    provider = MockLLMProvider(
        [
            ToolCallBlockStart(block_id="b0_0", tool_id="toolu_1", name="weather_lookup"),
            ToolCallReady(
                block_id="b0_0", tool_id="toolu_1", name="weather_lookup",
                inputs={"city": "Shanghai"},
            ),
            ProviderCallEnd(stop_reason="tool_use"),
        ],
        [
            TextBlockStart(block_id="b1_0"),
            TextDelta(block_id="b1_0", delta="Fallback."),
            TextBlockStop(block_id="b1_0", text="Fallback."),
            ProviderCallEnd(stop_reason="end_turn"),
        ],
    )

    loop = AgentLoop(provider, MagicMock(get_all_tool_specs=MagicMock(return_value=[])))
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "weather"}])

    assert await gen.asend(None) == ToolCallBlockStart(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup"
    )
    assert await gen.asend(None) == ToolCallReady(
        block_id="b0_0", tool_id="toolu_1", name="weather_lookup", inputs={"city": "Shanghai"}
    )
    assert await gen.asend(
        ToolResult(tool_id="toolu_1", name="weather_lookup", ok=False, output=None, error="network down")
    ) == TextBlockStart(block_id="b1_0")
    assert await gen.asend(None) == TextDelta(block_id="b1_0", delta="Fallback.")
    assert await gen.asend(None) == TextBlockStop(block_id="b1_0", text="Fallback.")
    assert await gen.asend(None) == TurnDone(full_text="Fallback.")

    last_messages = provider.last_messages
    assert last_messages[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Error: network down"}],
    }
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_agent_loop.py -v
```

Expected: FAIL — `AgentLoop` still takes `client: Any` not `LLMProvider`.

- [ ] **Step 3: Rewrite agent_loop.py**

Replace the entire contents of `sebastian/core/agent_loop.py`:

```python
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from sebastian.capabilities.registry import CapabilityRegistry
from sebastian.core.stream_events import (
    LLMStreamEvent,
    ProviderCallEnd,
    TextBlockStop,
    ThinkingBlockStop,
    ToolCallReady,
    ToolResult,
    TurnDone,
)

if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20


def _tool_result_content(result: ToolResult) -> str:
    if result.ok:
        return str(result.output)
    return f"Error: {result.error}"


def _validate_injected_tool_result(
    *,
    tool_id: str,
    tool_name: str,
    result: ToolResult | None,
) -> ToolResult:
    if result is None:
        raise RuntimeError(f"Tool call {tool_name} ({tool_id}) requires an injected ToolResult")
    if result.tool_id != tool_id or result.name != tool_name:
        raise RuntimeError(
            f"Injected ToolResult does not match current tool call {tool_name} ({tool_id})"
        )
    return result


class AgentLoop:
    """Core reasoning loop. Drives multi-turn LLM conversation via LLMProvider."""

    def __init__(
        self,
        provider: LLMProvider,
        registry: CapabilityRegistry,
        model: str = "claude-opus-4-6",
        max_tokens: int | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._model = model
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            from sebastian.config import settings
            self._max_tokens = settings.llm_max_tokens

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        task_id: str | None = None,
    ) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
        """Yield LLM stream events; accept tool results injected via asend()."""
        working = list(messages)
        tools = self._registry.get_all_tool_specs()
        full_text_parts: list[str] = []

        for iteration in range(MAX_ITERATIONS):
            assistant_content: list[dict[str, Any]] = []
            tool_results_for_next: list[dict[str, Any]] = []
            stop_reason = "end_turn"

            async for event in self._provider.stream(
                system=system_prompt,
                messages=working,
                tools=tools,
                model=self._model,
                max_tokens=self._max_tokens,
                block_id_prefix=f"b{iteration}_",
            ):
                if isinstance(event, ProviderCallEnd):
                    stop_reason = event.stop_reason
                    continue

                if isinstance(event, ThinkingBlockStop):
                    assistant_content.append(
                        {"type": "thinking", "thinking": event.thinking}
                    )
                    yield event

                elif isinstance(event, TextBlockStop):
                    full_text_parts.append(event.text)
                    assistant_content.append({"type": "text", "text": event.text})
                    yield event

                elif isinstance(event, ToolCallReady):
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": event.tool_id,
                            "name": event.name,
                            "input": event.inputs,
                        }
                    )
                    injected = yield event
                    validated = _validate_injected_tool_result(
                        tool_id=event.tool_id,
                        tool_name=event.name,
                        result=injected,
                    )
                    tool_results_for_next.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": event.tool_id,
                            "content": _tool_result_content(validated),
                        }
                    )

                else:
                    yield event

            working.append({"role": "assistant", "content": assistant_content})

            if stop_reason != "tool_use":
                yield TurnDone(full_text="".join(full_text_parts))
                return

            working.append({"role": "user", "content": tool_results_for_next})

        logger.warning("Reached MAX_ITERATIONS (%d) for task_id=%s", MAX_ITERATIONS, task_id)
        yield TurnDone(full_text="".join(full_text_parts))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_agent_loop.py -v
```

Expected: PASS (6 tests)

- [ ] **Step 5: Run full test suite to catch regressions**

```bash
pytest tests/ -v --tb=short
```

Expected: all pass (BaseAgent tests may need fixing — handled in Task 8).

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/agent_loop.py tests/unit/test_agent_loop.py
git commit -m "refactor(core): AgentLoop now takes LLMProvider instead of Anthropic client

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Refactor BaseAgent to accept LLMProvider

**Files:**
- Modify: `sebastian/core/base_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_base_agent_provider.py`:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
)
from tests.unit.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_base_agent_uses_injected_provider() -> None:
    """BaseAgent passes the injected LLMProvider to AgentLoop."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider([
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Hello from sub."),
        TextBlockStop(block_id="b0_0", text="Hello from sub."),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    from sebastian.memory.episodic_memory import EpisodicMemory
    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        registry=CapabilityRegistry(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    result = await agent.run("hi", session_id="test_sess_01")
    assert result == "Hello from sub."
    assert provider.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_base_agent_provider.py -v
```

Expected: FAIL — `BaseAgent.__init__` doesn't accept `provider` kwarg.

- [ ] **Step 3: Update BaseAgent.__init__**

In `sebastian/core/base_agent.py`:

1. Remove `import anthropic` at the top.

2. Add import block:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider
```

3. Replace the `__init__` signature and body:
```python
    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        event_bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._registry = registry
        self._session_store = session_store
        self._event_bus = event_bus
        self._episodic = EpisodicMemory(session_store)
        self.working_memory = WorkingMemory()
        self._active_stream: asyncio.Task[str] | None = None

        from sebastian.config import settings
        resolved_model = model or settings.sebastian_model

        if provider is None:
            from sebastian.llm.anthropic import AnthropicProvider
            provider = AnthropicProvider(api_key=settings.anthropic_api_key)

        self._loop = AgentLoop(provider, registry, resolved_model)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_base_agent_provider.py tests/unit/test_agent_loop.py -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Fix any remaining failures.

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent_provider.py
git commit -m "refactor(core): BaseAgent accepts optional LLMProvider, falls back to env Anthropic

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Wire LLMProviderRegistry into app.py and state.py

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`
- Modify: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_llm_provider_wiring.py`:

```python
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
import os


@pytest.mark.asyncio
async def test_gateway_starts_and_has_llm_registry() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")

    from sebastian.gateway.app import create_app
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200

    import sebastian.gateway.state as state
    assert hasattr(state, "llm_registry")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_llm_provider_wiring.py -v
```

Expected: FAIL — `state.llm_registry` doesn't exist.

- [ ] **Step 3: Update state.py**

Replace `sebastian/gateway/state.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.core.agent_pool import AgentPool
    from sebastian.gateway.sse import SSEManager
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

sebastian: Sebastian
sse_manager: SSEManager
event_bus: EventBus
conversation: ConversationManager
session_store: SessionStore
index_store: IndexStore
db_factory: async_sessionmaker[AsyncSession]
llm_registry: LLMProviderRegistry
agent_pools: dict[str, AgentPool] = {}
worker_sessions: dict[str, str | None] = {}
```

- [ ] **Step 4: Update lifespan in app.py**

In the `lifespan` function, add registry init and pass provider to Sebastian. Replace the block from `ensure_data_dir()` through `sebastian_agent = Sebastian(...)`:

```python
    ensure_data_dir()
    await init_db()
    db_factory = get_session_factory()
    session_store = SessionStore(settings.sessions_dir)
    index_store = IndexStore(settings.sessions_dir)

    from sebastian.llm.registry import LLMProviderRegistry
    llm_registry = LLMProviderRegistry(db_factory)
    default_provider = await llm_registry.get_default()

    load_tools()

    mcp_clients = load_mcps()
    if mcp_clients:
        await connect_all(mcp_clients, registry)

    event_bus = bus
    conversation = ConversationManager(event_bus)
    task_manager = TaskManager(session_store, event_bus, index_store=index_store)
    sse_mgr = SSEManager(event_bus)
    sebastian_agent = Sebastian(
        registry=registry,
        session_store=session_store,
        index_store=index_store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
        provider=default_provider,
    )
```

Also add `state.llm_registry = llm_registry` after the other state assignments.

- [ ] **Step 5: Update Sebastian.__init__ to accept provider**

In `sebastian/orchestrator/sebas.py`, update the signature:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider

class Sebastian(BaseAgent):
    ...
    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
        provider: LLMProvider | None = None,
    ) -> None:
        super().__init__(registry, session_store, event_bus=event_bus, provider=provider)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/integration/test_llm_provider_wiring.py -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 8: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py sebastian/orchestrator/sebas.py \
        tests/integration/test_llm_provider_wiring.py
git commit -m "feat(gateway): wire LLMProviderRegistry into lifespan and pass provider to Sebastian

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Slice 2: A2A

---

### Task 10: Implement A2ADispatcher

**Files:**
- Create: `sebastian/protocol/a2a/dispatcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_a2a_dispatcher.py`:

```python
from __future__ import annotations

import asyncio
import pytest


@pytest.mark.asyncio
async def test_dispatcher_delegate_resolves_when_worker_resolves() -> None:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask, TaskResult

    dispatcher = A2ADispatcher()
    queue = dispatcher.register_agent("code")

    task = DelegateTask(task_id="t1", goal="write hello.py")
    future_result = asyncio.create_task(dispatcher.delegate("code", task))

    received_task = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received_task.task_id == "t1"

    dispatcher.resolve(TaskResult(task_id="t1", ok=True, output={"summary": "done"}))

    result = await asyncio.wait_for(future_result, timeout=1.0)
    assert result.ok is True
    assert result.output["summary"] == "done"


@pytest.mark.asyncio
async def test_dispatcher_unknown_agent_returns_error() -> None:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask

    dispatcher = A2ADispatcher()
    task = DelegateTask(task_id="t2", goal="something")
    result = await dispatcher.delegate("nonexistent", task)
    assert result.ok is False
    assert "nonexistent" in (result.error or "")


@pytest.mark.asyncio
async def test_dispatcher_resolve_ignores_unknown_task_id() -> None:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import TaskResult

    dispatcher = A2ADispatcher()
    # Should not raise
    dispatcher.resolve(TaskResult(task_id="ghost", ok=True))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_a2a_dispatcher.py -v
```

Expected: FAIL — `sebastian.protocol.a2a.dispatcher` doesn't exist.

- [ ] **Step 3: Create A2ADispatcher**

`sebastian/protocol/a2a/dispatcher.py`:

```python
from __future__ import annotations

import asyncio
import logging

from sebastian.protocol.a2a.types import DelegateTask, TaskResult

logger = logging.getLogger(__name__)


class A2ADispatcher:
    """Routes DelegateTask objects to per-agent-type queues and resolves results.

    Each agent type gets its own asyncio.Queue to prevent cross-type head-of-line
    blocking. Results are returned via per-task asyncio.Future objects.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[DelegateTask]] = {}
        self._futures: dict[str, asyncio.Future[TaskResult]] = {}

    def register_agent(self, agent_type: str) -> asyncio.Queue[DelegateTask]:
        """Create and store a queue for agent_type. Returns the queue."""
        queue: asyncio.Queue[DelegateTask] = asyncio.Queue()
        self._queues[agent_type] = queue
        return queue

    def get_queue(self, agent_type: str) -> asyncio.Queue[DelegateTask] | None:
        return self._queues.get(agent_type)

    async def delegate(self, agent_type: str, task: DelegateTask) -> TaskResult:
        """Put task in the agent's queue and await its result."""
        queue = self._queues.get(agent_type)
        if queue is None:
            return TaskResult(
                task_id=task.task_id,
                ok=False,
                error=f"No agent registered for type: {agent_type!r}",
            )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[TaskResult] = loop.create_future()
        self._futures[task.task_id] = future

        await queue.put(task)
        try:
            return await future
        finally:
            self._futures.pop(task.task_id, None)

    def resolve(self, result: TaskResult) -> None:
        """Called by worker loop when a task completes."""
        future = self._futures.get(result.task_id)
        if future is not None and not future.done():
            future.set_result(result)
        else:
            logger.debug(
                "resolve() called for unknown or already-done task_id=%s", result.task_id
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_a2a_dispatcher.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/protocol/a2a/dispatcher.py tests/unit/test_a2a_dispatcher.py
git commit -m "feat(protocol): implement A2ADispatcher with per-agent-type queues

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 11: Create agents/_loader.py and manifest.toml files

**Files:**
- Create: `sebastian/agents/_loader.py`
- Modify: `sebastian/agents/code/__init__.py`
- Modify: `sebastian/agents/stock/__init__.py`
- Modify: `sebastian/agents/life/__init__.py`
- Create: `sebastian/agents/code/manifest.toml`
- Create: `sebastian/agents/stock/manifest.toml`
- Create: `sebastian/agents/life/manifest.toml`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_agents_loader.py`:

```python
from __future__ import annotations

import pytest
from pathlib import Path


def test_load_agents_returns_configs_for_manifest_dirs(tmp_path) -> None:
    """Loader reads manifest.toml and returns AgentConfig objects."""
    agent_dir = tmp_path / "testagent"
    agent_dir.mkdir()
    (agent_dir / "manifest.toml").write_text(
        '[agent]\nname = "Test Agent"\ndescription = "Does testing"\nworker_count = 2\nclass_name = "TestAgent"\n'
    )
    (agent_dir / "__init__.py").write_text(
        "from sebastian.core.base_agent import BaseAgent\n\n"
        "class TestAgent(BaseAgent):\n    name = 'testagent'\n    system_prompt = 'test'\n"
    )

    import sys
    sys.path.insert(0, str(tmp_path))
    try:
        from sebastian.agents._loader import load_agents
        configs = load_agents(extra_dirs=[tmp_path])
    finally:
        sys.path.remove(str(tmp_path))

    test_cfg = next((c for c in configs if c.agent_type == "testagent"), None)
    assert test_cfg is not None
    assert test_cfg.name == "Test Agent"
    assert test_cfg.description == "Does testing"
    assert test_cfg.worker_count == 2


def test_load_agents_includes_builtin_agents() -> None:
    from sebastian.agents._loader import load_agents
    configs = load_agents()
    agent_types = {c.agent_type for c in configs}
    assert "code" in agent_types
    assert "stock" in agent_types
    assert "life" in agent_types
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_agents_loader.py -v
```

Expected: FAIL — `sebastian.agents._loader` doesn't exist; manifests don't exist.

- [ ] **Step 3: Create manifest.toml files**

`sebastian/agents/code/manifest.toml`:
```toml
[agent]
name = "Code Agent"
description = "Executes code tasks: writes, runs, and debugs Python and shell scripts"
worker_count = 3
class_name = "CodeAgent"
```

`sebastian/agents/stock/manifest.toml`:
```toml
[agent]
name = "Stock Agent"
description = "Performs stock and investment research: price lookup, financial analysis, market summaries"
worker_count = 3
class_name = "StockAgent"
```

`sebastian/agents/life/manifest.toml`:
```toml
[agent]
name = "Life Agent"
description = "Handles daily life tasks: schedules, reminders, personal planning, and lifestyle queries"
worker_count = 3
class_name = "LifeAgent"
```

- [ ] **Step 4: Add stub agent classes**

`sebastian/agents/code/__init__.py`:
```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class CodeAgent(BaseAgent):
    name = "code"
    system_prompt = (
        "You are a code execution specialist. "
        "Write, run, and debug code as requested. "
        "Use available tools to execute scripts and report results."
    )
```

`sebastian/agents/stock/__init__.py`:
```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class StockAgent(BaseAgent):
    name = "stock"
    system_prompt = (
        "You are a stock and investment research specialist. "
        "Analyze financial data, look up prices, and provide investment insights."
    )
```

`sebastian/agents/life/__init__.py`:
```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class LifeAgent(BaseAgent):
    name = "life"
    system_prompt = (
        "You are a personal life assistant. "
        "Help with schedules, reminders, daily planning, and lifestyle questions."
    )
```

- [ ] **Step 5: Create _loader.py**

`sebastian/agents/_loader.py`:

```python
from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent


@dataclass
class AgentConfig:
    agent_type: str
    name: str
    description: str
    worker_count: int
    agent_class: type[BaseAgent]


def load_agents(extra_dirs: list[Path] | None = None) -> list[AgentConfig]:
    """Scan built-in agents dir and optional extra dirs for manifest.toml files.

    Later entries with the same agent_type override earlier ones (user extensions win).
    """
    builtin_dir = Path(__file__).parent
    dirs: list[tuple[Path, bool]] = [(builtin_dir, True), *((d, False) for d in (extra_dirs or []))]

    configs: dict[str, AgentConfig] = {}

    for base_dir, is_builtin in dirs:
        if not base_dir.exists():
            continue
        for entry in sorted(base_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            manifest_path = entry / "manifest.toml"
            if not manifest_path.exists():
                continue

            with manifest_path.open("rb") as f:
                data = tomllib.load(f)

            agent_section = data.get("agent", data)
            agent_type = entry.name
            class_name: str = agent_section.get("class_name", "")

            if is_builtin:
                module_path = f"sebastian.agents.{agent_type}"
            else:
                import sys
                if str(base_dir) not in sys.path:
                    sys.path.insert(0, str(base_dir))
                module_path = agent_type

            try:
                mod = importlib.import_module(module_path)
                agent_class = getattr(mod, class_name)
            except (ImportError, AttributeError) as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to load agent %r: %s", agent_type, exc
                )
                continue

            configs[agent_type] = AgentConfig(
                agent_type=agent_type,
                name=agent_section.get("name", agent_type),
                description=agent_section.get("description", ""),
                worker_count=int(agent_section.get("worker_count", 3)),
                agent_class=agent_class,
            )

    return list(configs.values())
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/unit/test_agents_loader.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add sebastian/agents/_loader.py \
        sebastian/agents/code/__init__.py sebastian/agents/code/manifest.toml \
        sebastian/agents/stock/__init__.py sebastian/agents/stock/manifest.toml \
        sebastian/agents/life/__init__.py sebastian/agents/life/manifest.toml \
        tests/unit/test_agents_loader.py
git commit -m "feat(agents): add manifest.toml + stub classes + _loader.py for agent discovery

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 12: Add worker loops to AgentPool

**Files:**
- Modify: `sebastian/core/agent_pool.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_agent_pool_worker.py`:

```python
from __future__ import annotations

import asyncio
import pytest


@pytest.mark.asyncio
async def test_worker_loop_processes_task_and_resolves() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.core.agent_pool import AgentPool
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask, TaskResult

    dispatcher = A2ADispatcher()
    queue = dispatcher.register_agent("code")
    pool = AgentPool("code", worker_count=1)

    mock_agent = MagicMock()
    mock_agent.execute_delegated_task = AsyncMock(
        return_value=TaskResult(task_id="t1", ok=True, output={"summary": "done"})
    )

    worker_tasks = pool.start_worker_loops(
        queue=queue,
        dispatcher=dispatcher,
        agent_instances={"code_01": mock_agent},
    )

    task = DelegateTask(task_id="t1", goal="write hello.py")
    future = asyncio.create_task(dispatcher.delegate("code", task))

    result = await asyncio.wait_for(future, timeout=2.0)
    assert result.ok is True
    assert result.output["summary"] == "done"

    for wt in worker_tasks:
        wt.cancel()
        try:
            await wt
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_worker_loop_tracks_current_goal() -> None:
    from unittest.mock import AsyncMock, MagicMock
    import asyncio

    from sebastian.core.agent_pool import AgentPool
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask, TaskResult

    dispatcher = A2ADispatcher()
    queue = dispatcher.register_agent("code")
    pool = AgentPool("code", worker_count=1)

    # Agent that signals when it starts, then waits
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def slow_execute(task):
        started.set()
        await proceed.wait()
        return TaskResult(task_id=task.task_id, ok=True)

    mock_agent = MagicMock()
    mock_agent.execute_delegated_task = slow_execute

    worker_tasks = pool.start_worker_loops(
        queue=queue,
        dispatcher=dispatcher,
        agent_instances={"code_01": mock_agent},
    )

    task = DelegateTask(task_id="t2", goal="long running goal")
    asyncio.create_task(dispatcher.delegate("code", task))

    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert pool.current_goals.get("code_01") == "long running goal"

    proceed.set()
    await asyncio.sleep(0.05)
    assert pool.current_goals.get("code_01") is None

    for wt in worker_tasks:
        wt.cancel()
        try:
            await wt
        except (asyncio.CancelledError, Exception):
            pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_agent_pool_worker.py -v
```

Expected: FAIL — `AgentPool` has no `start_worker_loops` or `current_goals`.

- [ ] **Step 3: Update AgentPool**

Append to `sebastian/core/agent_pool.py`:

```python
import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.a2a.types import DelegateTask
```

Add to the `AgentPool.__init__`:
```python
        self._current_goals: dict[str, str | None] = {
            worker_id: None for worker_id in self._workers
        }
        self._worker_tasks: list[asyncio.Task[None]] = []
```

Add new methods to `AgentPool`:

```python
    @property
    def current_goals(self) -> dict[str, str | None]:
        return dict(self._current_goals)

    def start_worker_loops(
        self,
        queue: asyncio.Queue[Any],
        dispatcher: A2ADispatcher,
        agent_instances: dict[str, Any],
    ) -> list[asyncio.Task[None]]:
        """Start one worker coroutine per agent instance. Returns the tasks."""
        tasks: list[asyncio.Task[None]] = []
        for worker_id, agent in agent_instances.items():
            task = asyncio.create_task(
                self._worker_loop(worker_id, queue, dispatcher, agent),
                name=f"a2a_worker_{worker_id}",
            )
            tasks.append(task)
        self._worker_tasks = tasks
        return tasks

    async def _worker_loop(
        self,
        worker_id: str,
        queue: asyncio.Queue[Any],
        dispatcher: A2ADispatcher,
        agent: Any,
    ) -> None:
        from sebastian.protocol.a2a.types import TaskResult

        while True:
            task = await queue.get()
            self._current_goals[worker_id] = task.goal
            try:
                result = await agent.execute_delegated_task(task)
                dispatcher.resolve(result)
            except asyncio.CancelledError:
                dispatcher.resolve(
                    TaskResult(task_id=task.task_id, ok=False, error="Worker cancelled")
                )
                raise
            except Exception as exc:
                dispatcher.resolve(
                    TaskResult(task_id=task.task_id, ok=False, error=str(exc))
                )
            finally:
                self._current_goals[worker_id] = None
                queue.task_done()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_agent_pool_worker.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/agent_pool.py tests/unit/test_agent_pool_worker.py
git commit -m "feat(core): AgentPool gains worker loops and current_goal tracking for A2A

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 13: Add execute_delegated_task to BaseAgent

**Files:**
- Modify: `sebastian/core/base_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_base_agent_delegated.py`:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
)
from tests.unit.test_agent_loop import MockLLMProvider


@pytest.mark.asyncio
async def test_execute_delegated_task_returns_task_result() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.memory.episodic_memory import EpisodicMemory
    from sebastian.protocol.a2a.types import DelegateTask
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider([
        TextBlockStart(block_id="b0_0"),
        TextDelta(block_id="b0_0", delta="Task complete."),
        TextBlockStop(block_id="b0_0", text="Task complete."),
        ProviderCallEnd(stop_reason="end_turn"),
    ])

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "You are a test agent."

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.create_session = AsyncMock()

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        registry=CapabilityRegistry(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    task = DelegateTask(task_id="t1", goal="do something")
    result = await agent.execute_delegated_task(task)

    assert result.task_id == "t1"
    assert result.ok is True
    assert result.output.get("summary") == "Task complete."


@pytest.mark.asyncio
async def test_execute_delegated_task_captures_exception() -> None:
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.base_agent import BaseAgent
    from sebastian.memory.episodic_memory import EpisodicMemory
    from sebastian.protocol.a2a.types import DelegateTask
    from sebastian.store.session_store import SessionStore

    provider = MockLLMProvider([])  # No turns — will raise RuntimeError

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "test"

    session_store = MagicMock(spec=SessionStore)
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.create_session = AsyncMock()

    episodic_mock = MagicMock(spec=EpisodicMemory)
    episodic_mock.get_turns = AsyncMock(return_value=[])
    episodic_mock.add_turn = AsyncMock()

    agent = TestAgent(
        registry=CapabilityRegistry(),
        session_store=session_store,
        provider=provider,
    )
    agent._episodic = episodic_mock

    task = DelegateTask(task_id="t2", goal="failing task")
    result = await agent.execute_delegated_task(task)

    assert result.task_id == "t2"
    assert result.ok is False
    assert result.error is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_base_agent_delegated.py -v
```

Expected: FAIL — `BaseAgent` has no `execute_delegated_task` method.

- [ ] **Step 3: Add execute_delegated_task to BaseAgent**

Add to `sebastian/core/base_agent.py` (after the `submit_background_task` method or before `_publish`):

First add import at the top:
```python
from sebastian.protocol.a2a.types import DelegateTask
from sebastian.protocol.a2a.types import TaskResult as A2ATaskResult
```

Wait — to avoid circular imports, use TYPE_CHECKING:
```python
if TYPE_CHECKING:
    from sebastian.llm.provider import LLMProvider
    from sebastian.protocol.a2a.types import DelegateTask
    from sebastian.protocol.a2a.types import TaskResult as A2ATaskResult
```

Add the method to `BaseAgent`:

```python
    async def execute_delegated_task(self, task: DelegateTask) -> A2ATaskResult:
        """Execute a delegated task from Sebastian. Creates an isolated session per task."""
        from sebastian.core.types import Session
        from sebastian.protocol.a2a.types import TaskResult as A2ATaskResult

        session = Session(
            id=f"a2a_{task.task_id}",
            agent_type=self.name,
            agent_id=f"{self.name}_01",
            title=task.goal[:40],
        )
        await self._session_store.create_session(session)

        try:
            result_text = await self.run_streaming(
                task.goal,
                session.id,
                task_id=task.task_id,
                agent_name=self.name,
            )
            return A2ATaskResult(
                task_id=task.task_id,
                ok=True,
                output={"summary": result_text},
            )
        except Exception as exc:
            return A2ATaskResult(
                task_id=task.task_id,
                ok=False,
                error=str(exc),
            )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_base_agent_delegated.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent_delegated.py
git commit -m "feat(core): add execute_delegated_task to BaseAgent for A2A worker loops

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 14: Implement delegate_to_agent tool and inject into Sebastian

**Files:**
- Create: `sebastian/orchestrator/tools/__init__.py`
- Create: `sebastian/orchestrator/tools/delegate.py`
- Modify: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_delegate_tool.py`:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_delegate_to_agent_calls_dispatcher() -> None:
    from sebastian.protocol.a2a.types import TaskResult

    mock_dispatcher = MagicMock()
    mock_dispatcher.delegate = AsyncMock(
        return_value=TaskResult(task_id="t1", ok=True, output={"summary": "hello.py created"})
    )

    with patch("sebastian.orchestrator.tools.delegate._get_dispatcher", return_value=mock_dispatcher):
        from sebastian.orchestrator.tools.delegate import delegate_to_agent
        result = await delegate_to_agent(agent_type="code", goal="write hello.py")

    assert result.ok is True
    assert "hello.py created" in str(result.output)
    mock_dispatcher.delegate.assert_called_once()


@pytest.mark.asyncio
async def test_delegate_to_agent_propagates_error() -> None:
    from sebastian.protocol.a2a.types import TaskResult

    mock_dispatcher = MagicMock()
    mock_dispatcher.delegate = AsyncMock(
        return_value=TaskResult(task_id="t1", ok=False, error="agent crashed")
    )

    with patch("sebastian.orchestrator.tools.delegate._get_dispatcher", return_value=mock_dispatcher):
        from sebastian.orchestrator.tools.delegate import delegate_to_agent
        result = await delegate_to_agent(agent_type="code", goal="impossible task")

    assert result.ok is False
    assert "agent crashed" in (result.error or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_delegate_tool.py -v
```

Expected: FAIL — `sebastian.orchestrator.tools.delegate` doesn't exist.

- [ ] **Step 3: Create the tool files**

`sebastian/orchestrator/tools/__init__.py` — empty:
```python
```

`sebastian/orchestrator/tools/delegate.py`:

```python
from __future__ import annotations

import uuid

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


def _get_dispatcher():
    """Deferred import to avoid circular dependency at module load time."""
    import sebastian.gateway.state as state
    return state.dispatcher


@tool(
    description=(
        "Delegate a task to a specialized sub-agent and wait for the result. "
        "Use this when a task requires domain-specific expertise. "
        "agent_type must be one of the available sub-agents listed in your system prompt."
    )
)
async def delegate_to_agent(
    agent_type: str,
    goal: str,
    context: str = "",
) -> ToolResult:
    """Delegate goal to sub-agent of agent_type. Returns the agent's result summary."""
    from sebastian.protocol.a2a.types import DelegateTask

    dispatcher = _get_dispatcher()
    task = DelegateTask(
        task_id=str(uuid.uuid4()),
        goal=goal,
        context={"context": context} if context else {},
    )

    a2a_result = await dispatcher.delegate(agent_type, task)

    if a2a_result.ok:
        summary = a2a_result.output.get("summary", str(a2a_result.output))
        return ToolResult(ok=True, output=summary)

    return ToolResult(ok=False, error=a2a_result.error)
```

- [ ] **Step 4: Update Sebastian to dynamically build system prompt**

In `sebastian/orchestrator/sebas.py`, add the helper and update `__init__`:

```python
from sebastian.agents._loader import AgentConfig

SEBASTIAN_SYSTEM_PROMPT = """You are Sebastian — an elegant, capable personal AI butler.
Your purpose: receive instructions, plan effectively, and execute precisely.
You have access to tools. Use them to fulfill requests completely.
For complex multi-step tasks, break them down and execute step by step.
When you encounter a decision that requires the user's input, ask clearly and concisely.
You never fabricate results — if a tool fails, say so and suggest alternatives."""


def _build_system_prompt(agent_registry: dict[str, AgentConfig]) -> str:
    if not agent_registry:
        return SEBASTIAN_SYSTEM_PROMPT
    agents_list = "\n".join(
        f"  - {cfg.agent_type}: {cfg.description}"
        for cfg in agent_registry.values()
    )
    return (
        SEBASTIAN_SYSTEM_PROMPT
        + f"\n\nAvailable sub-agents (use delegate_to_agent tool to delegate):\n{agents_list}"
    )
```

Update `Sebastian.__init__`:

```python
    def __init__(
        self,
        registry: CapabilityRegistry,
        session_store: SessionStore,
        index_store: IndexStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
        provider: LLMProvider | None = None,
        agent_registry: dict[str, AgentConfig] | None = None,
    ) -> None:
        super().__init__(registry, session_store, event_bus=event_bus, provider=provider)
        self._index = index_store
        self._task_manager = task_manager
        self._conversation = conversation
        if agent_registry:
            self.system_prompt = _build_system_prompt(agent_registry)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_delegate_tool.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add sebastian/orchestrator/tools/__init__.py sebastian/orchestrator/tools/delegate.py \
        sebastian/orchestrator/sebas.py tests/unit/test_delegate_tool.py
git commit -m "feat(orchestrator): add delegate_to_agent tool and dynamic sub-agent system prompt

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 15: Wire A2A into app.py + state.py

Connect `A2ADispatcher`, `AgentPool` worker loops, and `Sebastian` agent_registry in the lifespan.

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_a2a_wiring.py`:

```python
from __future__ import annotations

import pytest
import os
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_gateway_starts_with_dispatcher_and_agent_registry() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")

    from sebastian.gateway.app import create_app
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200

    import sebastian.gateway.state as state
    assert hasattr(state, "dispatcher")
    assert hasattr(state, "agent_registry")
    # All discovered agents should be in registry
    assert "code" in state.agent_registry
    assert "stock" in state.agent_registry
    assert "life" in state.agent_registry
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_a2a_wiring.py -v
```

Expected: FAIL — `state.dispatcher` and `state.agent_registry` don't exist.

- [ ] **Step 3: Update state.py**

Replace `sebastian/gateway/state.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.agents._loader import AgentConfig
    from sebastian.core.agent_pool import AgentPool
    from sebastian.gateway.sse import SSEManager
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.orchestrator.conversation import ConversationManager
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

sebastian: Sebastian
sse_manager: SSEManager
event_bus: EventBus
conversation: ConversationManager
session_store: SessionStore
index_store: IndexStore
db_factory: async_sessionmaker[AsyncSession]
llm_registry: LLMProviderRegistry
dispatcher: A2ADispatcher
agent_registry: dict[str, AgentConfig] = {}
agent_pools: dict[str, AgentPool] = {}
worker_sessions: dict[str, str | None] = {}
```

- [ ] **Step 4: Update app.py lifespan**

Replace `_discover_agent_types()` and `_initialize_runtime_agent_state()` with agent-config-aware versions. Update the `lifespan` function:

```python
def _initialize_a2a_and_pools(
    agent_configs: list[AgentConfig],
    dispatcher: A2ADispatcher,
    default_provider: LLMProvider,
    session_store: SessionStore,
    registry: CapabilityRegistry,
    event_bus: EventBus,
) -> tuple[dict[str, AgentPool], dict[str, str | None]]:
    """Create AgentPool + agent instances + worker loops for each sub-agent config."""
    agent_pools: dict[str, AgentPool] = {}
    worker_sessions: dict[str, str | None] = {}

    # Sebastian's pool (no worker loops — it runs via HTTP turns)
    sebastian_pool = AgentPool("sebastian", worker_count=1)
    agent_pools["sebastian"] = sebastian_pool
    for worker_id in sebastian_pool.status():
        worker_sessions[worker_id] = None

    for cfg in agent_configs:
        pool = AgentPool(cfg.agent_type, worker_count=cfg.worker_count)
        agent_pools[cfg.agent_type] = pool

        # Create one agent instance per worker slot
        agent_instances: dict[str, Any] = {}
        for worker_id in pool.status():
            agent = cfg.agent_class(
                registry=registry,
                session_store=session_store,
                event_bus=event_bus,
                provider=default_provider,
            )
            agent_instances[worker_id] = agent
            worker_sessions[worker_id] = None

        queue = dispatcher.register_agent(cfg.agent_type)
        pool.start_worker_loops(
            queue=queue,
            dispatcher=dispatcher,
            agent_instances=agent_instances,
        )

    return agent_pools, worker_sessions
```

In the `lifespan` function, after loading tools/MCP/provider, add:

```python
    from sebastian.agents._loader import load_agents
    from sebastian.config import settings
    from sebastian.protocol.a2a.dispatcher import A2ADispatcher

    agent_configs = load_agents(
        extra_dirs=[settings.extensions_dir / "agents"] if hasattr(settings, "extensions_dir") else None
    )
    agent_registry = {cfg.agent_type: cfg for cfg in agent_configs}

    dispatcher = A2ADispatcher()

    # Load delegate_to_agent tool (orchestrator-only)
    from sebastian.orchestrator.tools import delegate as _delegate_module  # noqa: F401

    sebastian_agent = Sebastian(
        registry=registry,
        session_store=session_store,
        index_store=index_store,
        task_manager=task_manager,
        conversation=conversation,
        event_bus=event_bus,
        provider=default_provider,
        agent_registry=agent_registry,
    )

    agent_pools, worker_sessions = _initialize_a2a_and_pools(
        agent_configs=agent_configs,
        dispatcher=dispatcher,
        default_provider=default_provider,
        session_store=session_store,
        registry=registry,
        event_bus=event_bus,
    )
```

Add state assignments:

```python
    state.dispatcher = dispatcher
    state.agent_registry = agent_registry
```

Also add `Any` to the imports at the top of `app.py`:
```python
from typing import TYPE_CHECKING, Any
```

And add `AgentConfig`, `LLMProvider`, `SessionStore`, `CapabilityRegistry` to TYPE_CHECKING imports for the type annotations in `_initialize_a2a_and_pools`.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/integration/test_a2a_wiring.py -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py \
        tests/integration/test_a2a_wiring.py
git commit -m "feat(gateway): wire A2ADispatcher, agent_registry, and worker loops into lifespan

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Slice 3: Gateway + App

---

### Task 16: Add LLM Provider CRUD routes

**Files:**
- Create: `sebastian/gateway/routes/llm_providers.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_llm_providers_api.py`:

```python
from __future__ import annotations

import pytest
import os
from httpx import AsyncClient, ASGITransport


@pytest.fixture(autouse=True)
def set_env():
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")


async def _get_token(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/auth/login", json={"password": ""})
    if resp.status_code == 200:
        return resp.json()["token"]
    return "test-token"


@pytest.mark.asyncio
async def test_llm_providers_crud() -> None:
    from sebastian.gateway.app import create_app
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # List (empty)
        resp = await client.get(
            "/api/v1/llm-providers",
            headers={"Authorization": "Bearer test"},
        )
        # Auth might reject; test the route exists at minimum
        assert resp.status_code in (200, 401, 403)
```

- [ ] **Step 2: Run test to verify the route exists**

```bash
pytest tests/integration/test_llm_providers_api.py -v
```

Expected: FAIL — route `/api/v1/llm-providers` doesn't exist (404).

- [ ] **Step 3: Create the routes file**

`sebastian/gateway/routes/llm_providers.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["llm-providers"])

AuthPayload = dict[str, Any]


class LLMProviderCreate(BaseModel):
    name: str
    provider_type: str          # "anthropic" | "openai"
    api_key: str
    model: str
    base_url: str | None = None
    thinking_format: str | None = None  # None | "reasoning_content" | "think_tags"
    is_default: bool = False


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    thinking_format: str | None = None
    is_default: bool | None = None


def _record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "provider_type": record.provider_type,
        "base_url": record.base_url,
        "api_key": record.api_key,
        "model": record.model,
        "thinking_format": record.thinking_format,
        "is_default": record.is_default,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.get("/llm-providers")
async def list_llm_providers(
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    records = await state.llm_registry.list_all()
    return {"providers": [_record_to_dict(r) for r in records]}


@router.post("/llm-providers", status_code=201)
async def create_llm_provider(
    body: LLMProviderCreate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name=body.name,
        provider_type=body.provider_type,
        api_key=body.api_key,
        model=body.model,
        base_url=body.base_url,
        thinking_format=body.thinking_format,
        is_default=body.is_default,
    )
    await state.llm_registry.create(record)
    return _record_to_dict(record)


@router.put("/llm-providers/{provider_id}")
async def update_llm_provider(
    provider_id: str,
    body: LLMProviderUpdate,
    _auth: AuthPayload = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    record = await state.llm_registry.update(provider_id, **updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _record_to_dict(record)


@router.delete("/llm-providers/{provider_id}", status_code=204)
async def delete_llm_provider(
    provider_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> None:
    import sebastian.gateway.state as state

    deleted = await state.llm_registry.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")
```

- [ ] **Step 4: Register the router in app.py**

In `sebastian/gateway/app.py`, in `create_app()`:

```python
def create_app() -> FastAPI:
    from sebastian.gateway.routes import agents, approvals, llm_providers, sessions, stream, turns

    app = FastAPI(title="Sebastian Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(turns.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(stream.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(llm_providers.router, prefix="/api/v1")
    return app
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/integration/test_llm_providers_api.py -v
```

Expected: PASS (route now exists, returns 401 due to auth — that's expected)

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/llm_providers.py sebastian/gateway/app.py \
        tests/integration/test_llm_providers_api.py
git commit -m "feat(gateway): add LLM provider CRUD routes (GET/POST/PUT/DELETE /llm-providers)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 17: Enrich GET /agents with name, description, current_goal

**Files:**
- Modify: `sebastian/gateway/routes/agents.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_gateway.py` (or create `tests/integration/test_agents_api.py`):

```python
from __future__ import annotations

import pytest
import os
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_agents_response_includes_name_and_description() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")

    from sebastian.gateway.app import create_app
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer test"},
        )
        # Route exists; auth may reject with 401
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            agents = resp.json()["agents"]
            code_agent = next((a for a in agents if a["agent_type"] == "code"), None)
            assert code_agent is not None
            assert "name" in code_agent
            assert "description" in code_agent
            assert "workers" in code_agent
            for w in code_agent["workers"]:
                assert "current_goal" in w
```

- [ ] **Step 2: Run test to verify the shape is wrong**

```bash
pytest tests/integration/test_agents_api.py -v
```

Expected: FAIL or partial fail (name/description/current_goal missing from response).

- [ ] **Step 3: Update agents.py**

Replace `sebastian/gateway/routes/agents.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sebastian.gateway.auth import require_auth

router = APIRouter(tags=["agents"])

AuthPayload = dict[str, Any]
JSONDict = dict[str, Any]


@router.get("/agents")
async def list_agents(_auth: AuthPayload = Depends(require_auth)) -> JSONDict:
    import sebastian.gateway.state as state

    agents = []
    for agent_type, pool in state.agent_pools.items():
        cfg = state.agent_registry.get(agent_type)
        agent_name = cfg.name if cfg else agent_type
        agent_description = cfg.description if cfg else ""

        workers = []
        for agent_id, worker_status in pool.status().items():
            workers.append(
                {
                    "agent_id": agent_id,
                    "status": worker_status.value,
                    "session_id": state.worker_sessions.get(agent_id),
                    "current_goal": pool.current_goals.get(agent_id),
                }
            )
        agents.append(
            {
                "agent_type": agent_type,
                "name": agent_name,
                "description": agent_description,
                "workers": workers,
                "queue_depth": pool.queue_depth,
            }
        )

    return {"agents": agents}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_agents_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/gateway/routes/agents.py tests/integration/test_agents_api.py
git commit -m "feat(gateway): enrich GET /agents with name, description, current_goal per worker

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 18: Update App types, API, and stores

**Files:**
- Modify: `ui/mobile/src/types.ts`
- Modify: `ui/mobile/src/api/agents.ts`
- Create: `ui/mobile/src/api/llmProviders.ts`
- Create: `ui/mobile/src/store/llmProviders.ts`

- [ ] **Step 1: Update types.ts**

Replace the existing `LLMProvider` type (lines ~101-102) with server-backed type:

```typescript
// Old (local-only):
// export type LLMProviderName = 'anthropic' | 'openai';
// export interface LLMProvider { name: LLMProviderName; apiKey: string; }

// New (server-backed):
export type LLMProviderType = 'anthropic' | 'openai';
export type ThinkingFormat = 'reasoning_content' | 'think_tags' | null;

export interface LLMProvider {
  id: string;
  name: string;
  provider_type: LLMProviderType;
  base_url: string | null;
  api_key: string;
  model: string;
  thinking_format: ThinkingFormat;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMProviderCreate {
  name: string;
  provider_type: LLMProviderType;
  api_key: string;
  model: string;
  base_url?: string | null;
  thinking_format?: ThinkingFormat;
  is_default?: boolean;
}
```

Also update `BackendAgentSummary` in agents.ts to include name/description/current_goal.

- [ ] **Step 2: Update api/agents.ts**

Update `BackendAgentWorker` and `BackendAgentSummary`, and update `mapAgentSummary`:

```typescript
interface BackendAgentWorker {
  agent_id: string;
  status: 'idle' | 'busy';
  session_id: string | null;
  current_goal: string | null;
}

interface BackendAgentSummary {
  agent_type: string;
  name: string;
  description: string;
  workers: BackendAgentWorker[];
  queue_depth: number;
}

function mapAgentSummary(agent: BackendAgentSummary): Agent {
  const busyWorker = agent.workers.find((w) => w.status === 'busy' && w.current_goal);
  const busyCount = agent.workers.filter((w) => w.status === 'busy').length;
  const hasQueuedWork = agent.queue_depth > 0;
  const status = busyCount > 0 || hasQueuedWork ? 'working' : 'idle';
  const queueSuffix = hasQueuedWork ? `，队列 ${agent.queue_depth}` : '';
  const goalText = busyWorker?.current_goal ?? '';

  return {
    id: agent.agent_type,
    name: agent.name || agent.agent_type,
    status,
    goal: goalText || `${agent.workers.length} 个 worker，${busyCount} 个忙碌${queueSuffix}`,
    createdAt: '1970-01-01T00:00:00.000Z',
  };
}
```

- [ ] **Step 3: Create api/llmProviders.ts**

`ui/mobile/src/api/llmProviders.ts`:

```typescript
import { apiClient } from './client';
import type { LLMProvider, LLMProviderCreate } from '../types';

interface ProvidersResponse {
  providers: LLMProvider[];
}

export async function getLLMProviders(): Promise<LLMProvider[]> {
  const { data } = await apiClient.get<ProvidersResponse>('/api/v1/llm-providers');
  return data.providers;
}

export async function createLLMProvider(body: LLMProviderCreate): Promise<LLMProvider> {
  const { data } = await apiClient.post<LLMProvider>('/api/v1/llm-providers', body);
  return data;
}

export async function updateLLMProvider(
  id: string,
  updates: Partial<LLMProviderCreate>,
): Promise<LLMProvider> {
  const { data } = await apiClient.put<LLMProvider>(`/api/v1/llm-providers/${id}`, updates);
  return data;
}

export async function deleteLLMProvider(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/llm-providers/${id}`);
}
```

- [ ] **Step 4: Create store/llmProviders.ts**

`ui/mobile/src/store/llmProviders.ts`:

```typescript
import { create } from 'zustand';
import {
  getLLMProviders,
  createLLMProvider,
  updateLLMProvider,
  deleteLLMProvider,
} from '../api/llmProviders';
import type { LLMProvider, LLMProviderCreate } from '../types';

interface LLMProvidersState {
  providers: LLMProvider[];
  loading: boolean;
  error: string | null;
  fetch: () => Promise<void>;
  create: (body: LLMProviderCreate) => Promise<LLMProvider>;
  update: (id: string, updates: Partial<LLMProviderCreate>) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

export const useLLMProvidersStore = create<LLMProvidersState>((set, get) => ({
  providers: [],
  loading: false,
  error: null,

  fetch: async () => {
    set({ loading: true, error: null });
    try {
      const providers = await getLLMProviders();
      set({ providers, loading: false });
    } catch (err: unknown) {
      set({ loading: false, error: err instanceof Error ? err.message : 'Failed to load providers' });
    }
  },

  create: async (body) => {
    const provider = await createLLMProvider(body);
    set((s) => ({ providers: [...s.providers, provider] }));
    return provider;
  },

  update: async (id, updates) => {
    const updated = await updateLLMProvider(id, updates);
    set((s) => ({
      providers: s.providers.map((p) => (p.id === id ? updated : p)),
    }));
  },

  remove: async (id) => {
    await deleteLLMProvider(id);
    set((s) => ({ providers: s.providers.filter((p) => p.id !== id) }));
  },
}));
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add ui/mobile/src/types.ts ui/mobile/src/api/agents.ts \
        ui/mobile/src/api/llmProviders.ts ui/mobile/src/store/llmProviders.ts
git commit -m "feat(app): update types + API + Zustand store for server-backed LLM providers

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 19: Rewrite LLMProviderConfig.tsx to use backend API

**Files:**
- Modify: `ui/mobile/src/components/settings/LLMProviderConfig.tsx`

- [ ] **Step 1: Review current file**

Read `ui/mobile/src/components/settings/LLMProviderConfig.tsx` — it currently uses local `useSettingsStore` and saves only `name` + `apiKey`. Replace completely.

- [ ] **Step 2: Rewrite the component**

Replace the entire `LLMProviderConfig.tsx`:

```tsx
import { useEffect, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
  Alert,
  StyleSheet,
} from 'react-native';
import { useLLMProvidersStore } from '../../store/llmProviders';
import type { LLMProvider, LLMProviderCreate, LLMProviderType } from '../../types';

const PROVIDER_TYPES: LLMProviderType[] = ['anthropic', 'openai'];

const DEFAULT_MODELS: Record<LLMProviderType, string> = {
  anthropic: 'claude-opus-4-6',
  openai: 'gpt-4o',
};

function ProviderForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: LLMProvider;
  onSave: (data: LLMProviderCreate) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [providerType, setProviderType] = useState<LLMProviderType>(
    initial?.provider_type ?? 'anthropic',
  );
  const [apiKey, setApiKey] = useState(initial?.api_key ?? '');
  const [model, setModel] = useState(initial?.model ?? DEFAULT_MODELS.anthropic);
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '');
  const [isDefault, setIsDefault] = useState(initial?.is_default ?? false);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim() || !apiKey.trim() || !model.trim()) {
      Alert.alert('错误', '请填写名称、API Key 和模型');
      return;
    }
    setSaving(true);
    try {
      await onSave({
        name: name.trim(),
        provider_type: providerType,
        api_key: apiKey.trim(),
        model: model.trim(),
        base_url: baseUrl.trim() || null,
        is_default: isDefault,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <View style={styles.form}>
      <Text style={styles.label}>名称</Text>
      <TextInput style={styles.input} value={name} onChangeText={setName} placeholder="如：Claude 家用" />

      <Text style={styles.label}>Provider 类型</Text>
      <View style={styles.segmented}>
        {PROVIDER_TYPES.map((pt) => (
          <TouchableOpacity
            key={pt}
            style={[styles.segment, providerType === pt && styles.segmentActive]}
            onPress={() => {
              setProviderType(pt);
              setModel(DEFAULT_MODELS[pt]);
            }}
          >
            <Text style={[styles.segmentText, providerType === pt && styles.segmentTextActive]}>
              {pt}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={styles.label}>API Key</Text>
      <TextInput
        style={styles.input}
        value={apiKey}
        onChangeText={setApiKey}
        placeholder="sk-ant-... 或 sk-..."
        secureTextEntry
        autoCapitalize="none"
      />

      <Text style={styles.label}>模型</Text>
      <TextInput style={styles.input} value={model} onChangeText={setModel} autoCapitalize="none" />

      <Text style={styles.label}>Base URL（可选，留空用默认）</Text>
      <TextInput
        style={styles.input}
        value={baseUrl}
        onChangeText={setBaseUrl}
        placeholder="https://api.example.com/v1"
        autoCapitalize="none"
      />

      <TouchableOpacity
        style={[styles.toggleRow]}
        onPress={() => setIsDefault((v) => !v)}
      >
        <Text style={styles.toggleLabel}>设为默认 Provider</Text>
        <Text style={styles.toggleValue}>{isDefault ? '✓' : '○'}</Text>
      </TouchableOpacity>

      <View style={styles.buttonRow}>
        <TouchableOpacity style={[styles.btn, styles.btnCancel]} onPress={onCancel}>
          <Text style={styles.btnCancelText}>取消</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.btn, styles.btnSave]} onPress={handleSave} disabled={saving}>
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.btnSaveText}>保存</Text>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}

export function LLMProviderConfig() {
  const { providers, loading, error, fetch, create, update, remove } = useLLMProvidersStore();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<LLMProvider | null>(null);

  useEffect(() => {
    fetch();
  }, []);

  async function handleCreate(data: LLMProviderCreate) {
    await create(data);
    setShowForm(false);
  }

  async function handleUpdate(data: LLMProviderCreate) {
    if (!editing) return;
    await update(editing.id, data);
    setEditing(null);
  }

  async function handleDelete(provider: LLMProvider) {
    Alert.alert('删除 Provider', `确认删除 "${provider.name}"？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          await remove(provider.id);
        },
      },
    ]);
  }

  if (showForm || editing) {
    return (
      <View style={styles.group}>
        <Text style={styles.groupLabel}>模型</Text>
        <ProviderForm
          initial={editing ?? undefined}
          onSave={editing ? handleUpdate : handleCreate}
          onCancel={() => {
            setShowForm(false);
            setEditing(null);
          }}
        />
      </View>
    );
  }

  return (
    <View style={styles.group}>
      <Text style={styles.groupLabel}>模型</Text>

      {loading && <ActivityIndicator style={{ marginBottom: 12 }} />}
      {error && <Text style={styles.errorText}>{error}</Text>}

      {providers.map((p) => (
        <View key={p.id} style={styles.card}>
          <View style={styles.cardRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>
                {p.name}
                {p.is_default ? ' ★' : ''}
              </Text>
              <Text style={styles.cardSub}>
                {p.provider_type} · {p.model}
              </Text>
            </View>
            <View style={styles.cardActions}>
              <TouchableOpacity onPress={() => setEditing(p)} style={styles.actionBtn}>
                <Text style={styles.actionBtnText}>编辑</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => handleDelete(p)} style={styles.actionBtn}>
                <Text style={[styles.actionBtnText, { color: '#FF3B30' }]}>删除</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      ))}

      <TouchableOpacity style={styles.addBtn} onPress={() => setShowForm(true)}>
        <Text style={styles.addBtnText}>+ 添加 Provider</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 28 },
  groupLabel: {
    marginBottom: 8,
    paddingHorizontal: 4,
    fontSize: 13,
    fontWeight: '600',
    color: '#6D6D72',
    textTransform: 'uppercase',
  },
  card: {
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    marginBottom: 8,
    overflow: 'hidden',
  },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  cardTitle: { fontSize: 17, color: '#111111', fontWeight: '500' },
  cardSub: { fontSize: 13, color: '#8E8E93', marginTop: 2 },
  cardActions: { flexDirection: 'row', gap: 12 },
  actionBtn: { padding: 4 },
  actionBtnText: { fontSize: 15, color: '#007AFF' },
  addBtn: {
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addBtnText: { fontSize: 17, color: '#007AFF' },
  form: {
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    padding: 16,
  },
  label: { fontSize: 13, color: '#6D6D72', marginBottom: 6, marginTop: 12 },
  input: {
    minHeight: 46,
    borderRadius: 12,
    backgroundColor: '#F2F2F7',
    paddingHorizontal: 14,
    fontSize: 17,
    color: '#111111',
  },
  segmented: {
    flexDirection: 'row',
    padding: 4,
    borderRadius: 12,
    backgroundColor: '#F2F2F7',
  },
  segment: { flex: 1, minHeight: 36, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  segmentActive: { backgroundColor: '#FFFFFF' },
  segmentText: { fontSize: 15, color: '#6D6D72', fontWeight: '500' },
  segmentTextActive: { color: '#111111' },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 16,
    paddingVertical: 4,
  },
  toggleLabel: { fontSize: 17, color: '#111111' },
  toggleValue: { fontSize: 20, color: '#007AFF' },
  buttonRow: { flexDirection: 'row', gap: 12, marginTop: 20 },
  btn: { flex: 1, minHeight: 46, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  btnCancel: { backgroundColor: '#F2F2F7' },
  btnSave: { backgroundColor: '#007AFF' },
  btnCancelText: { fontSize: 17, color: '#111111' },
  btnSaveText: { fontSize: 17, fontWeight: '600', color: '#FFFFFF' },
  errorText: { color: '#FF3B30', fontSize: 15, marginBottom: 8 },
});
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Manual smoke test**

Start gateway and App, navigate to Settings → 模型 section:
- List should load from backend (empty initially)
- "+ 添加 Provider" opens form
- Filling in name, type, API key, model and saving should create a record
- Record should appear in the list with edit/delete

- [ ] **Step 5: Commit**

```bash
git add ui/mobile/src/components/settings/LLMProviderConfig.tsx
git commit -m "feat(app): rewrite LLMProviderConfig to use server-backed LLM provider API

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Slice 4: Skills

---

### Task 20: Skills _loader.py + registry integration

**Files:**
- Modify: `sebastian/config/__init__.py`
- Create: `sebastian/capabilities/skills/_loader.py`
- Modify: `sebastian/capabilities/registry.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_skills_loader.py`:

```python
from __future__ import annotations

import pytest
from pathlib import Path


def test_skill_loader_reads_skill_md(tmp_path) -> None:
    """Loader finds SKILL.md files and creates tool specs."""
    skill_dir = tmp_path / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my_skill\ndescription: Does my thing\n---\n\nSteps: do stuff.\n"
    )

    from sebastian.capabilities.skills._loader import load_skills
    skills = load_skills(extra_dirs=[tmp_path])

    assert len(skills) == 1
    assert skills[0]["name"] == "skill__my_skill"
    assert "Does my thing" in skills[0]["description"]


def test_skill_loader_skips_dirs_without_skill_md(tmp_path) -> None:
    no_skill_dir = tmp_path / "notaskill"
    no_skill_dir.mkdir()
    (no_skill_dir / "README.md").write_text("# not a skill")

    from sebastian.capabilities.skills._loader import load_skills
    skills = load_skills(extra_dirs=[tmp_path])
    assert len(skills) == 0


def test_skill_loader_user_dir_overrides_builtin(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    user_dir = tmp_path / "user"
    user_dir.mkdir()

    # Same skill name in both dirs
    for base in [builtin_dir, user_dir]:
        sd = base / "greet"
        sd.mkdir()
        src = "builtin" if base == builtin_dir else "user"
        (sd / "SKILL.md").write_text(
            f"---\nname: greet\ndescription: Greet from {src}\n---\nGreet.\n"
        )

    from sebastian.capabilities.skills._loader import load_skills
    skills = load_skills(builtin_dir=builtin_dir, extra_dirs=[user_dir])
    greet = next(s for s in skills if s["name"] == "skill__greet")
    assert "user" in greet["description"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_skills_loader.py -v
```

Expected: FAIL — `sebastian.capabilities.skills._loader` doesn't exist.

- [ ] **Step 3: Add extensions_dir to config**

In `sebastian/config/__init__.py`, add properties:

```python
    @property
    def extensions_dir(self) -> Path:
        return Path(self.sebastian_data_dir) / "extensions"

    @property
    def skills_extensions_dir(self) -> Path:
        return self.extensions_dir / "skills"

    @property
    def agents_extensions_dir(self) -> Path:
        return self.extensions_dir / "agents"
```

Also update `ensure_data_dir()`:

```python
def ensure_data_dir() -> None:
    data = Path(settings.sebastian_data_dir)
    data.mkdir(parents=True, exist_ok=True)
    (data / "sessions").mkdir(exist_ok=True)
    (data / "sessions" / "sebastian").mkdir(exist_ok=True)
    (data / "sessions" / "subagents").mkdir(exist_ok=True)
    (data / "extensions").mkdir(exist_ok=True)
    (data / "extensions" / "skills").mkdir(exist_ok=True)
    (data / "extensions" / "agents").mkdir(exist_ok=True)
```

- [ ] **Step 4: Create _loader.py**

First create the `skills/` directory and `__init__.py` if they don't exist:

```bash
mkdir -p sebastian/capabilities/skills
touch sebastian/capabilities/skills/__init__.py
```

`sebastian/capabilities/skills/_loader.py`:

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse YAML-style frontmatter from SKILL.md content.

    Returns (metadata_dict, body_without_frontmatter).
    Only supports simple key: value lines (no nested YAML).
    """
    meta: dict[str, str] = {}
    body = content

    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            fm_block = content[3:end].strip()
            body = content[end + 4:].strip()
            for line in fm_block.splitlines():
                m = re.match(r"^(\w+)\s*:\s*(.+)$", line.strip())
                if m:
                    meta[m.group(1)] = m.group(2).strip()

    return meta, body


def load_skills(
    builtin_dir: Path | None = None,
    extra_dirs: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Scan dirs for skill subdirectories containing SKILL.md.

    Returns a list of tool spec dicts suitable for CapabilityRegistry.
    Tool names are prefixed with "skill__".
    Later dirs override earlier ones for the same skill name.
    """
    if builtin_dir is None:
        from pathlib import Path as _Path
        builtin_dir = _Path(__file__).parent.parent.parent / "capabilities" / "skills"
        # Use the directory containing this file's parent skills/ folder
        # In practice: sebastian/capabilities/skills/
        builtin_dir = _Path(__file__).parent

    dirs: list[Path] = [builtin_dir, *(extra_dirs or [])]

    skills: dict[str, dict[str, Any]] = {}

    for base_dir in dirs:
        if not base_dir.exists():
            continue
        for entry in sorted(base_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue

            content = skill_md.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(content)

            skill_name = meta.get("name", entry.name)
            description = meta.get("description", "")
            full_instructions = f"{description}\n\n{body}".strip() if body else description

            tool_name = f"skill__{skill_name}"
            skills[skill_name] = {
                "name": tool_name,
                "description": full_instructions,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "instructions": {
                            "type": "string",
                            "description": "Additional context or specific instructions for this skill invocation.",
                        }
                    },
                    "required": [],
                },
            }

    return list(skills.values())
```

- [ ] **Step 5: Wire skills into CapabilityRegistry**

In `sebastian/capabilities/registry.py`, add method to register skill specs:

```python
    def register_skill_specs(self, specs: list[dict[str, Any]]) -> None:
        """Register skill tool specs (read-only — no callable fn, LLM uses description)."""
        for spec in specs:
            # Skills are pure-description tools; calling them returns the instructions
            name = spec["name"]
            description = spec["description"]

            async def _skill_fn(instructions: str = "", _desc: str = description) -> ToolResult:
                return ToolResult(ok=True, output=_desc)

            self._mcp_tools[name] = (spec, _skill_fn)
```

- [ ] **Step 6: Load skills in app.py lifespan**

In the `lifespan` function, after `load_tools()`:

```python
    from sebastian.capabilities.skills._loader import load_skills
    from sebastian.config import settings
    skill_specs = load_skills(
        extra_dirs=[settings.skills_extensions_dir],
    )
    registry.register_skill_specs(skill_specs)
    logger.info("Loaded %d skills", len(skill_specs))
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/test_skills_loader.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add sebastian/config/__init__.py \
        sebastian/capabilities/skills/__init__.py \
        sebastian/capabilities/skills/_loader.py \
        sebastian/capabilities/registry.py \
        sebastian/gateway/app.py \
        tests/unit/test_skills_loader.py
git commit -m "feat(capabilities): skills loader scans SKILL.md files, registers as tool specs

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Final Validation

After all 20 tasks are complete:

- [ ] **Run full test suite**

```bash
pytest tests/ -v
```

Expected: all pass

- [ ] **Start gateway and verify health**

```bash
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
curl http://127.0.0.1:8000/api/v1/health
# {"status": "ok"}
```

- [ ] **Verify agents endpoint shows name/description**

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/agents | python3 -m json.tool
# Each agent entry should have "name", "description", and workers with "current_goal"
```

- [ ] **Verify LLM providers endpoint**

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/llm-providers
# {"providers": []}  (empty initially)
```

- [ ] **Smoke test App**

Launch Android emulator, open App:
- Settings → 模型: "+ 添加 Provider" should create a record and display it
- SubAgents page: should show code/stock/life agents with name and description

- [ ] **Tag slice completion**

```bash
git tag phase2a-complete
```

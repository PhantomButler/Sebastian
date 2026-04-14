# Thinking Effort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通输入框的"思考"开关到 LLM 请求的完整链路，支持 Anthropic Adaptive / Anthropic Extended / OpenAI reasoning_effort / 第三方布尔 toggle 四种形态，并修复多轮 thinking signature 缺失。

**Architecture:** 在 `LLMProviderRecord` 上新增 `thinking_capability` 字段（none/toggle/effort/adaptive/always_on）作为 Provider 请求能力的建模；每个 Provider 实现持有一份 effort→SDK 参数的常量表；前端根据当前默认 Provider 的 capability 动态渲染档位 UI；`thinking_effort` 按 per-turn 字段从 gateway 透传到 Provider。

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy async + Anthropic/OpenAI SDK（后端），React Native + Expo Router + Zustand（前端）

**Spec:** [docs/superpowers/specs/2026-04-08-thinking-effort-design.md](../specs/2026-04-08-thinking-effort-design.md)

---

## Task 1: DB schema — 新增 `thinking_capability` 字段

**Files:**
- Modify: `sebastian/store/models.py:72-87`
- Test: `tests/unit/test_llm_provider.py`（新增一个字段存在性测试）

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_llm_provider.py` 尾部追加：

```python
def test_llm_provider_record_has_thinking_capability_field() -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="test",
        provider_type="anthropic",
        api_key_enc="fake",
        model="claude-opus-4-6",
        thinking_capability="adaptive",
    )
    assert record.thinking_capability == "adaptive"

    record2 = LLMProviderRecord(
        name="test2",
        provider_type="openai",
        api_key_enc="fake",
        model="gpt-4o",
    )
    assert record2.thinking_capability is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_llm_provider.py::test_llm_provider_record_has_thinking_capability_field -v
```

Expected: FAIL — `TypeError: 'thinking_capability' is an invalid keyword argument`

- [ ] **Step 3: 加字段**

在 `sebastian/store/models.py` 的 `LLMProviderRecord` 中 `thinking_format` 下方加一行：

```python
thinking_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
thinking_capability: Mapped[str | None] = mapped_column(String(20), nullable=True)
is_default: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_llm_provider.py::test_llm_provider_record_has_thinking_capability_field -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/store/models.py tests/unit/test_llm_provider.py
git commit -m "feat(store): LLMProviderRecord 新增 thinking_capability 字段"
```

---

## Task 2: stream_events — `ThinkingBlockStop` 增加 `signature` 字段

**Files:**
- Modify: `sebastian/core/stream_events.py`
- Test: `tests/unit/test_llm_provider.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_llm_provider.py` 尾部追加：

```python
def test_thinking_block_stop_has_signature_field() -> None:
    from sebastian.core.stream_events import ThinkingBlockStop

    ev = ThinkingBlockStop(block_id="b0_0", thinking="thought", signature="sig_abc")
    assert ev.signature == "sig_abc"

    ev2 = ThinkingBlockStop(block_id="b0_0", thinking="thought")
    assert ev2.signature is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_llm_provider.py::test_thinking_block_stop_has_signature_field -v
```

Expected: FAIL — `TypeError: ThinkingBlockStop.__init__() got an unexpected keyword argument 'signature'`

- [ ] **Step 3: 加字段**

在 `sebastian/core/stream_events.py` 的 `ThinkingBlockStop` dataclass 上加字段（必须有默认值以免破坏现有位置参数调用）：

```python
@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str
    signature: str | None = None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_llm_provider.py::test_thinking_block_stop_has_signature_field -v
```

Expected: PASS

- [ ] **Step 5: 跑完整 llm provider 相关测试确认没回归**

```bash
pytest tests/unit/test_llm_provider.py tests/unit/test_agent_loop.py -v
```

Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add sebastian/core/stream_events.py tests/unit/test_llm_provider.py
git commit -m "feat(core): ThinkingBlockStop 增加 signature 字段"
```

---

## Task 3: `LLMProvider` 抽象签名 —— 加 `thinking_effort` 参数

**Files:**
- Modify: `sebastian/llm/provider.py:23-40`
- Test: `tests/unit/test_llm_provider.py:13-34`

- [ ] **Step 1: 改现有测试的 ConcreteProvider**

把 `test_llm_provider_stream_signature_accepted_by_subclass` 中的签名改为：

```python
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
        thinking_effort: str | None = None,
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        return
        yield
```

- [ ] **Step 2: 修改抽象基类**

在 `sebastian/llm/provider.py` 的 `stream` 签名末尾加 `thinking_effort: str | None = None`：

```python
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
    thinking_effort: str | None = None,
) -> AsyncGenerator[LLMStreamEvent, None]:
    """...
    thinking_effort: one of 'off' | 'on' | 'low' | 'medium' | 'high' | 'max' | None.
    Each Provider interprets according to its thinking_capability; providers with
    capability 'none' or 'always_on' ignore this parameter.
    """
    ...
    yield
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/unit/test_llm_provider.py -v
```

Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add sebastian/llm/provider.py tests/unit/test_llm_provider.py
git commit -m "feat(llm): LLMProvider.stream 增加 thinking_effort 参数"
```

---

## Task 4: `AnthropicProvider` —— capability 常量表 + signature 传出

**Files:**
- Modify: `sebastian/llm/anthropic.py`
- Test: `tests/unit/test_anthropic_thinking.py`（新建）

- [ ] **Step 1: 写 adaptive capability 的失败测试**

新建 `tests/unit/test_anthropic_thinking.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _build_stream_mock() -> MagicMock:
    """Build a minimal mock stream that yields one thinking block with signature."""
    raw_start = MagicMock()
    raw_start.type = "content_block_start"
    raw_start.index = 0
    raw_start.content_block.type = "thinking"

    raw_delta = MagicMock()
    raw_delta.type = "content_block_delta"
    raw_delta.index = 0
    raw_delta.delta.type = "thinking_delta"
    raw_delta.delta.thinking = "reasoning"

    raw_stop = MagicMock()
    raw_stop.type = "content_block_stop"
    raw_stop.index = 0

    async def aiter():
        for ev in (raw_start, raw_delta, raw_stop):
            yield ev

    stream_cm = MagicMock()
    stream_cm.__aiter__ = lambda self: aiter()

    thinking_block = MagicMock()
    thinking_block.type = "thinking"
    thinking_block.thinking = "reasoning"
    thinking_block.signature = "sig_xyz"
    stream_cm.current_message_snapshot.content = [thinking_block]

    final_msg = MagicMock()
    final_msg.stop_reason = "end_turn"
    stream_cm.get_final_message = AsyncMock(return_value=final_msg)

    stream_cm.__aenter__ = AsyncMock(return_value=stream_cm)
    stream_cm.__aexit__ = AsyncMock(return_value=None)
    return stream_cm


@pytest.mark.asyncio
async def test_anthropic_adaptive_effort_high_builds_correct_kwargs() -> None:
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", thinking_capability="adaptive")
    captured_kwargs: dict = {}

    def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return _build_stream_mock()

    provider._client = MagicMock()
    provider._client.messages.stream = fake_stream

    events = []
    async for ev in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking_effort="high",
    ):
        events.append(ev)

    assert captured_kwargs["thinking"] == {"type": "adaptive"}
    assert captured_kwargs["output_config"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_anthropic_adaptive_effort_off_omits_thinking() -> None:
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", thinking_capability="adaptive")
    captured_kwargs: dict = {}

    def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return _build_stream_mock()

    provider._client = MagicMock()
    provider._client.messages.stream = fake_stream

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking_effort="off",
    ):
        pass

    assert "thinking" not in captured_kwargs
    assert "output_config" not in captured_kwargs


@pytest.mark.asyncio
async def test_anthropic_fixed_effort_medium_uses_budget_tokens() -> None:
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", thinking_capability="effort")
    captured_kwargs: dict = {}

    def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return _build_stream_mock()

    provider._client = MagicMock()
    provider._client.messages.stream = fake_stream

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="claude-3-7-sonnet",
        max_tokens=16384,
        thinking_effort="medium",
    ):
        pass

    assert captured_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 8192}


@pytest.mark.asyncio
async def test_anthropic_toggle_on_sends_enabled_without_budget() -> None:
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", thinking_capability="toggle")
    captured_kwargs: dict = {}

    def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return _build_stream_mock()

    provider._client = MagicMock()
    provider._client.messages.stream = fake_stream

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="third-party-claude",
        max_tokens=4096,
        thinking_effort="on",
    ):
        pass

    assert captured_kwargs["thinking"] == {"type": "enabled"}
    assert "budget_tokens" not in captured_kwargs["thinking"]


@pytest.mark.asyncio
async def test_anthropic_none_capability_ignores_effort() -> None:
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", thinking_capability=None)
    captured_kwargs: dict = {}

    def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return _build_stream_mock()

    provider._client = MagicMock()
    provider._client.messages.stream = fake_stream

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking_effort="high",
    ):
        pass

    assert "thinking" not in captured_kwargs
    assert "output_config" not in captured_kwargs


@pytest.mark.asyncio
async def test_anthropic_thinking_block_stop_carries_signature() -> None:
    from sebastian.core.stream_events import ThinkingBlockStop
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="fake", thinking_capability="adaptive")
    provider._client = MagicMock()
    provider._client.messages.stream = lambda **kw: _build_stream_mock()

    stops = []
    async for ev in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking_effort="low",
    ):
        if isinstance(ev, ThinkingBlockStop):
            stops.append(ev)

    assert len(stops) == 1
    assert stops[0].signature == "sig_xyz"
    assert stops[0].thinking == "reasoning"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_anthropic_thinking.py -v
```

Expected: 所有新测试 FAIL（`AnthropicProvider` 不接受 `thinking_capability` 参数 / 不注入 thinking kwargs / ThinkingBlockStop 没 signature）

- [ ] **Step 3: 改 `AnthropicProvider`**

完整替换 `sebastian/llm/anthropic.py`：

```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, ClassVar

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

    # Fixed-budget mode (thinking_capability="effort"): map effort → budget_tokens.
    FIXED_EFFORT_TO_BUDGET: ClassVar[dict[str, int]] = {
        "low": 2048,
        "medium": 8192,
        "high": 24576,
    }

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        thinking_capability: str | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            **({"base_url": base_url} if base_url else {}),
        )
        self._capability = thinking_capability

    def _build_thinking_kwargs(
        self, thinking_effort: str | None, max_tokens: int
    ) -> dict[str, Any]:
        """Translate (capability, effort) → SDK kwargs fragment.

        Returns empty dict when no thinking should be enabled.
        """
        if self._capability is None or self._capability in ("none", "always_on"):
            return {}
        if thinking_effort in (None, "off"):
            return {}

        if self._capability == "toggle":
            if thinking_effort == "on":
                return {"thinking": {"type": "enabled"}}
            return {}

        if self._capability == "adaptive":
            if thinking_effort in ("low", "medium", "high", "max"):
                return {
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": thinking_effort},
                }
            return {}

        if self._capability == "effort":
            budget = self.FIXED_EFFORT_TO_BUDGET.get(thinking_effort)
            if budget is None:
                return {}
            # budget_tokens must be strictly less than max_tokens. If caller's
            # max_tokens is too tight, clamp budget to max_tokens - 1 with a
            # floor of 1024 (Anthropic minimum). If even 1024 doesn't fit,
            # disable thinking rather than raise.
            if budget >= max_tokens:
                budget = max(1024, max_tokens - 1)
                if budget >= max_tokens:
                    return {}
            return {"thinking": {"type": "enabled", "budget_tokens": budget}}

        return {}

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
        block_id_prefix: str = "",
        thinking_effort: str | None = None,
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        kwargs.update(self._build_thinking_kwargs(thinking_effort, max_tokens))

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

                block = stream.current_message_snapshot.content[block_index]
                if block.type == "thinking":
                    yield ThinkingBlockStop(
                        block_id=block_id,
                        thinking=block.thinking,
                        signature=getattr(block, "signature", None),
                    )
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

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/test_anthropic_thinking.py tests/unit/test_llm_provider.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/llm/anthropic.py tests/unit/test_anthropic_thinking.py
git commit -m "feat(llm): AnthropicProvider 按 capability 构造 thinking 参数并传出 signature"
```

---

## Task 5: `OpenAICompatProvider` —— 按 capability 注入 `reasoning_effort`

**Files:**
- Modify: `sebastian/llm/openai_compat.py`
- Test: `tests/unit/test_openai_compat_thinking.py`（新建）

- [ ] **Step 1: 写失败的测试**

新建 `tests/unit/test_openai_compat_thinking.py`：

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _build_empty_completion_stream():
    """Return an async iterator that immediately ends, finish_reason=stop."""
    chunk = MagicMock()
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.delta.content = None
    choice.delta.reasoning_content = None
    choice.delta.tool_calls = None
    chunk.choices = [choice]

    class AsyncIter:
        def __init__(self):
            self._yielded = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return chunk

    async def _create(**kwargs):
        return AsyncIter()

    return _create


@pytest.mark.asyncio
async def test_openai_effort_high_passes_reasoning_effort() -> None:
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="fake", thinking_capability="effort")
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        stream = _build_empty_completion_stream()
        return await stream(**kwargs)

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="o3",
        max_tokens=4096,
        thinking_effort="high",
    ):
        pass

    assert captured.get("reasoning_effort") == "high"


@pytest.mark.asyncio
async def test_openai_effort_off_omits_reasoning_effort() -> None:
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="fake", thinking_capability="effort")
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        stream = _build_empty_completion_stream()
        return await stream(**kwargs)

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="o3",
        max_tokens=4096,
        thinking_effort="off",
    ):
        pass

    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_openai_none_capability_ignores_effort() -> None:
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="fake", thinking_capability="none")
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        stream = _build_empty_completion_stream()
        return await stream(**kwargs)

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gpt-4o",
        max_tokens=4096,
        thinking_effort="high",
    ):
        pass

    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_openai_toggle_capability_is_noop() -> None:
    """OpenAI 路径下 toggle 默认 no-op（见 spec §3.2）。"""
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="fake", thinking_capability="toggle")
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        stream = _build_empty_completion_stream()
        return await stream(**kwargs)

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    async for _ in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="some-third-party",
        max_tokens=4096,
        thinking_effort="on",
    ):
        pass

    assert "reasoning_effort" not in captured
    assert "thinking" not in captured
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_openai_compat_thinking.py -v
```

Expected: FAIL

- [ ] **Step 3: 改 `OpenAICompatProvider`**

修改 `sebastian/llm/openai_compat.py`：

1. `__init__` 增加 `thinking_capability` 参数：

```python
def __init__(
    self,
    api_key: str,
    base_url: str | None = None,
    thinking_format: str | None = None,
    thinking_capability: str | None = None,
) -> None:
    self._client = openai.AsyncOpenAI(
        api_key=api_key,
        **({"base_url": base_url} if base_url else {}),
    )
    self._thinking_format = thinking_format
    self._capability = thinking_capability
```

2. `stream` 签名加 `thinking_effort: str | None = None`。

3. 在 `kwargs` 构造之后、调用 `create` 之前加一段：

```python
if self._capability == "effort" and thinking_effort not in (None, "off"):
    if thinking_effort in ("low", "medium", "high"):
        kwargs["reasoning_effort"] = thinking_effort
# 其余 capability（none / toggle / adaptive / always_on）在 OpenAI 路径下均为 no-op
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/test_openai_compat_thinking.py tests/unit/test_llm_provider.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/llm/openai_compat.py tests/unit/test_openai_compat_thinking.py
git commit -m "feat(llm): OpenAICompatProvider 按 capability 注入 reasoning_effort"
```

---

## Task 6: `LLMProviderRegistry` —— 把 capability 传入 Provider 实例

**Files:**
- Modify: `sebastian/llm/registry.py:116-132`
- Test: `tests/unit/test_llm_provider_routing.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_llm_provider_routing.py` 尾部追加：

```python
@pytest.mark.asyncio
async def test_registry_passes_thinking_capability_to_provider() -> None:
    from unittest.mock import MagicMock

    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="test",
        provider_type="anthropic",
        api_key_enc="",  # 实际不会解密，下面 monkey-patch decrypt
        model="claude-opus-4-6",
        thinking_capability="adaptive",
    )

    registry = LLMProviderRegistry(db_factory=MagicMock())

    import sebastian.llm.crypto as crypto
    original_decrypt = crypto.decrypt
    crypto.decrypt = lambda _enc: "fake-key"
    try:
        provider = registry._instantiate(record)
    finally:
        crypto.decrypt = original_decrypt

    from sebastian.llm.anthropic import AnthropicProvider
    assert isinstance(provider, AnthropicProvider)
    assert provider._capability == "adaptive"


@pytest.mark.asyncio
async def test_registry_passes_thinking_capability_to_openai_provider() -> None:
    from unittest.mock import MagicMock

    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="test",
        provider_type="openai",
        api_key_enc="",
        model="o3",
        thinking_format=None,
        thinking_capability="effort",
    )

    registry = LLMProviderRegistry(db_factory=MagicMock())

    import sebastian.llm.crypto as crypto
    original_decrypt = crypto.decrypt
    crypto.decrypt = lambda _enc: "fake-key"
    try:
        provider = registry._instantiate(record)
    finally:
        crypto.decrypt = original_decrypt

    from sebastian.llm.openai_compat import OpenAICompatProvider
    assert isinstance(provider, OpenAICompatProvider)
    assert provider._capability == "effort"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_llm_provider_routing.py::test_registry_passes_thinking_capability_to_provider tests/unit/test_llm_provider_routing.py::test_registry_passes_thinking_capability_to_openai_provider -v
```

Expected: FAIL

- [ ] **Step 3: 改 `_instantiate`**

修改 `sebastian/llm/registry.py` 的 `_instantiate`：

```python
def _instantiate(self, record: LLMProviderRecord) -> LLMProvider:
    from sebastian.llm.crypto import decrypt

    plain_key = decrypt(record.api_key_enc)
    if record.provider_type == "anthropic":
        from sebastian.llm.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=plain_key,
            base_url=record.base_url,
            thinking_capability=record.thinking_capability,
        )
    if record.provider_type == "openai":
        from sebastian.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=plain_key,
            base_url=record.base_url,
            thinking_format=record.thinking_format,
            thinking_capability=record.thinking_capability,
        )
    raise ValueError(f"Unknown provider_type: {record.provider_type!r}")
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/test_llm_provider_routing.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/llm/registry.py tests/unit/test_llm_provider_routing.py
git commit -m "feat(llm): registry 实例化 Provider 时传入 thinking_capability"
```

---

## Task 7: `AgentLoop` —— 透传 `thinking_effort` + 多轮回填 signature

**Files:**
- Modify: `sebastian/core/agent_loop.py`
- Test: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_agent_loop.py` 追加：

```python
@pytest.mark.asyncio
async def test_agent_loop_passes_thinking_effort_to_provider() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core.stream_events import ProviderCallEnd, TurnDone

    async def _empty_stream(**kwargs):
        # Capture kwargs for assertion via closure
        captured.update(kwargs)
        yield ProviderCallEnd(stop_reason="end_turn")

    captured: dict = {}
    provider = MagicMock()
    provider.message_format = "anthropic"
    provider.stream = _empty_stream

    tool_provider = MagicMock()
    tool_provider.get_all_tool_specs = MagicMock(return_value=[])

    loop = AgentLoop(provider=provider, tool_provider=tool_provider, model="m", max_tokens=1000)
    gen = loop.stream(system_prompt="sys", messages=[], task_id=None, thinking_effort="high")

    events = []
    try:
        while True:
            events.append(await gen.asend(None))
    except StopAsyncIteration:
        pass

    assert captured.get("thinking_effort") == "high"


@pytest.mark.asyncio
async def test_agent_loop_preserves_thinking_signature_across_iterations() -> None:
    """Multi-turn with tool_use: first iteration emits thinking block with signature,
    loop must include signature in the assistant_blocks it appends to `working`
    messages before the next iteration."""
    from unittest.mock import MagicMock
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core.stream_events import (
        ProviderCallEnd,
        ThinkingBlockStop,
        ToolCallReady,
        ToolResult,
    )

    iteration_calls: list[list[dict]] = []

    async def _two_iter_stream(**kwargs):
        iteration_calls.append(list(kwargs["messages"]))
        if len(iteration_calls) == 1:
            yield ThinkingBlockStop(block_id="b0_0", thinking="thought", signature="sig_1")
            yield ToolCallReady(block_id="b0_1", tool_id="tu_1", name="noop", inputs={})
            yield ProviderCallEnd(stop_reason="tool_use")
        else:
            yield ProviderCallEnd(stop_reason="end_turn")

    provider = MagicMock()
    provider.message_format = "anthropic"
    provider.stream = _two_iter_stream

    tool_provider = MagicMock()
    tool_provider.get_all_tool_specs = MagicMock(return_value=[])

    loop = AgentLoop(provider=provider, tool_provider=tool_provider, model="m", max_tokens=1000)
    gen = loop.stream(system_prompt="sys", messages=[{"role": "user", "content": "hi"}])

    # Drive the generator, injecting tool result when asked
    events = []
    send_val = None
    try:
        while True:
            ev = await gen.asend(send_val)
            send_val = None
            events.append(ev)
            if isinstance(ev, ToolCallReady):
                send_val = ToolResult(tool_id="tu_1", name="noop", ok=True, output="done", error=None)
    except StopAsyncIteration:
        pass

    # Second iteration's messages should contain the assistant turn with a thinking block + signature
    assert len(iteration_calls) == 2
    second_msgs = iteration_calls[1]
    assistant_msgs = [m for m in second_msgs if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    blocks = assistant_msgs[0]["content"]
    thinking_blocks = [b for b in blocks if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["thinking"] == "thought"
    assert thinking_blocks[0]["signature"] == "sig_1"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_agent_loop.py::test_agent_loop_passes_thinking_effort_to_provider tests/unit/test_agent_loop.py::test_agent_loop_preserves_thinking_signature_across_iterations -v
```

Expected: FAIL

- [ ] **Step 3: 修改 `AgentLoop.stream` 签名与 body**

修改 `sebastian/core/agent_loop.py`：

1. `stream` 加 `thinking_effort: str | None = None` 参数：

```python
async def stream(
    self,
    system_prompt: str,
    messages: list[dict[str, Any]],
    task_id: str | None = None,
    thinking_effort: str | None = None,
) -> AsyncGenerator[LLMStreamEvent, ToolResult | None]:
```

2. 在循环内调用 `self._provider.stream(...)` 的地方加 `thinking_effort=thinking_effort`：

```python
async for event in self._provider.stream(
    system=system_prompt,
    messages=working,
    tools=tools,
    model=self._model,
    max_tokens=self._max_tokens,
    block_id_prefix=f"b{iteration}_",
    thinking_effort=thinking_effort,
):
```

3. 在处理 `ThinkingBlockStop` 的分支里，把 signature 带入 assistant_blocks：

```python
if isinstance(event, ThinkingBlockStop):
    if not is_openai:
        block_dict: dict[str, Any] = {"type": "thinking", "thinking": event.thinking}
        if event.signature is not None:
            block_dict["signature"] = event.signature
        assistant_blocks.append(block_dict)
    yield event
```

- [ ] **Step 4: 运行新测试**

```bash
pytest tests/unit/test_agent_loop.py -v
```

Expected: 全部 PASS（包括原有的 agent_loop 测试）

- [ ] **Step 5: 提交**

```bash
git add sebastian/core/agent_loop.py tests/unit/test_agent_loop.py
git commit -m "feat(core): AgentLoop 透传 thinking_effort 并在多轮回填 signature"
```

---

## Task 8: `BaseAgent` —— `run_streaming` 透传 `thinking_effort`

**Files:**
- Modify: `sebastian/core/base_agent.py:216-339`
- Test: `tests/unit/test_base_agent.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_base_agent.py` 尾部追加：

```python
@pytest.mark.asyncio
async def test_base_agent_run_streaming_passes_thinking_effort_to_loop() -> None:
    """Verify run_streaming pipes thinking_effort down to AgentLoop.stream."""
    from unittest.mock import AsyncMock, MagicMock
    from sebastian.core.stream_events import ProviderCallEnd, TurnDone

    # Build a minimal BaseAgent-like test harness. Reuse existing helper if present;
    # otherwise instantiate Sebastian and patch the loop.
    import sebastian.gateway.state as state  # relies on tests/conftest.py bootstrap

    agent = state.sebastian  # type: ignore[attr-defined]
    captured: dict = {}

    original_stream = agent._loop.stream

    async def fake_stream(system_prompt, messages, task_id=None, thinking_effort=None):
        captured["thinking_effort"] = thinking_effort
        yield TurnDone(full_text="done")

    agent._loop.stream = fake_stream  # type: ignore[assignment]
    try:
        session = await agent.get_or_create_session(None, "hi")
        await agent.run_streaming("hi", session.id, thinking_effort="medium")
    finally:
        agent._loop.stream = original_stream  # type: ignore[assignment]

    assert captured.get("thinking_effort") == "medium"
```

> 如果 `tests/conftest.py` 没有提供 `state.sebastian` 的 fixture，改用已有的 `test_base_agent.py` 里构建 BaseAgent 的 helper（参考同文件前面的测试）。

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_base_agent.py::test_base_agent_run_streaming_passes_thinking_effort_to_loop -v
```

Expected: FAIL（`run_streaming` 不接受 `thinking_effort` 参数）

- [ ] **Step 3: 修改 `BaseAgent.run_streaming` 和 `_stream_inner`**

在 `sebastian/core/base_agent.py`：

1. `run` 和 `run_streaming` 签名加 `thinking_effort: str | None = None`：

```python
async def run(
    self,
    user_message: str,
    session_id: str,
    task_id: str | None = None,
    agent_name: str | None = None,
    thinking_effort: str | None = None,
) -> str:
    return await self.run_streaming(
        user_message,
        session_id,
        task_id=task_id,
        agent_name=agent_name,
        thinking_effort=thinking_effort,
    )

async def run_streaming(
    self,
    user_message: str,
    session_id: str,
    task_id: str | None = None,
    agent_name: str | None = None,
    thinking_effort: str | None = None,
) -> str:
    ...
```

2. `run_streaming` 内部创建 `_stream_inner` 任务时透传：

```python
current_stream = asyncio.create_task(
    self._stream_inner(
        messages=messages,
        session_id=session_id,
        task_id=task_id,
        agent_context=agent_context,
        thinking_effort=thinking_effort,
    )
)
```

3. `_stream_inner` 签名加 `thinking_effort: str | None`，并在调用 `self._loop.stream(...)` 时透传：

```python
async def _stream_inner(
    self,
    messages: list[dict[str, str]],
    session_id: str,
    task_id: str | None,
    agent_context: str,
    thinking_effort: str | None = None,
) -> str:
    ...
    gen = self._loop.stream(
        effective_system_prompt,
        messages,
        task_id=task_id,
        thinking_effort=thinking_effort,
    )
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/unit/test_base_agent.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent.py
git commit -m "feat(core): BaseAgent.run_streaming 透传 thinking_effort"
```

---

## Task 9: Gateway `POST /api/v1/turns` —— 加 `thinking_effort` 字段

**Files:**
- Modify: `sebastian/gateway/routes/turns.py:29-87`
- Test: `tests/integration/test_gateway_turns.py`

- [ ] **Step 1: 写失败的集成测试**

在 `tests/integration/test_gateway_turns.py` 尾部追加：

```python
@pytest.mark.asyncio
async def test_post_turns_accepts_thinking_effort_and_passes_to_agent(
    client, auth_headers, monkeypatch,
) -> None:
    """POST /api/v1/turns 携带 thinking_effort 时，传给 sebastian.run_streaming。"""
    import sebastian.gateway.state as state

    captured: dict = {}

    original_run = state.sebastian.run_streaming

    async def fake_run_streaming(content, session_id, *, thinking_effort=None, **kwargs):
        captured["thinking_effort"] = thinking_effort
        return "ok"

    monkeypatch.setattr(state.sebastian, "run_streaming", fake_run_streaming)

    response = await client.post(
        "/api/v1/turns",
        json={"content": "hello", "thinking_effort": "high"},
        headers=auth_headers,
    )
    assert response.status_code == 200

    # wait for background task
    import asyncio
    await asyncio.sleep(0.05)

    assert captured.get("thinking_effort") == "high"
```

> `client` / `auth_headers` / `monkeypatch` fixture 参考同文件已有测试。

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/integration/test_gateway_turns.py::test_post_turns_accepts_thinking_effort_and_passes_to_agent -v
```

Expected: FAIL

- [ ] **Step 3: 修改 `SendTurnRequest` 和 `send_turn`**

修改 `sebastian/gateway/routes/turns.py`：

```python
class SendTurnRequest(BaseModel):
    content: str
    session_id: str | None = None
    thinking_effort: str | None = None  # off | on | low | medium | high | max | None


@router.post("/turns")
async def send_turn(
    body: SendTurnRequest,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    await _ensure_llm_ready("sebastian")
    session = await state.sebastian.get_or_create_session(body.session_id, body.content)
    task = asyncio.create_task(
        state.sebastian.run_streaming(
            body.content,
            session.id,
            thinking_effort=body.thinking_effort,
        )
    )
    task.add_done_callback(_log_background_turn_failure)
    return {
        "session_id": session.id,
        "ts": datetime.now(UTC).isoformat(),
    }
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/integration/test_gateway_turns.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/gateway/routes/turns.py tests/integration/test_gateway_turns.py
git commit -m "feat(gateway): POST /turns 接受 thinking_effort 并透传"
```

---

## Task 10: Gateway `POST /sessions/{id}/turns` —— 对称改造

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Test: `tests/integration/test_gateway_sessions.py`

- [ ] **Step 1: 定位现有 sub-agent turns 路由**

```bash
grep -n "sessions/.*turns\|/turns" sebastian/gateway/routes/sessions.py
```

记下路由位置、请求体模型名称。

- [ ] **Step 2: 写失败的测试**

在 `tests/integration/test_gateway_sessions.py` 追加（假设 sub-agent session 创建 helper 已存在）：

```python
@pytest.mark.asyncio
async def test_sub_agent_turns_accepts_thinking_effort(
    client, auth_headers, monkeypatch,
) -> None:
    """POST /api/v1/sessions/{id}/turns 同样接受 thinking_effort。"""
    import sebastian.gateway.state as state

    captured: dict = {}

    # 假设第一个已注册 sub-agent
    sub_agent_type = next(iter(state.agent_instances.keys()))
    sub_agent = state.agent_instances[sub_agent_type]

    original_run = sub_agent.run_streaming

    async def fake_run(content, session_id, *, thinking_effort=None, **kw):
        captured["thinking_effort"] = thinking_effort
        return "ok"

    monkeypatch.setattr(sub_agent, "run_streaming", fake_run)

    # 创建 sub-agent session
    create_resp = await client.post(
        f"/api/v1/agents/{sub_agent_type}/sessions",
        json={"initial_content": "hi"},
        headers=auth_headers,
    )
    assert create_resp.status_code in (200, 201)
    session_id = create_resp.json()["session_id"]

    resp = await client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"content": "follow up", "thinking_effort": "medium"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    import asyncio
    await asyncio.sleep(0.05)
    assert captured.get("thinking_effort") == "medium"
```

- [ ] **Step 3: 运行测试确认失败**

```bash
pytest tests/integration/test_gateway_sessions.py::test_sub_agent_turns_accepts_thinking_effort -v
```

Expected: FAIL

- [ ] **Step 4: 修改 sub-agent turns 路由**

在 `sebastian/gateway/routes/sessions.py` 的 sub-agent turns 端点：

1. 请求体模型新增 `thinking_effort: str | None = None`
2. 调用 `run_streaming` 时加 `thinking_effort=body.thinking_effort`

（具体代码按 Step 1 定位到的位置修改，沿用 Task 9 的模式）

- [ ] **Step 5: 运行测试**

```bash
pytest tests/integration/test_gateway_sessions.py -v
```

Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add sebastian/gateway/routes/sessions.py tests/integration/test_gateway_sessions.py
git commit -m "feat(gateway): sub-agent turns 路由接受 thinking_effort"
```

---

## Task 11: Gateway `llm_providers` CRUD —— 暴露 `thinking_capability`

**Files:**
- Modify: `sebastian/gateway/routes/llm_providers.py:15-106`
- Test: `tests/integration/test_llm_providers_api.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/integration/test_llm_providers_api.py` 追加：

```python
@pytest.mark.asyncio
async def test_create_provider_with_thinking_capability(client, auth_headers) -> None:
    resp = await client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Test Adaptive",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "thinking_capability": "adaptive",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["thinking_capability"] == "adaptive"

    list_resp = await client.get("/api/v1/llm-providers", headers=auth_headers)
    assert list_resp.status_code == 200
    providers = list_resp.json()["providers"]
    created = next(p for p in providers if p["id"] == data["id"])
    assert created["thinking_capability"] == "adaptive"


@pytest.mark.asyncio
async def test_update_provider_thinking_capability(client, auth_headers) -> None:
    create = await client.post(
        "/api/v1/llm-providers",
        json={
            "name": "TestU",
            "provider_type": "openai",
            "api_key": "sk-fake",
            "model": "o3",
        },
        headers=auth_headers,
    )
    pid = create.json()["id"]

    upd = await client.put(
        f"/api/v1/llm-providers/{pid}",
        json={"thinking_capability": "effort"},
        headers=auth_headers,
    )
    assert upd.status_code == 200
    assert upd.json()["thinking_capability"] == "effort"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/integration/test_llm_providers_api.py::test_create_provider_with_thinking_capability tests/integration/test_llm_providers_api.py::test_update_provider_thinking_capability -v
```

Expected: FAIL

- [ ] **Step 3: 修改 CRUD 请求/响应模型**

修改 `sebastian/gateway/routes/llm_providers.py`：

```python
class LLMProviderCreate(BaseModel):
    name: str
    provider_type: str
    api_key: str
    model: str
    base_url: str | None = None
    thinking_format: str | None = None
    thinking_capability: str | None = None
    is_default: bool = False


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    thinking_format: str | None = None
    thinking_capability: str | None = None
    is_default: bool | None = None


def _record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "provider_type": record.provider_type,
        "base_url": record.base_url,
        "model": record.model,
        "thinking_format": record.thinking_format,
        "thinking_capability": record.thinking_capability,
        "is_default": record.is_default,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
```

`create_llm_provider` 内构造 record 时传 `thinking_capability=body.thinking_capability`。
`update_llm_provider` 加一个分支：

```python
if body.thinking_capability is not None:
    updates["thinking_capability"] = body.thinking_capability
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/integration/test_llm_providers_api.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add sebastian/gateway/routes/llm_providers.py tests/integration/test_llm_providers_api.py
git commit -m "feat(gateway): llm_providers CRUD 暴露 thinking_capability 字段"
```

---

## Task 12: 后端 README 与文档更新

**Files:**
- Modify: `sebastian/llm/README.md`
- Modify: `sebastian/store/README.md`（如存在则更新，不存在则跳过）

- [ ] **Step 1: 更新 `sebastian/llm/README.md`**

在"OpenAI 兼容的 thinking_format"小节后面新增一节"thinking_capability"：

```markdown
## thinking_capability

与 `thinking_format`（解析返回）正交，`thinking_capability` 描述 Provider 如何**发起**思考请求，值为：

| 值 | 含义 | 可选 effort | 请求行为 |
|---|---|---|---|
| `none` | 不支持思考控制 | — | 不传任何 thinking 参数 |
| `toggle` | 只支持开关二态 | off / on | `thinking={"type":"enabled"}`（Anthropic 路径）；OpenAI 路径 no-op |
| `effort` | 4 档 | off / low / medium / high | Anthropic 旧版 `thinking={"type":"enabled","budget_tokens":N}`；OpenAI `reasoning_effort=...` |
| `adaptive` | Anthropic Adaptive Thinking | off / low / medium / high / max | `thinking={"type":"adaptive"}` + `output_config={"effort":...}` |
| `always_on` | 模型必然思考 | —（UI 固定）| 不传参数，解析侧由 `thinking_format` 决定 |

典型组合：

| 模型 | provider_type | thinking_capability | thinking_format |
|---|---|---|---|
| Claude Opus 4.6 / Sonnet 4.6 | anthropic | adaptive | None |
| Claude 3.7 Sonnet | anthropic | effort | None |
| 第三方 Anthropic-format 代理 | anthropic | toggle | None |
| OpenAI o3 / o4 | openai | effort | None |
| GPT-4o | openai | none | None |
| DeepSeek-R1 | openai | always_on | reasoning_content |
| llama.cpp Qwen `<think>` | openai | always_on | think_tags |

**注意**：`OpenAICompatProvider` 收到 `capability=toggle` 时默认 no-op。OpenAI 兼容接口没有统一的"布尔 thinking"字段标准，若将来需要支持具体某个后端，再在 `openai_compat.py` 加分支。

Anthropic 旧版 effort 模式的 budget_tokens 映射写在 `AnthropicProvider.FIXED_EFFORT_TO_BUDGET` 常量表里（low=2048 / medium=8192 / high=24576）。budget_tokens 必须小于 max_tokens，超出时自动 clamp 到 `max(1024, max_tokens - 1)`；如果连 1024 都放不下则禁用 thinking。
```

修改导航表追加一行：

```markdown
| 调整 thinking_capability 翻译规则 / budget 默认值 | [anthropic.py](anthropic.py) 的 `_build_thinking_kwargs` 与 `FIXED_EFFORT_TO_BUDGET` / [openai_compat.py](openai_compat.py) |
```

- [ ] **Step 2: 提交**

```bash
git add sebastian/llm/README.md
git commit -m "docs(llm): README 补充 thinking_capability 字段说明"
```

---

## Task 13: 前端类型定义

**Files:**
- Modify: `ui/mobile/src/types.ts`

- [ ] **Step 1: 新增类型**

在 `ui/mobile/src/types.ts` 顶部或现有类型区新增：

```typescript
export type ThinkingEffort =
  | 'off'
  | 'on'
  | 'low'
  | 'medium'
  | 'high'
  | 'max';

export type ThinkingCapability =
  | 'none'
  | 'toggle'
  | 'effort'
  | 'adaptive'
  | 'always_on';

export const EFFORT_LEVELS_BY_CAPABILITY: Record<ThinkingCapability, readonly ThinkingEffort[]> = {
  none: [],
  toggle: ['off', 'on'],
  effort: ['off', 'low', 'medium', 'high'],
  adaptive: ['off', 'low', 'medium', 'high', 'max'],
  always_on: [],
};
```

- [ ] **Step 2: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误（假设原有代码没受影响）

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/src/types.ts
git commit -m "feat(mobile): 新增 ThinkingEffort / ThinkingCapability 类型"
```

---

## Task 14: 前端 composer store —— effortBySession + lastUserChoice

**Files:**
- Modify: `ui/mobile/src/store/composer.ts`

- [ ] **Step 1: 完整替换 composer store**

替换 `ui/mobile/src/store/composer.ts`：

```typescript
import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ThinkingEffort } from '../types';

const DRAFT_KEY = '__draft__';

interface ComposerStore {
  effortBySession: Record<string, ThinkingEffort>;
  lastUserChoice: ThinkingEffort;

  getEffort: (sessionId: string | null) => ThinkingEffort;
  setEffort: (sessionId: string | null, effort: ThinkingEffort) => void;
  migrateDraftToSession: (newSessionId: string) => void;
  clearSession: (sessionId: string) => void;
  clampAllToCapability: (allowedEfforts: readonly ThinkingEffort[]) => ThinkingEffort | null;
}

function clampOne(
  current: ThinkingEffort,
  allowed: readonly ThinkingEffort[],
): ThinkingEffort {
  if (allowed.includes(current)) return current;
  // Mapping rules (spec §3.7.1):
  //   max → high; on → medium; low/medium/high → same if present else closest
  // Degradation to toggle: any "on" state maps to 'on'
  if (allowed.includes('on')) {
    return current === 'off' ? 'off' : 'on';
  }
  if (current === 'max' && allowed.includes('high')) return 'high';
  if (current === 'on' && allowed.includes('medium')) return 'medium';
  // Fallback: first non-off value, or 'off' if allowed
  if (allowed.includes('off')) return 'off';
  return allowed[0] ?? 'off';
}

export const useComposerStore = create<ComposerStore>()(
  persist(
    (set, get) => ({
      effortBySession: {},
      lastUserChoice: 'off',

      getEffort(sessionId) {
        const key = sessionId ?? DRAFT_KEY;
        return get().effortBySession[key] ?? get().lastUserChoice;
      },

      setEffort(sessionId, effort) {
        const key = sessionId ?? DRAFT_KEY;
        set((s) => ({
          effortBySession: { ...s.effortBySession, [key]: effort },
          lastUserChoice: effort,
        }));
      },

      migrateDraftToSession(newSessionId) {
        set((s) => {
          const draftVal = s.effortBySession[DRAFT_KEY];
          if (draftVal === undefined) return s;
          const next = { ...s.effortBySession };
          next[newSessionId] = draftVal;
          delete next[DRAFT_KEY];
          return { effortBySession: next };
        });
      },

      clearSession(sessionId) {
        set((s) => {
          const next = { ...s.effortBySession };
          delete next[sessionId];
          return { effortBySession: next };
        });
      },

      clampAllToCapability(allowedEfforts) {
        // Returns the clamped lastUserChoice if it changed, else null (for toast hint).
        const s = get();
        let changedFromValue: ThinkingEffort | null = null;
        const nextMap: Record<string, ThinkingEffort> = {};
        for (const [k, v] of Object.entries(s.effortBySession)) {
          const clamped = clampOne(v, allowedEfforts);
          if (clamped !== v) {
            nextMap[k] = clamped;
            if (k === DRAFT_KEY) changedFromValue = v;
          } else {
            nextMap[k] = v;
          }
        }
        const clampedLast = clampOne(s.lastUserChoice, allowedEfforts);
        const lastChanged = clampedLast !== s.lastUserChoice;
        set({
          effortBySession: nextMap,
          lastUserChoice: clampedLast,
        });
        return lastChanged ? s.lastUserChoice : changedFromValue;
      },
    }),
    {
      name: 'sebastian-composer-v2',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (s) => ({ lastUserChoice: s.lastUserChoice }),
    },
  ),
);
```

- [ ] **Step 2: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误（如果报 `AsyncStorage` 缺失，检查 `package.json` 是否已安装 `@react-native-async-storage/async-storage`；此项目 settings 已在用此包）

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/src/store/composer.ts
git commit -m "refactor(mobile): composer store 从布尔 thinking 迁移到 effort 档位"
```

---

## Task 15: 前端 settings store —— 加 `currentThinkingCapability`

**Files:**
- Modify: `ui/mobile/src/store/settings.ts`

- [ ] **Step 1: 阅读现有 store 结构**

```bash
cat ui/mobile/src/store/settings.ts
```

记下 persist 配置、已有字段命名风格。

- [ ] **Step 2: 增加字段与 setter**

在 `SettingsStore` interface 加一个字段：

```typescript
currentThinkingCapability: ThinkingCapability | null;
setCurrentThinkingCapability: (cap: ThinkingCapability | null) => void;
```

在 `create` 的 body 中加初始值 `currentThinkingCapability: null`，和 setter：

```typescript
setCurrentThinkingCapability(cap) {
  set({ currentThinkingCapability: cap });
},
```

**重要**：这个字段**不要**放进 `partialize`——capability 应该在每次 provider 列表拉取后重新计算，不从本地恢复。

导入 `ThinkingCapability` from `../types`。

- [ ] **Step 3: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/src/store/settings.ts
git commit -m "feat(mobile): settings store 加 currentThinkingCapability 字段"
```

---

## Task 16: 前端 providers API —— 拉取并写入 capability + 触发 clamp

**Files:**
- Modify or Create: `ui/mobile/src/api/llm.ts`
- Modify: `ui/mobile/app/_layout.tsx`（或现有启动初始化的地方）

- [ ] **Step 1: 定位现有 providers API 封装**

```bash
grep -rn "llm-providers" ui/mobile/src/ ui/mobile/app/
```

如果有现成文件（如 `src/api/llm.ts` / `llmProviders.ts`），修改它；否则新建 `src/api/llm.ts`。

- [ ] **Step 2: 新增或完善 `fetchProviders` 与 capability 同步函数**

在 `src/api/llm.ts` 中：

```typescript
import { apiClient } from './client';
import type { ThinkingCapability, ThinkingEffort } from '../types';
import { EFFORT_LEVELS_BY_CAPABILITY } from '../types';
import { useSettingsStore } from '../store/settings';
import { useComposerStore } from '../store/composer';

export interface LLMProviderRecord {
  id: string;
  name: string;
  provider_type: string;
  base_url: string | null;
  model: string;
  thinking_format: string | null;
  thinking_capability: ThinkingCapability | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export async function fetchProviders(): Promise<LLMProviderRecord[]> {
  const { data } = await apiClient.get<{ providers: LLMProviderRecord[] }>(
    '/api/v1/llm-providers',
  );
  return data.providers;
}

export async function syncCurrentThinkingCapability(
  onClamped?: (from: ThinkingEffort, to: ThinkingEffort) => void,
): Promise<void> {
  const providers = await fetchProviders();
  const defaultProvider = providers.find((p) => p.is_default) ?? null;
  const capability = defaultProvider?.thinking_capability ?? null;

  const prevLast = useComposerStore.getState().lastUserChoice;
  useSettingsStore.getState().setCurrentThinkingCapability(capability);

  if (capability) {
    const allowed = EFFORT_LEVELS_BY_CAPABILITY[capability];
    const changedFrom = useComposerStore.getState().clampAllToCapability(allowed);
    if (changedFrom && onClamped) {
      const after = useComposerStore.getState().lastUserChoice;
      onClamped(changedFrom, after);
    }
  }
}
```

- [ ] **Step 3: 在 App 启动时调用**

在 `ui/mobile/app/_layout.tsx` 的根组件 mount effect 里（或者已有的"登录后拉全局数据"的位置）调用 `syncCurrentThinkingCapability()`。

```typescript
import { syncCurrentThinkingCapability } from '@/src/api/llm';
import { useEffect } from 'react';
// ...
useEffect(() => {
  syncCurrentThinkingCapability().catch(() => {
    // 拉失败时 currentThinkingCapability 保持 null，UI 按 disabled 兜底
  });
}, []);
```

> 如果项目里已经有"登录成功后拉 providers"的 hook（例如 `useProviders`），把这条同步逻辑加进去而不是新建 useEffect。先 grep 确认。

- [ ] **Step 4: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/src/api/llm.ts ui/mobile/app/_layout.tsx
git commit -m "feat(mobile): 启动时同步当前默认 provider 的 thinking_capability 并 clamp 档位"
```

---

## Task 17: 前端 `EffortPicker` 组件

**Files:**
- Create: `ui/mobile/src/components/composer/EffortPicker.tsx`

- [ ] **Step 1: 新建组件**

创建 `ui/mobile/src/components/composer/EffortPicker.tsx`：

```typescript
import { Modal, View, Text, TouchableOpacity, StyleSheet, Pressable } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import type { ThinkingEffort } from '../../types';

interface Props {
  visible: boolean;
  options: readonly ThinkingEffort[];
  current: ThinkingEffort;
  onSelect: (effort: ThinkingEffort) => void;
  onClose: () => void;
}

const LABELS: Record<ThinkingEffort, string> = {
  off: '关闭',
  on: '开启',
  low: '低 — 少量思考',
  medium: '中 — 适度思考',
  high: '高 — 深度思考',
  max: '最大 — 无约束思考',
};

export function EffortPicker({ visible, options, current, onSelect, onClose }: Props) {
  const colors = useTheme();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable
          style={[styles.sheet, { backgroundColor: colors.background }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.title, { color: colors.textPrimary }]}>思考深度</Text>
          {options.map((opt) => {
            const active = opt === current;
            return (
              <TouchableOpacity
                key={opt}
                style={[
                  styles.option,
                  active && { backgroundColor: colors.accentMuted ?? '#E8F0FE' },
                ]}
                onPress={() => {
                  onSelect(opt);
                  onClose();
                }}
              >
                <Text
                  style={[
                    styles.optionLabel,
                    { color: active ? (colors.accent ?? '#3B82F6') : colors.textPrimary },
                  ]}
                >
                  {LABELS[opt]}
                </Text>
                {active && (
                  <Text style={{ color: colors.accent ?? '#3B82F6', fontSize: 16 }}>✓</Text>
                )}
              </TouchableOpacity>
            );
          })}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'flex-end',
  },
  sheet: {
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingBottom: 32,
  },
  title: {
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 12,
    textAlign: 'center',
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    paddingHorizontal: 12,
    borderRadius: 10,
  },
  optionLabel: {
    fontSize: 15,
  },
});
```

> 如果 theme 对象没有 `accentMuted` / `accent` 键，用现有的 `ThinkButton` 里已用的 `#E8F0FE` / `#3B82F6` 字面量或者最接近的 theme 字段替代。改之前先看 `ui/mobile/src/theme/ThemeContext.tsx`。

- [ ] **Step 2: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误（按需调整 theme 字段名）

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/src/components/composer/EffortPicker.tsx
git commit -m "feat(mobile): 新增 EffortPicker 组件用于选择思考档位"
```

---

## Task 18: 前端 `ThinkButton` 按 capability 重构

**Files:**
- Modify: `ui/mobile/src/components/composer/ThinkButton.tsx`

- [ ] **Step 1: 完整替换 ThinkButton**

替换 `ui/mobile/src/components/composer/ThinkButton.tsx`：

```typescript
import { useState } from 'react';
import { TouchableOpacity, Text, StyleSheet, View } from 'react-native';
import { ThinkIcon } from '../common/Icons';
import { useTheme } from '../../theme/ThemeContext';
import { EffortPicker } from './EffortPicker';
import { useSettingsStore } from '../../store/settings';
import { EFFORT_LEVELS_BY_CAPABILITY } from '../../types';
import type { ThinkingEffort } from '../../types';

interface Props {
  current: ThinkingEffort;
  onChange: (next: ThinkingEffort) => void;
}

const ACTIVE_BG = '#E8F0FE';
const ACTIVE_FG = '#3B82F6';

const SHORT_LABEL: Record<ThinkingEffort, string> = {
  off: '思考',
  on: '思考',
  low: '思考·低',
  medium: '思考·中',
  high: '思考·高',
  max: '思考·最大',
};

export function ThinkButton({ current, onChange }: Props) {
  const colors = useTheme();
  const capability = useSettingsStore((s) => s.currentThinkingCapability);
  const [pickerVisible, setPickerVisible] = useState(false);

  // Not loaded / not configured: disabled pill
  if (capability === null) {
    return (
      <View style={[styles.pill, { backgroundColor: colors.inputBackground, opacity: 0.5 }]}>
        <ThinkIcon size={16} color={colors.textMuted} />
        <Text style={[styles.label, { color: colors.textMuted }]}>思考</Text>
      </View>
    );
  }

  // Not supported: hide entirely
  if (capability === 'none') {
    return null;
  }

  // Always-on: non-interactive badge
  if (capability === 'always_on') {
    return (
      <View style={[styles.pill, { backgroundColor: colors.inputBackground }]}>
        <ThinkIcon size={16} color={colors.textMuted} />
        <Text style={[styles.label, { color: colors.textMuted }]}>思考·自动</Text>
      </View>
    );
  }

  // Toggle: single-tap on/off, no picker
  if (capability === 'toggle') {
    const active = current === 'on';
    return (
      <TouchableOpacity
        style={[styles.pill, { backgroundColor: active ? ACTIVE_BG : colors.inputBackground }]}
        onPress={() => onChange(active ? 'off' : 'on')}
        activeOpacity={0.7}
      >
        <ThinkIcon size={16} color={active ? ACTIVE_FG : colors.textMuted} />
        <Text style={[styles.label, { color: active ? ACTIVE_FG : colors.textMuted }]}>
          思考
        </Text>
      </TouchableOpacity>
    );
  }

  // effort / adaptive: pill + picker
  const active = current !== 'off';
  const options = EFFORT_LEVELS_BY_CAPABILITY[capability];

  return (
    <>
      <TouchableOpacity
        style={[styles.pill, { backgroundColor: active ? ACTIVE_BG : colors.inputBackground }]}
        onPress={() => setPickerVisible(true)}
        activeOpacity={0.7}
      >
        <ThinkIcon size={16} color={active ? ACTIVE_FG : colors.textMuted} />
        <Text style={[styles.label, { color: active ? ACTIVE_FG : colors.textMuted }]}>
          {SHORT_LABEL[current]}
        </Text>
      </TouchableOpacity>
      <EffortPicker
        visible={pickerVisible}
        options={options}
        current={current}
        onSelect={onChange}
        onClose={() => setPickerVisible(false)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 18,
    gap: 6,
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
  },
});
```

注意：Props 从 `{ active, onPress, disabled }` 改为 `{ current, onChange }`——这是破坏性变更，Task 19 会修改 Composer 调用方。

- [ ] **Step 2: 类型检查（预期会在 Composer 调用处报错）**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: `ThinkButton` 本身通过，但 `components/composer/index.tsx` 的调用处可能报错（Task 19 修复）

- [ ] **Step 3: 先不 commit，等 Task 19 一起提交**

（或者如果你想保持 green state，可以临时把 Composer 的调用也改掉一起提交——但本 plan 按分 Task 提交更清晰）

跳过 commit，进入 Task 19。

---

## Task 19: Composer 调用方 + `sendTurn` API 改造

**Files:**
- Modify: `ui/mobile/src/components/composer/index.tsx`
- Modify: `ui/mobile/src/api/turns.ts`

- [ ] **Step 1: 改 `sendTurn` API**

替换 `ui/mobile/src/api/turns.ts`：

```typescript
import axios from 'axios';
import { apiClient } from './client';
import type { ThinkingEffort } from '../types';

export async function sendTurn(
  sessionId: string | null,
  content: string,
  thinkingEffort: ThinkingEffort,
): Promise<{ sessionId: string; ts: string }> {
  const { data } = await apiClient.post<{ session_id: string; ts: string }>(
    '/api/v1/turns',
    {
      session_id: sessionId,
      content,
      thinking_effort: thinkingEffort === 'off' ? null : thinkingEffort,
    },
  );
  return { sessionId: data.session_id, ts: data.ts };
}

export async function cancelTurn(sessionId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/sessions/${sessionId}/cancel`);
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return;
    }
    throw err;
  }
}
```

- [ ] **Step 2: 改 Composer `onSend` 签名与 ThinkButton 调用**

修改 `ui/mobile/src/components/composer/index.tsx`：

1. `Props` 里 `onSend` 改为：

```typescript
onSend: (text: string, opts: { effort: ThinkingEffort }) => Promise<void>;
```

2. 从 store 读的改为：

```typescript
const effort = useComposerStore((s) => s.getEffort(sessionId));
const setEffort = useComposerStore((s) => s.setEffort);
```

3. `ThinkButton` 的调用改为：

```typescript
<ThinkButton current={effort} onChange={(next) => setEffort(sessionId, next)} />
```

4. 发送时：

```typescript
await onSend(content, { effort });
```

5. 顶部 import 补上 `import type { ThinkingEffort } from '../../types';`

- [ ] **Step 3: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: `composer/` 和 `ThinkButton` 通过。`app/index.tsx` 和 `app/subagents/session/[id].tsx` 的 `handleSend` 可能还有红（Task 20 修复）。

- [ ] **Step 4: 先不 commit，继续 Task 20**

---

## Task 20: ChatScreen + Sub-Agent Session 页面 —— `handleSend` 真正传 effort

**Files:**
- Modify: `ui/mobile/app/index.tsx:70`
- Modify: `ui/mobile/app/subagents/session/[id].tsx`（对应 handleSend）

- [ ] **Step 1: 改主 ChatScreen**

在 `ui/mobile/app/index.tsx` 找到 `handleSend`（约 line 70），替换为：

```typescript
async function handleSend(text: string, opts: { effort: ThinkingEffort }) {
  try {
    const { sessionId } = await sendTurn(currentSessionId, text, opts.effort);
    // ... 原有的 session id 处理逻辑保持不变
  } catch (err) {
    // 原有错误处理
  }
}
```

顶部 import 加 `import type { ThinkingEffort } from '@/src/types';`

- [ ] **Step 2: 改 Sub-Agent Session 页面**

在 `ui/mobile/app/subagents/session/[id].tsx` 做同样的改造。搜索 `handleSend` 或 `onSend`，按相同模式修复。注意这里调用的应该是 sub-agent 的 turns API（`POST /sessions/{id}/turns`），封装可能在 `src/api/sessions.ts` 或类似文件里——需要沿用 Task 19 的模式给那个 API 函数也加 `thinkingEffort` 参数。

```bash
grep -n "handleSend\|sendTurn\|onSend" ui/mobile/app/subagents/session/\[id\].tsx
grep -rn "sessions.*turns" ui/mobile/src/api/
```

找到 sub-agent 的 turns 封装函数后，按 Task 19 的模式加 `thinkingEffort` 参数并在 body 里塞 `thinking_effort` 字段。

- [ ] **Step 3: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 全部通过

- [ ] **Step 4: 提交 Task 18-20 的完整改动**

```bash
git add ui/mobile/src/api/turns.ts \
        ui/mobile/src/api/sessions.ts \
        ui/mobile/src/components/composer/ThinkButton.tsx \
        ui/mobile/src/components/composer/index.tsx \
        ui/mobile/app/index.tsx \
        ui/mobile/app/subagents/session/\[id\].tsx
git commit -m "feat(mobile): ThinkButton 与 Composer 支持 effort 档位并传递到 API"
```

> 如果 `src/api/sessions.ts` 不存在或路径不同，按 Step 2 的 grep 结果调整提交命令。

---

## Task 21: Settings 页面 —— 新增 `thinking_capability` 选择器

**Files:**
- Modify: `ui/mobile/src/components/settings/LLMProviderConfig.tsx`

- [ ] **Step 1: 读取现有 provider 表单结构**

```bash
cat ui/mobile/src/components/settings/LLMProviderConfig.tsx
```

记下现有字段（name、provider_type、api_key、model、base_url、thinking_format、is_default）的渲染方式。

- [ ] **Step 2: 在表单中新增 `thinking_capability` 字段**

在现有 `thinking_format` 下面（或对应的"高级"区块）新增一个下拉/分段选择器，选项为：

```
None（不选） / toggle / effort / adaptive / always_on
```

字段名映射：表单 state 加一个 `thinkingCapability: ThinkingCapability | null`，默认从 record 初始化，保存时包含在 POST/PUT body 的 `thinking_capability` 字段里。

给每个选项加一句中文说明提示（与 spec §3.1 capability 表对齐）：

```
none       — 模型不支持思考控制
toggle     — 只支持开/关，无档位
effort     — 支持 low/medium/high 三档
adaptive   — Anthropic Adaptive（low/medium/high/max）
always_on  — 模型必然思考，UI 固定
```

- [ ] **Step 3: 保存后触发 capability 同步**

提交表单成功（PUT/POST 返回 200/201）后，调用 `syncCurrentThinkingCapability()`，以便 UI 立刻反映新 capability + 触发 clamp。如果该 provider 成为/仍是默认 provider，clamp 会自动处理档位降级；否则是 no-op。

```typescript
import { syncCurrentThinkingCapability } from '@/src/api/llm';
// ...
await saveProvider(payload);
await syncCurrentThinkingCapability();
```

- [ ] **Step 4: 类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add ui/mobile/src/components/settings/LLMProviderConfig.tsx
git commit -m "feat(mobile): settings 页 LLM provider 表单新增 thinking_capability 选择"
```

---

## Task 22: 前端 README 更新

**Files:**
- Modify: `ui/mobile/README.md`
- Modify: `ui/mobile/src/components/composer/README.md`

- [ ] **Step 1: 更新 mobile README 修改导航表**

在 `ui/mobile/README.md` 的"修改导航"表里，把原来"修改思考按钮"那行拆成两行：

```markdown
| 修改思考档位选择器弹窗 | `src/components/composer/EffortPicker.tsx` |
| 修改思考按钮（按 capability 渲染不同形态） | `src/components/composer/ThinkButton.tsx` |
| 修改思考档位 session 状态（effort + lastUserChoice） | `src/store/composer.ts` |
| 修改当前 provider thinking_capability 同步逻辑 | `src/api/llm.ts` 的 `syncCurrentThinkingCapability` |
```

- [ ] **Step 2: 更新 composer README**

在 `ui/mobile/src/components/composer/README.md` 加一节"思考档位"：

```markdown
## 思考档位

- `ThinkButton` 根据当前默认 provider 的 `thinking_capability`（从 `useSettingsStore` 读）决定渲染形态：
  - `null` → 灰色 disabled pill
  - `none` → 不渲染
  - `toggle` → 单点切换 pill（off/on），不弹 picker
  - `effort` → pill + `EffortPicker`（off/low/medium/high）
  - `adaptive` → pill + `EffortPicker`（off/low/medium/high/max）
  - `always_on` → 不可点徽标"思考·自动"
- 选中档位存在 `useComposerStore.effortBySession`，全局最近选择存在 `lastUserChoice`（AsyncStorage 持久化）。
- Provider 切换导致 capability 变化时，`syncCurrentThinkingCapability` 会调 `clampAllToCapability` 统一降级/升级并触发 toast。
- 切换时机：effort 在 `POST /turns` 时锁定，in-flight turn 不受影响，picker 始终可点。
```

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/README.md ui/mobile/src/components/composer/README.md
git commit -m "docs(mobile): README 同步 thinking effort 相关改动"
```

---

## Task 23: 手动验证清单

**Files:** 无代码改动，仅运行手动测试

- [ ] **Step 1: 跑全量后端测试**

```bash
pytest tests/ -x --ignore=tests/e2e
```

Expected: 全部 PASS

- [ ] **Step 2: 跑前端类型检查**

```bash
cd ui/mobile && npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 3: 启动 gateway**

```bash
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
```

- [ ] **Step 4: 通过 Settings 页面创建/编辑一个 Anthropic provider**

- 设 `thinking_capability=adaptive`，设为默认
- 验证返回 200，列表显示该字段

- [ ] **Step 5: 启动模拟器并构建 App**

```bash
cd ui/mobile
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed
npx expo run:android
```

- [ ] **Step 6: 验证档位 UI**

1. 输入框点"思考"按钮 → 弹出 picker，看到 off/low/medium/high/max 五档
2. 选 high，发送"帮我分析一下这段代码的时间复杂度，给出详细推导"
3. 观察对话气泡是否出现折叠的"思考过程"卡片，展开看到推理内容 ✅

- [ ] **Step 7: 验证多轮 + signature 修复**

1. 在同一会话继续发送"那空间复杂度呢？需要用到 web_search 工具查一下最新数据"
2. 观察 sub-agent / 工具调用完成后，模型继续输出，不出现 Anthropic API 400 报错 ✅

- [ ] **Step 8: 验证 capability 切换**

1. 在 Settings 页创建一个 OpenAI provider，`thinking_capability=none`，设为默认
2. 回到 Chat 页 → 思考按钮应该消失 ✅
3. 再切回 adaptive，按钮恢复；原选中的 max 保持（因 adaptive 保留 max）

4. 再切到 `thinking_capability=effort` 的 provider → max 自动降级为 high，toast 提示 ✅

- [ ] **Step 9: 验证 always_on**

1. 创建一个 OpenAI provider，`thinking_capability=always_on`, `thinking_format=reasoning_content`（假 DeepSeek-R1）
2. 设为默认 → 按钮变成不可点"思考·自动"灰色徽标 ✅

- [ ] **Step 10: 验证 in-flight 切换**

1. 回到 adaptive provider
2. 发送一条长消息触发长时间输出
3. 输出中途点按钮改档位 → picker 正常打开，改动立即生效（写入 store），in-flight turn 不变
4. 等 in-flight turn 结束，再发一条新消息 → 使用新档位

- [ ] **Step 11: 无问题则收工**

如发现回归或 spec 未覆盖的 bug，记录到 followups 并在合适的下一个 commit 修复。

---

## Self-Review 记录

**Spec 覆盖检查：**
- §2 目标 1（前端按钮真正控制）→ Task 18, 19, 20
- §2 目标 2（四种请求形态）→ Task 4, 5
- §2 目标 3（三种边缘情况 UI）→ Task 18
- §2 目标 4（多轮 signature）→ Task 2, 4, 7
- §2 目标 5（档位动态显示）→ Task 15, 16, 18
- §3.1（capability 字段）→ Task 1, 6, 11
- §3.2（Provider 翻译表）→ Task 4, 5
- §3.3（API 协议）→ Task 9, 10, 11, 16, 19
- §3.4（链路透传）→ Task 3, 7, 8, 9, 10
- §3.5（signature 修复）→ Task 2, 4, 7
- §3.6（前端档位 UI + 能力来源）→ Task 13, 14, 15, 16, 17, 18
- §3.7（sub-agent 路由）→ Task 10, 20
- §3.7.1（capability clamp 矩阵）→ Task 14 的 `clampOne`
- §3.8（切换时机）→ Task 14（无 in-flight 状态判断）+ Task 23 Step 10 验证

**类型一致性：** `ThinkingEffort` / `ThinkingCapability` / `thinking_capability` / `thinking_effort` / `EFFORT_LEVELS_BY_CAPABILITY` 在前后端命名一致。

**占位符：** 无 TBD/TODO。

---

*本计划 v1.0, 2026-04-08。*

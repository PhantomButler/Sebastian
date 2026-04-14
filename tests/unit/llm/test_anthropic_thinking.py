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


def test_effort_max_raises_for_capability_effort() -> None:
    """capability='effort' 下传入 'max' 应抛 ValueError（'max' 仅 adaptive 允许）。"""
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-test", thinking_capability="effort")
    with pytest.raises(ValueError, match="max.*not allowed.*effort"):
        provider._build_thinking_kwargs("max", max_tokens=8192)


def test_effort_budget_exceeds_max_tokens_raises() -> None:
    """effort='high' (budget=24576) 但 max_tokens=8192 时应抛 ValueError。"""
    from sebastian.llm.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-test", thinking_capability="effort")
    with pytest.raises(ValueError, match="budget_tokens.*max_tokens"):
        provider._build_thinking_kwargs("high", max_tokens=8192)

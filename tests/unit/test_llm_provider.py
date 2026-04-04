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


@pytest.mark.asyncio
async def test_openai_compat_provider_streams_text_and_ends() -> None:
    from unittest.mock import AsyncMock, MagicMock

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

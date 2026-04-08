from __future__ import annotations

from unittest.mock import MagicMock

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
        def __init__(self) -> None:
            self._yielded = False

        def __aiter__(self) -> "AsyncIter":
            return self

        async def __anext__(self) -> MagicMock:
            if self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return chunk

    async def _create(**kwargs: object) -> AsyncIter:
        return AsyncIter()

    return _create


@pytest.mark.asyncio
async def test_openai_effort_high_passes_reasoning_effort() -> None:
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="fake", thinking_capability="effort")
    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object):
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
    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object):
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
    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object):
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


def _build_reasoning_then_text_stream():
    """Yield: reasoning chunk → text chunk → stop chunk."""

    def _make_chunk(
        *,
        reasoning: str | None = None,
        content: str | None = None,
        finish: str | None = None,
    ) -> MagicMock:
        chunk = MagicMock()
        choice = MagicMock()
        choice.finish_reason = finish
        choice.delta.content = content
        choice.delta.reasoning_content = reasoning
        choice.delta.tool_calls = None
        chunk.choices = [choice]
        return chunk

    chunks = [
        _make_chunk(reasoning="let me "),
        _make_chunk(reasoning="think..."),
        _make_chunk(content="answer"),
        _make_chunk(finish="stop"),
    ]

    class AsyncIter:
        def __init__(self) -> None:
            self._i = 0

        def __aiter__(self) -> "AsyncIter":
            return self

        async def __anext__(self) -> MagicMock:
            if self._i >= len(chunks):
                raise StopAsyncIteration
            c = chunks[self._i]
            self._i += 1
            return c

    async def _create(**kwargs: object) -> AsyncIter:
        return AsyncIter()

    return _create


@pytest.mark.asyncio
async def test_openai_effort_plus_reasoning_content_combo() -> None:
    """effort capability + reasoning_content format: both inject reasoning_effort
    and parse delta.reasoning_content into ThinkingBlockStart/Delta/Stop."""
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        api_key="fake",
        thinking_capability="effort",
        thinking_format="reasoning_content",
    )
    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object):
        captured.update(kwargs)
        stream = _build_reasoning_then_text_stream()
        return await stream(**kwargs)

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    events = []
    async for ev in provider.stream(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="deepseek-r1",
        max_tokens=4096,
        thinking_effort="medium",
    ):
        events.append(ev)

    assert captured.get("reasoning_effort") == "medium"

    types = [type(ev).__name__ for ev in events]
    assert "ThinkingBlockStart" in types
    assert "ThinkingDelta" in types
    assert "ThinkingBlockStop" in types
    assert "TextBlockStart" in types
    assert "TextDelta" in types
    assert "TextBlockStop" in types

    # Order: thinking fully emitted before text block starts
    think_start = types.index("ThinkingBlockStart")
    think_stop = types.index("ThinkingBlockStop")
    text_start = types.index("TextBlockStart")
    assert think_start < think_stop
    assert think_stop > text_start or think_start < text_start  # think started first

    # Verify accumulated thinking text
    stop_ev = next(ev for ev in events if type(ev).__name__ == "ThinkingBlockStop")
    assert stop_ev.thinking == "let me think..."

    text_stop = next(ev for ev in events if type(ev).__name__ == "TextBlockStop")
    assert text_stop.text == "answer"


@pytest.mark.asyncio
async def test_openai_toggle_capability_is_noop() -> None:
    """OpenAI path: toggle capability is no-op (spec §3.2)."""
    from sebastian.llm.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="fake", thinking_capability="toggle")
    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object):
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

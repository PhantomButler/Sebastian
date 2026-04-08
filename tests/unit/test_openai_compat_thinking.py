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

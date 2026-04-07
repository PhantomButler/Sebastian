from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import TextDelta


async def _async_iter(items: list[Any]):
    for item in items:
        yield item


def _make_registry(provider: Any, model: str = "claude-haiku-4-5-20251001") -> MagicMock:
    registry = MagicMock()
    registry.get_default_with_model = AsyncMock(return_value=(provider, model))
    return registry


def _make_provider(response_text: str) -> MagicMock:
    provider = MagicMock()
    provider.stream = MagicMock(
        return_value=_async_iter([TextDelta(block_id="0", delta=response_text)])
    )
    return provider


@pytest.mark.asyncio
async def test_reviewer_returns_proceed_on_safe_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider('{"decision": "proceed", "explanation": ""}')
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "cat /etc/hosts"},
        reason="Reading hosts file to debug DNS issue",
        task_goal="Debug network connectivity",
    )

    assert decision.decision == "proceed"
    assert decision.explanation == ""
    registry.get_default_with_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_reviewer_returns_escalate_on_risky_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider(
        '{"decision": "escalate", "explanation": "此命令将永久删除文件，请确认。"}'
    )
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "rm -rf /tmp/old_data"},
        reason="Cleaning up temp files",
        task_goal="Summarize today's news",
    )

    assert decision.decision == "escalate"
    assert "删除" in decision.explanation


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_provider_error() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = MagicMock()

    def _raising(*args: Any, **kwargs: Any):
        async def _gen():
            raise RuntimeError("API error")
            yield  # pragma: no cover
        return _gen()

    provider.stream = _raising
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "ls"},
        reason="List files",
        task_goal="Find config file",
    )

    assert decision.decision == "escalate"
    assert decision.explanation != ""


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_invalid_json() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider("not valid json")
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="file_write",
        tool_input={"path": "/tmp/out.txt", "content": "data"},
        reason="Write output",
        task_goal="Generate report",
    )

    assert decision.decision == "escalate"


@pytest.mark.asyncio
async def test_reviewer_escalates_when_no_provider_configured() -> None:
    """Lazy resolution: if registry raises RuntimeError (no provider), escalate safely."""
    from sebastian.permissions.reviewer import PermissionReviewer

    registry = MagicMock()
    registry.get_default_with_model = AsyncMock(
        side_effect=RuntimeError("No default LLM provider configured.")
    )

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "ls"},
        reason="List files",
        task_goal="Any goal",
    )

    assert decision.decision == "escalate"
    assert "Provider" in decision.explanation or "provider" in decision.explanation


@pytest.mark.asyncio
async def test_reviewer_passes_context_to_llm() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider('{"decision": "proceed", "explanation": ""}')
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    await reviewer.review(
        tool_name="shell",
        tool_input={"command": "pwd"},
        reason="Check working directory",
        task_goal="Debug file path issue",
    )

    call_kwargs = provider.stream.call_args
    user_content = call_kwargs.kwargs["messages"][0]["content"]
    assert "shell" in user_content
    assert "pwd" in user_content
    assert "Check working directory" in user_content
    assert "Debug file path issue" in user_content

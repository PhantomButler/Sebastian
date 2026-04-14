from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import TextDelta


async def _async_iter(items: list[Any]) -> AsyncGenerator[Any, None]:
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


@pytest.mark.asyncio
async def test_reviewer_handles_markdown_wrapped_json() -> None:
    """Model wraps JSON in ```json code fences — should still parse correctly."""
    from sebastian.permissions.reviewer import PermissionReviewer

    wrapped = '```json\n{\n  "decision": "proceed",\n  "explanation": ""\n}\n```'
    provider = _make_provider(wrapped)
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="bash",
        tool_input={"command": "pwd"},
        reason="Check working directory",
        task_goal="查看当前工作目录",
    )

    assert decision.decision == "proceed"


@pytest.mark.asyncio
async def test_reviewer_escalates_on_empty_response() -> None:
    """Empty stream response escalates safely without raising an exception."""
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider("")
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="bash",
        tool_input={"command": "ls"},
        reason="List files",
        task_goal="Find config",
    )

    assert decision.decision == "escalate"


@pytest.mark.asyncio
async def test_reviewer_system_prompt_contains_workspace_dir() -> None:
    """review() 构建的 system prompt 包含真实 workspace_dir 路径。"""
    from pathlib import Path
    from unittest.mock import patch

    from sebastian.permissions.reviewer import PermissionReviewer

    fake_workspace = Path("/fake/workspace/path")
    captured_prompts: list[str] = []

    provider = MagicMock()

    async def _capturing_stream(*args, **kwargs):
        captured_prompts.append(kwargs.get("system", ""))
        yield TextDelta(block_id="0", delta='{"decision": "proceed", "explanation": ""}')

    provider.stream = _capturing_stream
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)

    with patch("sebastian.permissions.reviewer.settings") as mock_settings:
        mock_settings.workspace_dir = fake_workspace
        await reviewer.review(
            tool_name="Bash",
            tool_input={"command": "echo hello"},
            reason="test",
            task_goal="test goal",
        )

    assert captured_prompts, "stream was not called"
    assert str(fake_workspace) in captured_prompts[0]

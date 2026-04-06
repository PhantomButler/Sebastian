# tests/unit/test_permission_reviewer.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_reviewer_returns_proceed_on_safe_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"decision": "proceed", "explanation": ""}')]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "cat /etc/hosts"},
        reason="Reading hosts file to debug DNS issue",
        task_goal="Debug network connectivity",
    )

    assert decision.decision == "proceed"
    assert decision.explanation == ""


@pytest.mark.asyncio
async def test_reviewer_returns_escalate_on_risky_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(
            text='{"decision": "escalate", "explanation": "此命令将永久删除文件，请确认。"}'
        )
    ]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "rm -rf /tmp/old_data"},
        reason="Cleaning up temp files",
        task_goal="Summarize today's news",
    )

    assert decision.decision == "escalate"
    assert "删除" in decision.explanation


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_api_error() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API error"))

    reviewer = PermissionReviewer(client=mock_client)
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

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="not valid json")]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    decision = await reviewer.review(
        tool_name="file_write",
        tool_input={"path": "/tmp/out.txt", "content": "data"},
        reason="Write output",
        task_goal="Generate report",
    )

    assert decision.decision == "escalate"


@pytest.mark.asyncio
async def test_reviewer_passes_context_to_llm() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"decision": "proceed", "explanation": ""}')]
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    reviewer = PermissionReviewer(client=mock_client)
    await reviewer.review(
        tool_name="shell",
        tool_input={"command": "pwd"},
        reason="Check working directory",
        task_goal="Debug file path issue",
    )

    call_kwargs = mock_client.messages.create.call_args
    user_content = call_kwargs.kwargs["messages"][0]["content"]
    assert "shell" in user_content
    assert "pwd" in user_content
    assert "Check working directory" in user_content
    assert "Debug file path issue" in user_content

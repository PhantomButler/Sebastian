from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_text_response(text: str):
    """Build a mock Anthropic messages.create response that returns text."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def _make_tool_response(tool_id: str, tool_name: str, tool_input: dict):
    """Build a mock response requesting a single tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_agent_loop_no_tools():
    """When the model responds with text immediately, return that text."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_make_text_response("Hello there!"))

    reg = CapabilityRegistry()
    loop = AgentLoop(mock_client, reg)
    result = await loop.run(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "Hi"}],
    )
    assert result == "Hello there!"


@pytest.mark.asyncio
async def test_agent_loop_single_tool_call():
    """Loop should call the tool and then return the final text response."""
    from sebastian.capabilities.registry import CapabilityRegistry
    from sebastian.core.agent_loop import AgentLoop
    from sebastian.core import tool as tool_module
    from sebastian.core.tool import tool
    from sebastian.core.types import ToolResult

    tool_module._tools.clear()

    @tool(name="echo_loop_test", description="Echo")
    async def echo_tool(msg: str) -> ToolResult:
        return ToolResult(ok=True, output=f"echoed: {msg}")

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=[
        _make_tool_response("call-1", "echo_loop_test", {"msg": "hi"}),
        _make_text_response("Done, I echoed hi."),
    ])

    reg = CapabilityRegistry()
    loop = AgentLoop(mock_client, reg)
    result = await loop.run(
        system_prompt="sys",
        messages=[{"role": "user", "content": "echo hi"}],
    )
    assert "Done" in result
    assert mock_client.messages.create.call_count == 2

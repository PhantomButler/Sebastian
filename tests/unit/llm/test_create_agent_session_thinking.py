"""run_agent_session thinking_effort 透传测试。

覆盖修复：sub-agent 新会话首条消息此前永远不开思考的 bug。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.session_runner import run_agent_session
from sebastian.core.types import Session


@pytest.mark.asyncio
async def test_run_agent_session_passes_thinking_effort() -> None:
    """run_agent_session 应将 thinking_effort 透传到 agent.run_streaming。"""
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value=None)
    session = Session(agent_type="code", title="t", goal="g", depth=2)

    await run_agent_session(
        agent=agent,
        session=session,
        goal="hello",
        session_store=AsyncMock(),
        index_store=AsyncMock(),
        event_bus=None,
        thinking_effort="high",
    )

    agent.run_streaming.assert_awaited_once_with("hello", session.id, thinking_effort="high")


@pytest.mark.asyncio
async def test_run_agent_session_default_none() -> None:
    """未提供 thinking_effort 时应传 None 给 agent.run_streaming。"""
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value=None)
    session = Session(agent_type="code", title="t", goal="g", depth=2)

    await run_agent_session(
        agent=agent,
        session=session,
        goal="hello",
        session_store=AsyncMock(),
        index_store=AsyncMock(),
        event_bus=None,
    )

    agent.run_streaming.assert_awaited_once_with("hello", session.id, thinking_effort=None)

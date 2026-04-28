"""run_agent_session 测试。

A4 后：thinking_effort 不再透传给 run_agent_session / agent.run_streaming。
agent 内部通过 llm_registry.get_provider() 自行读取 ResolvedProvider 中的配置。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.session_runner import run_agent_session
from sebastian.core.types import Session


@pytest.mark.asyncio
async def test_run_agent_session_calls_run_streaming_without_thinking_effort() -> None:
    """run_agent_session 调用 agent.run_streaming(goal, session_id)，不传 thinking_effort 参数。
    thinking_effort 由 agent 内部从 llm_registry.get_provider() 读取。
    """
    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value=None)
    session = Session(agent_type="code", title="t", goal="g", depth=2)

    await run_agent_session(
        agent=agent,
        session=session,
        goal="hello",
        session_store=AsyncMock(),
        event_bus=None,
    )

    agent.run_streaming.assert_awaited_once_with(
        "hello", session.id, persist_user_message=True, preallocated_exchange=None
    )


@pytest.mark.asyncio
async def test_run_agent_session_no_thinking_effort_param() -> None:
    """run_agent_session 签名不再含 thinking_effort 参数。"""
    import inspect

    sig = inspect.signature(run_agent_session)
    assert "thinking_effort" not in sig.parameters

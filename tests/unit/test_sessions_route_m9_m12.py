from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.types import Session


@pytest.mark.asyncio
async def test_log_background_turn_failure_noop_on_success() -> None:
    """_log_background_turn_failure 对成功 task 不抛出。"""
    from sebastian.gateway.routes.sessions import _log_background_turn_failure

    async def ok() -> str:
        return "done"

    task = asyncio.create_task(ok())
    await task
    _log_background_turn_failure(task)  # should not raise


@pytest.mark.asyncio
async def test_log_background_turn_failure_logs_on_error() -> None:
    """_log_background_turn_failure 在任务抛异常时记录日志（不重新抛出）。"""
    from sebastian.gateway.routes.sessions import _log_background_turn_failure

    async def fail() -> None:
        raise RuntimeError("boom")

    task = asyncio.create_task(fail())
    try:
        await task
    except RuntimeError:
        pass

    # Should not raise, only log
    _log_background_turn_failure(task)


def test_schedule_session_turn_sub_agent_no_agent_name() -> None:
    """Verify that _schedule_session_turn calls agent.run_streaming WITHOUT agent_name kwarg.

    This test reads the actual source code to verify the fix is in place.
    """
    import inspect
    from sebastian.gateway.routes.sessions import _schedule_session_turn

    # Get the source code of _schedule_session_turn
    source = inspect.getsource(_schedule_session_turn)

    # Verify that the line calling agent.run_streaming does NOT have agent_name=session.agent_type
    # The corrected code should be: agent.run_streaming(content, session.id)
    # NOT: agent.run_streaming(content, session.id, agent_name=session.agent_type)

    lines = source.split("\n")
    run_streaming_line = None
    for line in lines:
        if "agent.run_streaming" in line and "agent_name=" not in line:
            run_streaming_line = line
            break

    assert run_streaming_line is not None, (
        "Expected to find agent.run_streaming(content, session.id) without agent_name kwarg. "
        "Verify the M12 fix was applied correctly."
    )

    # Make sure no other agent.run_streaming calls have agent_name
    for line in lines:
        if "agent.run_streaming" in line and "session.agent_type" in line:
            assert "agent_name=" not in line, (
                "Found agent.run_streaming call with agent_name=session.agent_type kwarg. "
                "This should have been removed in the M12 fix."
            )

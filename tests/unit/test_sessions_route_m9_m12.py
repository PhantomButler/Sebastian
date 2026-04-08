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


@pytest.mark.asyncio
async def test_schedule_session_turn_sub_agent_no_agent_name() -> None:
    """_schedule_session_turn 调用 sub-agent 的 run_streaming 时不传 agent_name。"""
    import sys
    import types
    import sebastian.gateway.routes.sessions as mod

    session = MagicMock(spec=Session)
    session.agent_type = "code"
    session.id = "sess-test"

    mock_agent = MagicMock()
    mock_agent.run_streaming = AsyncMock(return_value="ok")

    fake_state = types.ModuleType("sebastian.gateway.state")
    fake_state.agent_instances = {"code": mock_agent}  # type: ignore[attr-defined]
    fake_state.session_store = AsyncMock()  # type: ignore[attr-defined]
    fake_state.index_store = AsyncMock()  # type: ignore[attr-defined]
    fake_state.event_bus = AsyncMock()  # type: ignore[attr-defined]
    fake_state.sebastian = MagicMock()  # type: ignore[attr-defined]

    import sebastian.gateway as gw_pkg

    original = sys.modules.get("sebastian.gateway.state")
    original_attr = getattr(gw_pkg, "state", None)
    sys.modules["sebastian.gateway.state"] = fake_state
    gw_pkg.state = fake_state  # type: ignore[attr-defined]
    try:
        await mod._schedule_session_turn(session, "hello")
        await asyncio.sleep(0)  # let background task run
    finally:
        if original is not None:
            sys.modules["sebastian.gateway.state"] = original
        else:
            sys.modules.pop("sebastian.gateway.state", None)
        if original_attr is not None:
            gw_pkg.state = original_attr  # type: ignore[attr-defined]
        else:
            gw_pkg.__dict__.pop("state", None)

    # Verify run_streaming was called exactly once, without agent_name kwarg
    mock_agent.run_streaming.assert_awaited_once_with(
        "hello", "sess-test", thinking_effort=None
    )


@pytest.mark.asyncio
async def test_log_background_turn_failure_noop_on_cancelled() -> None:
    """_log_background_turn_failure 在任务被取消时静默跳过。"""
    from sebastian.gateway.routes.sessions import _log_background_turn_failure

    async def cancellable() -> None:
        await asyncio.sleep(100)

    task = asyncio.create_task(cancellable())
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    _log_background_turn_failure(task)  # should not raise

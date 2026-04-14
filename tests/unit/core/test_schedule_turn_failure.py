from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.types import Session, SessionStatus


@pytest.mark.asyncio
async def test_turn_done_callback_sets_failed_on_exception() -> None:
    """done callback 在任务抛异常时把 session.status 设为 FAILED。"""
    from sebastian.gateway.routes.sessions import _make_turn_done_callback

    session = MagicMock(spec=Session)
    session.id = "sess-1"
    session.agent_type = "code"
    session.status = SessionStatus.ACTIVE

    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()

    cb = _make_turn_done_callback(session, session_store, index_store, event_bus)

    async def fail_task() -> None:
        raise RuntimeError("oops")

    task = asyncio.create_task(fail_task())
    try:
        await task
    except RuntimeError:
        pass

    cb(task)
    assert session.status == SessionStatus.FAILED

    # Let the background persist task run
    await asyncio.sleep(0.01)
    session_store.update_session.assert_awaited_once()
    index_store.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_turn_done_callback_sets_cancelled_on_cancel() -> None:
    """done callback 在任务被取消时把 session.status 设为 CANCELLED。"""
    from sebastian.gateway.routes.sessions import _make_turn_done_callback

    session = MagicMock(spec=Session)
    session.id = "sess-2"
    session.agent_type = "code"
    session.status = SessionStatus.ACTIVE

    session_store = AsyncMock()
    index_store = AsyncMock()
    event_bus = AsyncMock()
    cb = _make_turn_done_callback(session, session_store, index_store, event_bus)

    async def cancellable() -> None:
        await asyncio.sleep(100)

    task = asyncio.create_task(cancellable())
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    cb(task)
    assert session.status == SessionStatus.CANCELLED

    await asyncio.sleep(0.01)
    session_store.update_session.assert_awaited_once()
    index_store.upsert.assert_awaited_once()
    event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_turn_done_callback_noop_on_success() -> None:
    """done callback 在任务正常完成时不修改 session status。"""
    from sebastian.gateway.routes.sessions import _make_turn_done_callback

    session = MagicMock(spec=Session)
    session.id = "sess-3"
    session.agent_type = "code"
    session.status = SessionStatus.ACTIVE

    session_store = AsyncMock()
    cb = _make_turn_done_callback(session, session_store, AsyncMock(), AsyncMock())

    async def ok_task() -> str:
        return "done"

    task = asyncio.create_task(ok_task())
    await task
    cb(task)

    assert session.status == SessionStatus.ACTIVE
    session_store.update_session.assert_not_called()

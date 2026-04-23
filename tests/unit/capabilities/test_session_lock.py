from __future__ import annotations

import asyncio

import pytest

from sebastian.capabilities.tools import _session_lock as lock_mod
from sebastian.capabilities.tools._session_lock import (
    get_session_lock,
    release_session_lock,
)


@pytest.fixture(autouse=True)
def _clear_locks():
    lock_mod._SESSION_LOCKS.clear()
    yield
    lock_mod._SESSION_LOCKS.clear()


def test_get_session_lock_is_stable_per_session() -> None:
    a = get_session_lock("s1")
    b = get_session_lock("s1")
    assert a is b


def test_release_drops_unheld_lock() -> None:
    get_session_lock("s1")
    release_session_lock("s1")
    assert "s1" not in lock_mod._SESSION_LOCKS


def test_release_noop_when_session_absent() -> None:
    release_session_lock("never")  # 不应抛异常


@pytest.mark.asyncio
async def test_release_preserves_lock_when_currently_held() -> None:
    lock = get_session_lock("s1")
    async with lock:
        release_session_lock("s1")
        # 持锁时保留，避免破坏 in-flight 临界区
        assert "s1" in lock_mod._SESSION_LOCKS
    # 锁释放后再调用即可回收
    release_session_lock("s1")
    assert "s1" not in lock_mod._SESSION_LOCKS


@pytest.mark.asyncio
async def test_session_runner_releases_lock_on_terminal_status(tmp_path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.core.session_runner import run_agent_session
    from sebastian.core.types import Session

    get_session_lock("s-done")
    assert "s-done" in lock_mod._SESSION_LOCKS

    agent = MagicMock()
    agent.run_streaming = AsyncMock(return_value="ok")
    session = Session(id="s-done", agent_type="code", title="t", depth=2)

    await run_agent_session(
        agent=agent,
        session=session,
        goal="g",
        session_store=AsyncMock(),
        event_bus=None,
    )

    assert "s-done" not in lock_mod._SESSION_LOCKS


@pytest.mark.asyncio
async def test_session_runner_keeps_lock_on_stop(tmp_path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.core.session_runner import run_agent_session
    from sebastian.core.types import Session

    get_session_lock("s-stop")

    agent = MagicMock()
    agent.run_streaming = AsyncMock(side_effect=asyncio.CancelledError())
    agent.consume_cancel_intent = MagicMock(return_value="stop")
    session = Session(id="s-stop", agent_type="code", title="t", depth=2)

    await run_agent_session(
        agent=agent,
        session=session,
        goal="g",
        session_store=AsyncMock(),
        event_bus=None,
    )

    # stop 分支由 stop_agent 负责；IDLE 可能被 resume，锁必须保留
    assert "s-stop" in lock_mod._SESSION_LOCKS

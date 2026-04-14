from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stalled_watchdog import _check_stalled_sessions


@pytest.mark.asyncio
async def test_marks_stalled_session():
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "status": "active",
                "last_activity_at": old,
                "depth": 2,
            },
        ]
    )
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(
        return_value=MagicMock(
            id="s1",
            status="active",
            last_activity_at=now - timedelta(minutes=10),
            goal="analyze stock market",
        )
    )
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert len(stalled) == 1
    assert stalled[0] == "s1"
    session_store.update_session.assert_awaited_once()
    event_bus.publish.assert_awaited_once()
    publish_call = event_bus.publish.call_args[0][0]
    assert publish_call.data.get("goal") == "analyze stock market"


@pytest.mark.asyncio
async def test_completed_session_not_marked() -> None:
    """非 active 状态的 session 不被误标为 stalled。"""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "status": "completed",
                "last_activity_at": old,
                "depth": 2,
            },
        ]
    )
    session_store = AsyncMock()
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    session_store.get_session.assert_not_awaited()
    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_threshold_boundary_below_not_stalled() -> None:
    """4m59s 未活动（< threshold 5m）不标 stalled。"""
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=4, seconds=59)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "status": "active",
                "last_activity_at": recent,
                "depth": 2,
            },
        ]
    )
    session_store = AsyncMock()
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_threshold_boundary_above_stalled() -> None:
    """5m1s 未活动（> threshold 5m）标为 stalled。"""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=5, seconds=1)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": "s2",
                "agent_type": "code",
                "status": "active",
                "last_activity_at": old,
                "depth": 2,
            },
        ]
    )
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(
        return_value=MagicMock(
            id="s2",
            status="active",
            last_activity_at=now - timedelta(minutes=5, seconds=1),
            goal="test goal",
        )
    )
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == ["s2"]
    session_store.update_session.assert_awaited_once()
    index_store.upsert.assert_awaited_once()
    event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_last_activity_at_skipped() -> None:
    """last_activity_at 为空字符串时跳过，不报错。"""
    index_store = AsyncMock()
    index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "status": "active",
                "last_activity_at": "",
                "depth": 2,
            },
        ]
    )
    session_store = AsyncMock()
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    session_store.get_session.assert_not_awaited()
    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_session_none_skipped() -> None:
    """session_store.get_session 返回 None 时跳过，不调 index_store.upsert。"""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "status": "active",
                "last_activity_at": old,
                "depth": 2,
            },
        ]
    )
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(return_value=None)
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert stalled == []
    index_store.upsert.assert_not_awaited()
    event_bus.publish.assert_not_awaited()

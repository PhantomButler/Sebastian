import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from sebastian.core.stalled_watchdog import _check_stalled_sessions


@pytest.mark.asyncio
async def test_marks_stalled_session():
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=10)).isoformat()

    index_store = AsyncMock()
    index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "status": "active", "last_activity_at": old, "depth": 2},
    ])
    session_store = AsyncMock()
    session_store.get_session = AsyncMock(return_value=MagicMock(
        id="s1", status="active", last_activity_at=now - timedelta(minutes=10),
    ))
    event_bus = AsyncMock()
    registry = {"code": MagicMock(stalled_threshold_minutes=5)}

    stalled = await _check_stalled_sessions(index_store, session_store, event_bus, registry)
    assert len(stalled) == 1
    assert stalled[0] == "s1"
    session_store.update_session.assert_awaited_once()

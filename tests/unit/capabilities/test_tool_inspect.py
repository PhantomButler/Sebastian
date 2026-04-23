from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_inspect_session_returns_messages():
    from sebastian.capabilities.tools.inspect_session import inspect_session

    mock_state = MagicMock()
    mock_state.session_store = AsyncMock()
    mock_state.session_store.list_sessions = AsyncMock(
        return_value=[
            {"id": "s1", "agent_type": "code", "depth": 2, "status": "active", "title": "写测试"},
        ]
    )
    mock_state.session_store.get_session = AsyncMock(
        return_value=MagicMock(
            id="s1",
            agent_type="code",
            status="active",
            title="写测试",
            last_activity_at="2026-04-06T10:00:00",
            goal="写单元测试",
        )
    )
    mock_state.session_store.get_recent_timeline_items = AsyncMock(
        return_value=[
            {
                "kind": "user_message",
                "role": "user",
                "content": "请写单元测试",
                "seq": 1,
                "created_at": "2026-04-06T10:00:00",
            },
            {
                "kind": "assistant_message",
                "role": "assistant",
                "content": "好的，我来写",
                "seq": 2,
                "created_at": "2026-04-06T10:00:05",
            },
        ]
    )

    with patch("sebastian.capabilities.tools.inspect_session._get_state", return_value=mock_state):
        result = await inspect_session(session_id="s1", recent_n=5)

    assert result.ok is True
    assert "写测试" in result.output
    assert "请写单元测试" in result.output

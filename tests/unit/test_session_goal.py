from __future__ import annotations

import pytest
from sebastian.core.types import Session


def test_session_has_goal_field() -> None:
    s = Session(agent_type="code", title="test", goal="write unit tests")
    assert s.goal == "write unit tests"


def test_session_goal_defaults_to_empty() -> None:
    s = Session(agent_type="code", title="test")
    assert s.goal == ""


def test_session_goal_persists_in_json_roundtrip() -> None:
    s = Session(agent_type="code", title="test", goal="analyze stock prices")
    data = s.model_dump()
    s2 = Session(**data)
    assert s2.goal == "analyze stock prices"


@pytest.mark.asyncio
async def test_check_sub_agents_includes_goal_and_activity() -> None:
    """check_sub_agents 的输出应包含 goal 和 last_activity_at。"""
    from unittest.mock import AsyncMock, MagicMock, patch
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents
    from sebastian.permissions.types import ToolCallContext

    mock_state = MagicMock()
    mock_state.index_store = AsyncMock()
    mock_state.index_store.list_all = AsyncMock(return_value=[
        {
            "id": "child1",
            "agent_type": "code",
            "depth": 3,
            "parent_session_id": "parent1",
            "status": "active",
            "title": "write tests",
            "goal": "write unit tests for auth module",
            "last_activity_at": "2026-04-07T10:00:00+00:00",
        }
    ])

    ctx = ToolCallContext(
        task_goal="check workers", session_id="parent1",
        task_id=None, agent_type="code", depth=2,
    )

    with patch("sebastian.capabilities.tools.check_sub_agents._get_state", return_value=mock_state):
        result = await check_sub_agents(_ctx=ctx)

    assert result.ok
    assert "write unit tests for auth module" in result.output
    assert "2026-04-07T10:00:00" in result.output

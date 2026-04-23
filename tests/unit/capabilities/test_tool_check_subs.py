from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.tool_context import _current_tool_ctx
from sebastian.permissions.types import ToolCallContext


@pytest.mark.asyncio
async def test_check_sub_agents_as_sebastian():
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents

    mock_state = MagicMock()
    mock_state.session_store = AsyncMock()
    mock_state.session_store.list_sessions = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "depth": 2,
                "parent_session_id": "seb1",
                "status": "active",
                "title": "写代码",
            },
            {
                "id": "s2",
                "agent_type": "stock",
                "depth": 2,
                "parent_session_id": "seb1",
                "status": "completed",
                "title": "看行情",
            },
            # depth=3 — should be excluded
            {
                "id": "s3",
                "agent_type": "code",
                "depth": 3,
                "parent_session_id": "seb1",
                "status": "active",
                "title": "子任务",
            },
            # Different parent session — should be excluded
            {
                "id": "s4",
                "agent_type": "code",
                "depth": 2,
                "parent_session_id": "other_seb",
                "status": "active",
                "title": "历史任务",
            },
        ]
    )

    ctx = ToolCallContext(
        task_goal="check progress",
        session_id="seb1",
        task_id=None,
        agent_type="sebastian",
        depth=1,
    )

    token = _current_tool_ctx.set(ctx)
    try:
        with patch(
            "sebastian.capabilities.tools.check_sub_agents._get_state", return_value=mock_state
        ):
            result = await check_sub_agents()
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is True
    assert "写代码" in result.output
    assert "看行情" in result.output
    assert "子任务" not in result.output  # wrong depth
    assert "历史任务" not in result.output  # different parent session


@pytest.mark.asyncio
async def test_check_sub_agents_as_leader():
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents

    mock_state = MagicMock()
    mock_state.session_store = AsyncMock()
    mock_state.session_store.list_sessions = AsyncMock(
        return_value=[
            {
                "id": "s1",
                "agent_type": "code",
                "depth": 3,
                "parent_session_id": "leader_session",
                "status": "active",
                "title": "子任务A",
            },
            {
                "id": "s2",
                "agent_type": "code",
                "depth": 3,
                "parent_session_id": "leader_session",
                "status": "completed",
                "title": "子任务B",
            },
            # Different agent_type — should be excluded
            {
                "id": "s3",
                "agent_type": "stock",
                "depth": 3,
                "parent_session_id": "leader_session",
                "status": "active",
                "title": "股票任务",
            },
            # Depth 2 — should be excluded
            {
                "id": "s4",
                "agent_type": "code",
                "depth": 2,
                "parent_session_id": None,
                "status": "active",
                "title": "组长任务",
            },
            # Different parent — should be excluded (another leader's child)
            {
                "id": "s5",
                "agent_type": "code",
                "depth": 3,
                "parent_session_id": "other_leader",
                "status": "active",
                "title": "他人子任务",
            },
        ]
    )

    ctx = ToolCallContext(
        task_goal="check workers",
        session_id="leader_session",
        task_id=None,
        agent_type="code",
        depth=2,
    )

    token = _current_tool_ctx.set(ctx)
    try:
        with patch(
            "sebastian.capabilities.tools.check_sub_agents._get_state", return_value=mock_state
        ):
            result = await check_sub_agents()
    finally:
        _current_tool_ctx.reset(token)

    assert result.ok is True
    assert "子任务A" in result.output
    assert "子任务B" in result.output
    assert "股票任务" not in result.output  # wrong agent_type
    assert "组长任务" not in result.output  # wrong depth
    assert "他人子任务" not in result.output  # different parent


@pytest.mark.asyncio
async def test_check_sub_agents_no_context():
    """Without ContextVar set, tool returns error."""
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents

    result = await check_sub_agents()

    assert result.ok is False
    assert "上下文" in result.error

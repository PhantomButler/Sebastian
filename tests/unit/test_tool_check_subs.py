import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sebastian.permissions.types import ToolCallContext


@pytest.mark.asyncio
async def test_check_sub_agents_as_sebastian():
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents

    mock_state = MagicMock()
    mock_state.index_store = AsyncMock()
    mock_state.index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "depth": 2, "status": "active", "title": "写代码"},
        {"id": "s2", "agent_type": "stock", "depth": 2, "status": "completed", "title": "看行情"},
        {"id": "s3", "agent_type": "code", "depth": 3, "status": "active", "title": "子任务"},
    ])

    ctx = ToolCallContext(
        task_goal="check progress", session_id="seb1",
        task_id=None, agent_type="sebastian", depth=1,
    )

    with patch("sebastian.capabilities.tools.check_sub_agents._get_state", return_value=mock_state):
        result = await check_sub_agents(_ctx=ctx)

    assert result.ok is True
    assert "写代码" in result.output
    assert "看行情" in result.output
    assert "子任务" not in result.output


@pytest.mark.asyncio
async def test_check_sub_agents_as_leader():
    from sebastian.capabilities.tools.check_sub_agents import check_sub_agents

    mock_state = MagicMock()
    mock_state.index_store = AsyncMock()
    mock_state.index_store.list_all = AsyncMock(return_value=[
        {"id": "s1", "agent_type": "code", "depth": 3, "status": "active", "title": "子任务A"},
        {"id": "s2", "agent_type": "code", "depth": 3, "status": "completed", "title": "子任务B"},
        # Different agent_type — should be excluded
        {"id": "s3", "agent_type": "stock", "depth": 3, "status": "active", "title": "股票任务"},
        # Depth 2 — should be excluded
        {"id": "s4", "agent_type": "code", "depth": 2, "status": "active", "title": "组长任务"},
    ])

    ctx = ToolCallContext(
        task_goal="check workers", session_id="leader_session",
        task_id=None, agent_type="code", depth=2,
    )

    with patch("sebastian.capabilities.tools.check_sub_agents._get_state", return_value=mock_state):
        result = await check_sub_agents(_ctx=ctx)

    assert result.ok is True
    assert "子任务A" in result.output
    assert "子任务B" in result.output
    assert "股票任务" not in result.output  # wrong agent_type
    assert "组长任务" not in result.output  # wrong depth

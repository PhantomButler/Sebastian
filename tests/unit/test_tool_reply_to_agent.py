from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sebastian.core.types import Session, SessionStatus


def _make_waiting_session() -> Session:
    s = Session(
        agent_type="code", title="重构", goal="重构 auth", depth=2, parent_session_id="seb-123"
    )
    s.status = SessionStatus.WAITING
    return s


def _make_mock_state(session: Session):
    state = MagicMock()
    state.index_store = AsyncMock()
    state.session_store = AsyncMock()
    state.event_bus = AsyncMock()
    state.session_store.get_session = AsyncMock(return_value=session)
    state.index_store.list_all = AsyncMock(
        return_value=[
            {
                "id": session.id,
                "agent_type": session.agent_type,
                "status": session.status.value,  # 跟随 session 对象的实际状态
                "depth": 2,
            }
        ]
    )

    mock_agent = AsyncMock()
    state.agent_instances = {"code": mock_agent}

    return state, mock_agent


@pytest.mark.asyncio
async def test_reply_to_agent_appends_message_and_restarts():
    from sebastian.capabilities.tools.reply_to_agent import reply_to_agent

    session = _make_waiting_session()
    state, mock_agent = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.reply_to_agent._get_state", return_value=state):
        result = await reply_to_agent(
            session_id=session.id,
            instruction="可以覆盖，继续执行",
        )

    assert result.ok is True
    state.session_store.append_message.assert_awaited_once_with(
        session.id,
        role="user",
        content="可以覆盖，继续执行",
        agent_type=session.agent_type,
    )
    # run_agent_session 通过 asyncio.create_task 调用，等一下让 task 完成
    import asyncio

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_reply_to_agent_rejects_non_waiting_session():
    from sebastian.capabilities.tools.reply_to_agent import reply_to_agent

    session = _make_waiting_session()
    session.status = SessionStatus.ACTIVE  # 不是 WAITING
    state, _ = _make_mock_state(session)

    with patch("sebastian.capabilities.tools.reply_to_agent._get_state", return_value=state):
        result = await reply_to_agent(session_id=session.id, instruction="继续")

    assert result.ok is False
    assert "waiting" in result.error.lower() or "等待" in result.error


@pytest.mark.asyncio
async def test_reply_to_agent_rejects_unknown_session():
    from sebastian.capabilities.tools.reply_to_agent import reply_to_agent

    state = MagicMock()
    state.index_store = AsyncMock()
    state.index_store.list_all = AsyncMock(return_value=[])

    with patch("sebastian.capabilities.tools.reply_to_agent._get_state", return_value=state):
        result = await reply_to_agent(session_id="nonexistent", instruction="继续")

    assert result.ok is False

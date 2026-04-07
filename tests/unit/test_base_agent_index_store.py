from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_update_activity_uses_injected_index_store() -> None:
    """_update_activity 应该调用注入的 index_store，不 import gateway.state。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore
    from sebastian.store.index_store import IndexStore

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "test"

    mock_index_store = MagicMock(spec=IndexStore)
    mock_index_store.update_activity = AsyncMock()

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
        index_store=mock_index_store,
    )

    await agent._update_activity("sess-abc")

    mock_index_store.update_activity.assert_awaited_once_with("sess-abc")


@pytest.mark.asyncio
async def test_update_activity_without_index_store_is_noop() -> None:
    """不注入 index_store 时 _update_activity 静默跳过，不报错。"""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "test"
        system_prompt = "test"

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
    )

    # Should not raise
    await agent._update_activity("sess-xyz")

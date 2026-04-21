from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store import models  # noqa: F401  — registers all ORM metadata
from sebastian.store.database import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def base_agent_with_memory():
    """Minimal BaseAgent with in-memory SQLite + one seeded profile record."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.models import ProfileMemoryRecord
    from sebastian.store.session_store import SessionStore

    # Build in-memory DB
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed one active profile record (subject_id="owner" — resolve_subject always returns this)
    async with factory() as session:
        record = ProfileMemoryRecord(
            id="depth-guard-test-1",
            subject_id="owner",
            scope="user",
            slot_id="user.pref.drink",
            kind="preference",
            content="喜欢茶",
            structured_payload={},
            source="explicit",
            confidence=0.9,
            status="active",
            valid_from=None,
            valid_until=None,
            provenance={},
            policy_tags=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            last_accessed_at=None,
            access_count=0,
        )
        session.add(record)
        await session.commit()

    class TestAgent(BaseAgent):
        name = "test"

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
        db_factory=factory,
    )

    # Patch memory_settings to enabled=True for all tests in this file
    import sebastian.gateway.state as gw_state

    fake_settings = MagicMock()
    fake_settings.enabled = True
    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        yield agent

    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depth_1_injects_memory(base_agent_with_memory) -> None:
    """depth=1 应走进正常注入逻辑，返回带记忆内容的字符串（fixture 预置一条 profile 记录）。"""
    agent = base_agent_with_memory
    agent._current_depth["s1"] = 1
    out = await agent._memory_section(
        session_id="s1", agent_context="sebastian", user_message="我喜欢茶"
    )
    assert out != ""


@pytest.mark.asyncio
async def test_depth_2_returns_empty(base_agent_with_memory) -> None:
    """depth=2（子 agent）必须返回空字符串，不注入记忆。"""
    agent = base_agent_with_memory
    agent._current_depth["s1"] = 2
    out = await agent._memory_section(
        session_id="s1", agent_context="worker", user_message="我喜欢茶"
    )
    assert out == ""


@pytest.mark.asyncio
async def test_depth_missing_returns_empty(base_agent_with_memory) -> None:
    """depth 未初始化（key 缺失 → None）必须 fail-closed 返回空字符串。"""
    agent = base_agent_with_memory
    agent._current_depth.pop("s1", None)
    out = await agent._memory_section(
        session_id="s1", agent_context="sebastian", user_message="我喜欢茶"
    )
    assert out == ""


@pytest.mark.asyncio
async def test_depth_zero_returns_empty(base_agent_with_memory) -> None:
    """depth=0 也必须返回空字符串（非预期深度）。"""
    agent = base_agent_with_memory
    agent._current_depth["s1"] = 0
    out = await agent._memory_section(
        session_id="s1", agent_context="sebastian", user_message="我喜欢茶"
    )
    assert out == ""

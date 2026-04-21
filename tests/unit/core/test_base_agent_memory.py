from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.stream_events import (
    ProviderCallEnd,
    TextBlockStart,
    TextBlockStop,
    TextDelta,
)
from sebastian.store import models  # noqa: F401  — registers all ORM metadata
from sebastian.store.database import Base
from tests.unit.core.test_agent_loop import MockLLMProvider

# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def mem_factory():
    """In-memory SQLite db_factory with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _make_test_agent(provider, session_store=None, db_factory=None):
    """Construct a minimal concrete TestAgent."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "test"

    if session_store is None:
        session_store = MagicMock(spec=SessionStore)
        session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())

    agent = TestAgent(
        gate=MagicMock(),
        session_store=session_store,
        provider=provider,
        db_factory=db_factory,
    )
    return agent


def _silent_provider(text: str = "ok") -> MockLLMProvider:
    return MockLLMProvider(
        [
            TextBlockStart(block_id="b0"),
            TextDelta(block_id="b0", delta=text),
            TextBlockStop(block_id="b0", text=text),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )


def _stub_episodic(agent) -> None:
    from sebastian.memory.episodic_memory import EpisodicMemory

    mock = MagicMock(spec=EpisodicMemory)
    mock.get_turns = AsyncMock(return_value=[])
    mock.add_turn = AsyncMock()
    agent._episodic = mock


# ---------------------------------------------------------------------------
# Test 1 — __init__ accepts optional db_factory
# ---------------------------------------------------------------------------


def test_init_accepts_db_factory() -> None:
    """BaseAgent.__init__ must accept db_factory and store it as _db_factory."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MinAgent(BaseAgent):
        name = "min"

    fake_factory = MagicMock()
    agent = MinAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
        db_factory=fake_factory,
    )
    assert agent._db_factory is fake_factory


def test_init_db_factory_defaults_to_none() -> None:
    """db_factory should default to None when not supplied."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class MinAgent(BaseAgent):
        name = "min"

    agent = MinAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
    )
    assert agent._db_factory is None


# ---------------------------------------------------------------------------
# Test 2 — _memory_section() returns assembled text with real SQLite records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_section_returns_profile_content(mem_factory) -> None:
    """_memory_section() pulls profile records from DB and returns non-empty string."""
    from datetime import UTC, datetime

    from sebastian.store.models import ProfileMemoryRecord

    # Seed a profile record directly into the DB
    async with mem_factory() as session:
        record = ProfileMemoryRecord(
            id="mem-test-1",
            subject_id="owner",
            scope="user",
            slot_id="user.pref.lang",
            kind="preference",
            content="用户偏好中文简洁回复",
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

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)

    import sebastian.gateway.state as gw_state

    fake_settings = MagicMock()
    fake_settings.enabled = True

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        result = await agent._memory_section(
            session_id="s1", agent_context="test", user_message="你好"
        )

    assert "用户偏好中文简洁回复" in result


# ---------------------------------------------------------------------------
# Test 3 — _stream_inner() includes memory section in effective system prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_inner_includes_memory_in_system_prompt(mem_factory) -> None:
    """effective_system_prompt passed to _loop.stream must contain memory text."""
    from datetime import UTC, datetime

    from sebastian.store.models import ProfileMemoryRecord

    async with mem_factory() as session:
        record = ProfileMemoryRecord(
            id="mem-stream-1",
            subject_id="owner",
            scope="user",
            slot_id="user.pref.style",
            kind="preference",
            content="喜欢详细解释",
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

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    _stub_episodic(agent)

    captured_prompts: list[str] = []

    original_stream = agent._loop.stream

    def capturing_stream(system_prompt: str, *args: Any, **kwargs: Any):
        captured_prompts.append(system_prompt)
        return original_stream(system_prompt, *args, **kwargs)

    agent._loop.stream = capturing_stream  # type: ignore[method-assign]

    import sebastian.gateway.state as gw_state

    fake_settings = MagicMock()
    fake_settings.enabled = True

    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    agent._session_store = session_store

    empty_todo_store = MagicMock()
    empty_todo_store.read = AsyncMock(return_value=[])

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        with patch.object(gw_state, "todo_store", empty_todo_store, create=True):
            await agent._stream_inner(
                messages=[{"role": "user", "content": "解释一下 asyncio"}],
                session_id="s2",
                task_id=None,
                agent_context="test",
            )

    assert captured_prompts, "stream() was never called"
    effective_prompt = captured_prompts[0]
    assert "喜欢详细解释" in effective_prompt


# ---------------------------------------------------------------------------
# Test 4 — todo section still works alongside memory section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_inner_includes_both_memory_and_todo(mem_factory) -> None:
    """Both memory section and todo section must appear in effective_system_prompt."""
    from datetime import UTC, datetime

    from sebastian.store.models import ProfileMemoryRecord

    async with mem_factory() as session:
        record = ProfileMemoryRecord(
            id="mem-todo-1",
            subject_id="owner",
            scope="user",
            slot_id="user.pref.foo",
            kind="preference",
            content="记忆内容存在",
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

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    _stub_episodic(agent)

    captured_prompts: list[str] = []

    original_stream = agent._loop.stream

    def capturing_stream(system_prompt: str, *args: Any, **kwargs: Any):
        captured_prompts.append(system_prompt)
        return original_stream(system_prompt, *args, **kwargs)

    agent._loop.stream = capturing_stream  # type: ignore[method-assign]

    # Stub a todo item
    from enum import Enum

    class FakeStatus(Enum):
        PENDING = "pending"

    fake_todo = MagicMock()
    fake_todo.status = FakeStatus.PENDING
    fake_todo.content = "完成任务A"
    fake_todo.active_form = "完成任务A"

    fake_todo_store = MagicMock()
    fake_todo_store.read = AsyncMock(return_value=[fake_todo])

    import sebastian.gateway.state as gw_state

    fake_mem_settings = MagicMock()
    fake_mem_settings.enabled = True

    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    agent._session_store = session_store

    with patch.object(gw_state, "memory_settings", fake_mem_settings, create=True):
        with patch.object(gw_state, "todo_store", fake_todo_store, create=True):
            await agent._stream_inner(
                messages=[{"role": "user", "content": "你好"}],
                session_id="s3",
                task_id=None,
                agent_context="test",
            )

    effective_prompt = captured_prompts[0]
    assert "记忆内容存在" in effective_prompt
    assert "完成任务A" in effective_prompt


# ---------------------------------------------------------------------------
# Test 4b — _memory_section() passes active_project_or_agent_context to RetrievalContext
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_section_passes_active_project_or_agent_context(mem_factory) -> None:
    """_memory_section must populate active_project_or_agent_context with agent_type."""
    from unittest.mock import patch

    import sebastian.gateway.state as gw_state
    from sebastian.memory.retrieval import RetrievalContext

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-ctx"] = 1  # depth guard: only depth=1 injects memory

    fake_settings = MagicMock()
    fake_settings.enabled = True

    captured_contexts: list[RetrievalContext] = []

    async def _fake_retrieve(ctx: RetrievalContext, *, db_session) -> str:  # type: ignore[override]
        captured_contexts.append(ctx)
        return ""

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        with patch(
            "sebastian.memory.retrieval.retrieve_memory_section",
            side_effect=_fake_retrieve,
        ):
            await agent._memory_section(
                session_id="s-ctx", agent_context="orchestrator", user_message="测试"
            )

    assert captured_contexts, "retrieve_memory_section was not called"
    ctx = captured_contexts[0]
    assert ctx.active_project_or_agent_context == {"agent_type": "orchestrator"}


# ---------------------------------------------------------------------------
# Test 5 — _memory_section() returns "" and logs warning when retrieval raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_section_returns_empty_on_exception(mem_factory, caplog) -> None:
    """If retrieve_memory_section raises, _memory_section must return '' and log warning."""
    import logging

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s4"] = 1  # depth guard: only depth=1 reaches retrieval logic

    import sebastian.gateway.state as gw_state

    fake_settings = MagicMock()
    fake_settings.enabled = True

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        with patch(
            "sebastian.memory.retrieval.retrieve_memory_section",
            side_effect=RuntimeError("DB exploded"),
        ):
            with caplog.at_level(logging.WARNING, logger="sebastian.core.base_agent"):
                result = await agent._memory_section(
                    session_id="s4", agent_context="test", user_message="query"
                )

    assert result == ""
    assert any("Memory section retrieval failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Test 6 — _memory_section() returns "" immediately when memory disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_section_returns_empty_when_disabled(mem_factory) -> None:
    """When memory_settings.enabled is False, _memory_section returns '' without DB access."""
    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)

    import sebastian.gateway.state as gw_state

    fake_settings = MagicMock()
    fake_settings.enabled = False

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        with patch("sebastian.memory.retrieval.retrieve_memory_section") as mock_retrieve:
            result = await agent._memory_section(
                session_id="s5", agent_context="test", user_message="query"
            )
            mock_retrieve.assert_not_called()

    assert result == ""

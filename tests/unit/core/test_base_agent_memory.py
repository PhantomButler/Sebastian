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


def _make_memory_service(db_factory):
    from sebastian.memory.services.memory_service import MemoryService

    return MemoryService(db_factory=db_factory)


def _stub_session_store(agent) -> None:
    """Replace agent._session_store with a minimal mock for _stream_inner tests."""
    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.get_messages = AsyncMock(return_value=[])
    session_store.get_context_messages = AsyncMock(return_value=[])
    session_store.append_message = AsyncMock()
    session_store.allocate_exchange = AsyncMock(return_value=("ex_test", 1))
    agent._session_store = session_store


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
    agent._current_depth["s1"] = 1  # depth guard: only depth=1 injects memory

    import sebastian.gateway.state as gw_state

    real_ms = _make_memory_service(mem_factory)

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        result = await agent._memory_section(
            session_id="s1", agent_context="test", user_message="我喜欢中文"
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
    agent._current_depth["s2"] = 1  # depth guard: only depth=1 injects memory
    _stub_session_store(agent)

    captured_prompts: list[str] = []

    original_stream = agent._loop.stream

    def capturing_stream(system_prompt: str, *args: Any, **kwargs: Any):
        captured_prompts.append(system_prompt)
        return original_stream(system_prompt, *args, **kwargs)

    agent._loop.stream = capturing_stream  # type: ignore[method-assign]

    import sebastian.gateway.state as gw_state

    real_ms = _make_memory_service(mem_factory)

    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.append_message = AsyncMock()
    agent._session_store = session_store

    empty_todo_store = MagicMock()
    empty_todo_store.read = AsyncMock(return_value=[])

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        with patch.object(gw_state, "todo_store", empty_todo_store, create=True):
            await agent._stream_inner(
                messages=[{"role": "user", "content": "我喜欢详细解释"}],
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
    agent._current_depth["s3"] = 1  # depth guard: only depth=1 injects memory
    _stub_session_store(agent)

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

    real_ms = _make_memory_service(mem_factory)

    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.append_message = AsyncMock()
    agent._session_store = session_store

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        with patch.object(gw_state, "todo_store", fake_todo_store, create=True):
            await agent._stream_inner(
                messages=[{"role": "user", "content": "我喜欢中文"}],
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
    from sebastian.memory.retrieval.retrieval import RetrievalContext

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-ctx"] = 1  # depth guard: only depth=1 injects memory

    real_ms = _make_memory_service(mem_factory)

    captured_contexts: list[RetrievalContext] = []

    async def _fake_retrieve(ctx: RetrievalContext, *, db_session) -> str:  # type: ignore[override]
        captured_contexts.append(ctx)
        return ""

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        with patch(
            "sebastian.memory.services.retrieval.retrieve_memory_section",
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

    real_ms = _make_memory_service(mem_factory)

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        with patch(
            "sebastian.memory.services.retrieval.retrieve_memory_section",
            side_effect=RuntimeError("DB exploded"),
        ):
            with caplog.at_level(
                logging.WARNING, logger="sebastian.memory.services.memory_service"
            ):
                result = await agent._memory_section(
                    session_id="s4", agent_context="test", user_message="query"
                )

    assert result == ""
    assert any("retrieve_for_prompt failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Test 6 — _memory_section() returns "" immediately when memory disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_section_returns_empty_when_disabled(mem_factory) -> None:
    """When memory_settings.enabled is False, _memory_section returns '' without DB access."""
    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)

    import sebastian.gateway.state as gw_state

    from sebastian.memory.services.memory_service import MemoryService

    disabled_ms = MemoryService(db_factory=mem_factory, memory_settings_fn=lambda: False)

    with patch.object(gw_state, "memory_service", disabled_ms, create=True):
        with patch("sebastian.memory.services.retrieval.retrieve_memory_section") as mock_retrieve:
            result = await agent._memory_section(
                session_id="s5", agent_context="test", user_message="query"
            )
            mock_retrieve.assert_not_called()

    assert result == ""


# ---------------------------------------------------------------------------
# Test 7 — run_streaming() with db_factory set uses get_context_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_streaming_sqlite_mode_uses_get_context_messages(mem_factory) -> None:
    """When _db_factory is set, run_streaming must call get_context_messages, not get_messages."""
    import sebastian.gateway.state as gw_state

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    _stub_session_store(agent)

    # Ensure get_session_for_agent_type returns a session with required attrs
    fake_worker_session = MagicMock()
    fake_worker_session.agent_type = "test"
    agent._session_store.get_session_for_agent_type = AsyncMock(return_value=fake_worker_session)

    fake_settings = MagicMock()
    fake_settings.enabled = False

    empty_todo_store = MagicMock()
    empty_todo_store.read = AsyncMock(return_value=[])

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        with patch.object(gw_state, "todo_store", empty_todo_store, create=True):
            await agent.run_streaming(session_id="s-sqlite", user_message="hello")

    agent._session_store.get_context_messages.assert_called_once()
    call_args = agent._session_store.get_context_messages.call_args
    assert call_args.args[0] == "s-sqlite"  # session_id
    agent._session_store.get_messages.assert_not_called()


# ---------------------------------------------------------------------------
# Test A — prompt order: resident before dynamic memory, memory before todo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_inner_prompt_order_resident_dynamic_todo(mem_factory) -> None:
    """In the assembled system prompt, resident memory → dynamic memory → todos.

    Verifies the full three-way ordering:
      resident_idx < dynamic_idx < todo_idx
    """
    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-order"] = 1
    _stub_session_store(agent)

    captured_prompts: list[str] = []
    original_stream = agent._loop.stream

    def capturing_stream(system_prompt: str, *args: Any, **kwargs: Any):
        captured_prompts.append(system_prompt)
        return original_stream(system_prompt, *args, **kwargs)

    agent._loop.stream = capturing_stream  # type: ignore[method-assign]

    from enum import Enum

    class FakeStatus(Enum):
        PENDING = "pending"

    fake_todo = MagicMock()
    fake_todo.status = FakeStatus.PENDING
    fake_todo.content = "待办任务X"
    fake_todo.active_form = "待办任务X"

    fake_todo_store = MagicMock()
    fake_todo_store.read = AsyncMock(return_value=[fake_todo])

    # Resident refresher returns a ready snapshot.
    # rendered_record_ids contains "res-1" — so dynamic retrieval excludes that record.
    from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult

    fake_refresher = MagicMock()
    fake_refresher.read = AsyncMock(
        return_value=ResidentSnapshotReadResult(
            content="## Resident Memory\n\n- Profile memory: 用户偏好英文\n",
            rendered_record_ids={"res-1"},
        )
    )

    # Mock dynamic retrieval to return a non-empty section.
    # The dynamic record id ("dyn-1") is NOT in resident's rendered_record_ids,
    # so it would not be filtered out by the exclusion logic.
    _DYNAMIC_SECTION = "## Current facts about user\n- [preference] 动态记忆内容"

    async def _fake_retrieve(ctx: Any, *, db_session: Any) -> str:
        return _DYNAMIC_SECTION

    import sebastian.gateway.state as gw_state

    real_ms = _make_memory_service(mem_factory)

    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.append_message = AsyncMock()
    agent._session_store = session_store

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        with patch.object(gw_state, "todo_store", fake_todo_store, create=True):
            with patch.object(gw_state, "resident_snapshot_refresher", fake_refresher, create=True):
                with patch(
                    "sebastian.memory.services.retrieval.retrieve_memory_section",
                    side_effect=_fake_retrieve,
                ):
                    await agent._stream_inner(
                        messages=[{"role": "user", "content": "hello"}],
                        session_id="s-order",
                        task_id=None,
                        agent_context="test",
                    )

    assert captured_prompts, "stream() was never called"
    prompt = captured_prompts[0]

    resident_idx = prompt.find("## Resident Memory")
    dynamic_idx = prompt.find("## Current facts about user")
    todo_idx = prompt.find("待办任务X")

    assert resident_idx != -1, "## Resident Memory not found in prompt"
    assert dynamic_idx != -1, "## Current facts about user (dynamic) not found in prompt"
    assert todo_idx != -1, "Todo content not found in prompt"
    assert resident_idx < dynamic_idx, (
        f"Resident Memory ({resident_idx}) must appear before dynamic memory ({dynamic_idx})"
    )
    assert dynamic_idx < todo_idx, (
        f"Dynamic memory ({dynamic_idx}) must appear before todos ({todo_idx})"
    )


# ---------------------------------------------------------------------------
# Test B — resident dedup sets are passed to _memory_section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_section_receives_resident_exclusions(mem_factory) -> None:
    """When _stream_inner() calls _memory_section(), it passes the resident dedup sets
    so that dynamic retrieval can skip already-rendered records."""
    from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult
    from sebastian.memory.retrieval.retrieval import RetrievalContext

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-excl"] = 1

    import sebastian.gateway.state as gw_state

    real_ms = _make_memory_service(mem_factory)

    captured_ctxs: list[RetrievalContext] = []

    async def _fake_retrieve(ctx: RetrievalContext, *, db_session) -> str:
        captured_ctxs.append(ctx)
        return ""

    fake_refresher = MagicMock()
    fake_refresher.read = AsyncMock(
        return_value=ResidentSnapshotReadResult(
            content="## Resident Memory\n\n- Profile memory: 偏好英文\n",
            rendered_record_ids={"rid-1"},
            rendered_dedupe_keys={"dkey-1"},
            rendered_canonical_bullets={"bullet-1"},
        )
    )

    empty_todo_store = MagicMock()
    empty_todo_store.read = AsyncMock(return_value=[])

    session_store = MagicMock()
    session_store.get_session_for_agent_type = AsyncMock(return_value=MagicMock())
    session_store.update_activity = AsyncMock()
    session_store.append_message = AsyncMock()
    agent._session_store = session_store

    with patch.object(gw_state, "memory_service", real_ms, create=True):
        with patch.object(gw_state, "todo_store", empty_todo_store, create=True):
            with patch.object(gw_state, "resident_snapshot_refresher", fake_refresher, create=True):
                with patch(
                    "sebastian.memory.services.retrieval.retrieve_memory_section",
                    side_effect=_fake_retrieve,
                ):
                    await agent._stream_inner(
                        messages=[{"role": "user", "content": "hello"}],
                        session_id="s-excl",
                        task_id=None,
                        agent_context="test",
                    )

    assert captured_ctxs, "retrieve_memory_section was never called"
    ctx = captured_ctxs[0]
    assert ctx.resident_record_ids == {"rid-1"}
    assert ctx.resident_dedupe_keys == {"dkey-1"}
    assert ctx.resident_canonical_bullets == {"bullet-1"}


# ---------------------------------------------------------------------------
# Test C — _resident_memory_section() skips depth > 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resident_memory_section_skips_depth_above_one(mem_factory) -> None:
    """When _current_depth[session] != 1, _resident_memory_section must return an
    empty result and must NOT call refresher.read()."""
    from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-depth"] = 2  # sub-agent depth — memory ineligible

    fake_refresher = MagicMock()
    fake_refresher.read = AsyncMock(
        return_value=ResidentSnapshotReadResult(content="should not be returned")
    )

    import sebastian.gateway.state as gw_state

    fake_settings = MagicMock()
    fake_settings.enabled = True

    with patch.object(gw_state, "memory_settings", fake_settings, create=True):
        with patch.object(gw_state, "resident_snapshot_refresher", fake_refresher, create=True):
            result = await agent._resident_memory_section("s-depth")

    assert result.content == ""
    fake_refresher.read.assert_not_called()


# ---------------------------------------------------------------------------
# Test D — _resident_memory_section() skips when memory disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resident_memory_section_skips_when_memory_disabled(mem_factory) -> None:
    """When memory_settings.enabled is False, _resident_memory_section returns empty."""
    from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult

    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-dis"] = 1

    fake_refresher = MagicMock()
    fake_refresher.read = AsyncMock(
        return_value=ResidentSnapshotReadResult(content="should not be returned")
    )

    import sebastian.gateway.state as gw_state

    fake_ms = MagicMock()
    fake_ms.is_enabled.return_value = False

    with patch.object(gw_state, "memory_service", fake_ms, create=True):
        with patch.object(gw_state, "resident_snapshot_refresher", fake_refresher, create=True):
            result = await agent._resident_memory_section("s-dis")

    assert result.content == ""
    fake_refresher.read.assert_not_called()


# ---------------------------------------------------------------------------
# Test E — _resident_memory_section() skips when refresher is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resident_memory_section_skips_missing_refresher(mem_factory) -> None:
    """When state.resident_snapshot_refresher is None, return empty result."""
    agent = _make_test_agent(_silent_provider(), db_factory=mem_factory)
    agent._current_depth["s-noref"] = 1

    import sebastian.gateway.state as gw_state

    fake_ms = MagicMock()
    fake_ms.is_enabled.return_value = True

    with patch.object(gw_state, "memory_service", fake_ms, create=True):
        with patch.object(gw_state, "resident_snapshot_refresher", None, create=True):
            result = await agent._resident_memory_section("s-noref")

    assert result.content == ""


# ---------------------------------------------------------------------------
# Test F — _resident_memory_section() does not open db_factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resident_memory_read_does_not_open_db_factory(mem_factory) -> None:
    """_resident_memory_section() must read from refresher.read(), not the DB.
    db_factory is patched to raise AssertionError if called."""
    from sebastian.memory.resident_snapshot import ResidentSnapshotReadResult

    # Build a db_factory that raises if called
    bad_factory = MagicMock(side_effect=AssertionError("db_factory must not be called"))

    agent = _make_test_agent(_silent_provider(), db_factory=bad_factory)
    agent._current_depth["s-nodb"] = 1

    fake_refresher = MagicMock()
    fake_refresher.read = AsyncMock(
        return_value=ResidentSnapshotReadResult(
            content="## Resident Memory\n\n- Profile memory: test\n",
            rendered_record_ids={"r1"},
        )
    )

    import sebastian.gateway.state as gw_state

    fake_memory_service = MagicMock()
    fake_memory_service.is_enabled.return_value = True

    with patch.object(gw_state, "memory_service", fake_memory_service, create=True):
        with patch.object(gw_state, "resident_snapshot_refresher", fake_refresher, create=True):
            result = await agent._resident_memory_section("s-nodb")

    # db_factory should never have been called
    bad_factory.assert_not_called()
    assert "## Resident Memory" in result.content

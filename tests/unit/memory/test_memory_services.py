from __future__ import annotations

import pytest

from sebastian.memory.contracts.retrieval import (
    ExplicitMemorySearchRequest,
    ExplicitMemorySearchResult,
    PromptMemoryRequest,
    PromptMemoryResult,
)
from sebastian.memory.contracts.writing import MemoryWriteRequest, MemoryWriteResult
from sebastian.memory.services.retrieval import MemoryRetrievalService


def test_prompt_memory_request_defaults_dedupe_sets() -> None:
    request = PromptMemoryRequest(
        session_id="sess-1",
        agent_type="sebastian",
        user_message="我喜欢什么",
        subject_id="user:owner",
    )
    assert request.resident_record_ids == set()
    assert request.resident_dedupe_keys == set()
    assert request.resident_canonical_bullets == set()


def test_prompt_memory_result_instantiation() -> None:
    result = PromptMemoryResult(section="## 记忆\n- 喜欢咖啡")
    assert result.section == "## 记忆\n- 喜欢咖啡"


def test_explicit_memory_search_request_default_limit() -> None:
    request = ExplicitMemorySearchRequest(
        query="咖啡",
        session_id="sess-1",
        agent_type="sebastian",
        subject_id="user:owner",
    )
    assert request.limit == 5


def test_explicit_memory_search_result_instantiation() -> None:
    result = ExplicitMemorySearchResult(items=[{"id": "m1", "content": "喜欢咖啡"}])
    assert len(result.items) == 1


def test_memory_write_result_defaults() -> None:
    result = MemoryWriteResult()
    assert result.decisions == []
    assert result.proposed_slots_registered == []
    assert result.proposed_slots_rejected == []
    assert result.saved_count == 0
    assert result.discarded_count == 0


@pytest.mark.asyncio
async def test_retrieval_service_delegates_prompt_retrieval(db_session, monkeypatch) -> None:
    captured = {}

    async def fake_retrieve(context, *, db_session):
        captured["context"] = context
        return "## Memory\n- [fact] hello"

    monkeypatch.setattr(
        "sebastian.memory.services.retrieval.retrieve_memory_section", fake_retrieve
    )

    service = MemoryRetrievalService()
    result = await service.retrieve_for_prompt(
        PromptMemoryRequest(
            session_id="sess-1",
            agent_type="sebastian",
            user_message="hello",
            subject_id="user:owner",
        ),
        db_session=db_session,
    )

    assert result.section == "## Memory\n- [fact] hello"
    assert captured["context"].access_purpose == "context_injection"
    assert captured["context"].active_project_or_agent_context is None


@pytest.mark.asyncio
async def test_retrieval_service_forwards_active_context(db_session, monkeypatch) -> None:
    captured = {}

    async def fake_retrieve(context, *, db_session):
        captured["context"] = context
        return ""

    monkeypatch.setattr(
        "sebastian.memory.services.retrieval.retrieve_memory_section", fake_retrieve
    )

    service = MemoryRetrievalService()
    await service.retrieve_for_prompt(
        PromptMemoryRequest(
            session_id="sess-1",
            agent_type="sebastian",
            user_message="hello",
            subject_id="user:owner",
            active_project_or_agent_context={"project": "home-automation"},
        ),
        db_session=db_session,
    )

    assert captured["context"].active_project_or_agent_context == {"project": "home-automation"}


@pytest.mark.asyncio
async def test_retrieval_service_search_returns_empty_on_no_data(db_session, monkeypatch) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "sebastian.memory.stores.profile_store.ProfileMemoryStore.search_active",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.stores.profile_store.ProfileMemoryStore.search_recent_context",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.stores.episode_store.EpisodeMemoryStore.search_summaries_by_query",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.stores.episode_store.EpisodeMemoryStore.search_episodes_only",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.stores.entity_registry.EntityRegistry.list_relations",
        AsyncMock(return_value=[]),
    )

    service = MemoryRetrievalService()
    result = await service.search(
        ExplicitMemorySearchRequest(
            query="咖啡",
            session_id="sess-1",
            agent_type="sebastian",
            subject_id="user:owner",
        ),
        db_session=db_session,
    )

    assert isinstance(result, ExplicitMemorySearchResult)
    assert result.items == []


@pytest.mark.asyncio
async def test_write_service_caller_owned_does_not_commit(db_session, monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.memory.writing.decision_log import MemoryDecisionLogger
    from sebastian.memory.stores.entity_registry import EntityRegistry
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.writing.pipeline import PipelineResult
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.services.writing import MemoryWriteService
    from sebastian.memory.writing.slot_proposals import SlotProposalHandler
    from sebastian.memory.writing.slots import SlotRegistry

    fake_result = PipelineResult(
        decisions=[],
        proposed_slots_registered=["user.profile.hobby"],
        proposed_slots_rejected=[],
    )
    mock_process = AsyncMock(return_value=fake_result)
    monkeypatch.setattr("sebastian.memory.services.writing.process_candidates", mock_process)

    service = MemoryWriteService(db_factory=MagicMock())
    request = MemoryWriteRequest(
        candidates=[],
        session_id="sess-1",
        agent_type="sebastian",
        worker_id="test",
        rule_version="spec-a-v1",
        input_source={"type": "test"},
    )

    profile_store = ProfileMemoryStore(db_session)
    episode_store = EpisodeMemoryStore(db_session)
    entity_registry = EntityRegistry(db_session)
    decision_logger = MemoryDecisionLogger(db_session)
    slot_registry = SlotRegistry(slots=[])
    slot_store_mock = MagicMock()
    slot_proposal_handler = SlotProposalHandler(store=slot_store_mock, registry=slot_registry)

    commit_called = False
    original_commit = db_session.commit

    async def spy_commit() -> None:
        nonlocal commit_called
        commit_called = True
        await original_commit()

    db_session.commit = spy_commit

    write_result = await service.write_candidates_in_session(
        request,
        db_session=db_session,
        profile_store=profile_store,
        episode_store=episode_store,
        entity_registry=entity_registry,
        decision_logger=decision_logger,
        slot_registry=slot_registry,
        slot_proposal_handler=slot_proposal_handler,
    )

    assert mock_process.called
    assert not commit_called
    assert write_result.proposed_slots_registered == ["user.profile.hobby"]
    assert write_result.decisions == []


@pytest.mark.asyncio
async def test_write_service_owned_commits(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.writing.pipeline import PipelineResult
    from sebastian.memory.services.writing import MemoryWriteService

    fake_result = PipelineResult(
        decisions=[],
        proposed_slots_registered=[],
        proposed_slots_rejected=[],
    )
    mock_process = AsyncMock(return_value=fake_result)
    monkeypatch.setattr("sebastian.memory.services.writing.process_candidates", mock_process)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_db_factory = MagicMock(return_value=mock_cm)

    service = MemoryWriteService(db_factory=mock_db_factory)
    request = MemoryWriteRequest(
        candidates=[],
        session_id="sess-2",
        agent_type="sebastian",
        worker_id="test",
        rule_version="spec-a-v1",
        input_source={"type": "test"},
    )

    result = await service.write_candidates(request)

    assert mock_process.called
    mock_session.commit.assert_awaited_once()
    assert result.decisions == []
    assert result.proposed_slots_registered == []


# ---------------------------------------------------------------------------
# MemoryService facade tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_service_disabled_returns_empty_prompt() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.memory.services.memory_service import MemoryService

    mock_retrieval = MagicMock()
    mock_retrieval.retrieve_for_prompt = AsyncMock()

    service = MemoryService(
        db_factory=MagicMock(),
        retrieval=mock_retrieval,
        memory_settings_fn=lambda: False,
    )

    result = await service.retrieve_for_prompt(
        PromptMemoryRequest(
            session_id="sess-1",
            agent_type="sebastian",
            user_message="hello",
            subject_id="user:owner",
        )
    )

    assert result == PromptMemoryResult(section="")
    mock_retrieval.retrieve_for_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_memory_service_retrieval_exception_returns_empty_section() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.memory.services.memory_service import MemoryService

    mock_retrieval = MagicMock()
    mock_retrieval.retrieve_for_prompt = AsyncMock(side_effect=RuntimeError("db exploded"))

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_db_factory = MagicMock(return_value=mock_cm)

    service = MemoryService(
        db_factory=mock_db_factory,
        retrieval=mock_retrieval,
    )

    result = await service.retrieve_for_prompt(
        PromptMemoryRequest(
            session_id="sess-1",
            agent_type="sebastian",
            user_message="hello",
            subject_id="user:owner",
        )
    )

    assert result == PromptMemoryResult(section="")


@pytest.mark.asyncio
async def test_memory_service_search_exception_returns_empty() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.memory.services.memory_service import MemoryService

    mock_retrieval = MagicMock()
    mock_retrieval.search = AsyncMock(side_effect=RuntimeError("db exploded"))

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_db_factory = MagicMock(return_value=mock_cm)

    service = MemoryService(
        db_factory=mock_db_factory,
        retrieval=mock_retrieval,
    )

    result = await service.search(
        ExplicitMemorySearchRequest(
            query="咖啡",
            session_id="sess-1",
            agent_type="sebastian",
            subject_id="user:owner",
        )
    )

    assert result == ExplicitMemorySearchResult(items=[])


@pytest.mark.asyncio
async def test_memory_service_marks_snapshot_dirty_on_successful_write() -> None:
    """When saved_count > 0, write_candidates() must call mark_dirty_locked() inside
    mutation_scope() — not schedule_refresh() — to prevent stale snapshot reads."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.services.memory_service import MemoryService

    # Result with saves
    mock_result = MagicMock()
    mock_result.saved_count = 2

    mock_writing = MagicMock()
    mock_writing.write_candidates_in_session = AsyncMock(return_value=mock_result)

    # Refresher: mutation_scope is a real asynccontextmanager so we can track entry
    mark_dirty_called = False

    class FakeRefresher:
        @asynccontextmanager
        async def mutation_scope(self):
            yield

        async def mark_dirty_locked(self) -> None:
            nonlocal mark_dirty_called
            mark_dirty_called = True

    mock_session = AsyncMock(spec=AsyncSession)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_db_factory = MagicMock(return_value=mock_cm)

    service = MemoryService(
        db_factory=mock_db_factory,
        writing=mock_writing,
        resident_snapshot_refresher=FakeRefresher(),
    )

    request = MemoryWriteRequest(
        candidates=[],
        session_id="sess-1",
        agent_type="sebastian",
        worker_id="test",
        rule_version="spec-a-v1",
        input_source={"type": "test"},
    )
    await service.write_candidates(request)

    mock_writing.write_candidates_in_session.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    assert mark_dirty_called, "mark_dirty_locked() must be called when saved_count > 0"


@pytest.mark.asyncio
async def test_memory_service_no_dirty_mark_when_no_saves() -> None:
    """When saved_count == 0, write_candidates() must NOT call mark_dirty_locked()."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.services.memory_service import MemoryService

    mock_result = MagicMock()
    mock_result.saved_count = 0

    mock_writing = MagicMock()
    mock_writing.write_candidates_in_session = AsyncMock(return_value=mock_result)

    mark_dirty_called = False

    class FakeRefresher:
        @asynccontextmanager
        async def mutation_scope(self):
            yield

        async def mark_dirty_locked(self) -> None:
            nonlocal mark_dirty_called
            mark_dirty_called = True

    mock_session = AsyncMock(spec=AsyncSession)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_db_factory = MagicMock(return_value=mock_cm)

    service = MemoryService(
        db_factory=mock_db_factory,
        writing=mock_writing,
        resident_snapshot_refresher=FakeRefresher(),
    )

    request = MemoryWriteRequest(
        candidates=[],
        session_id="sess-1",
        agent_type="sebastian",
        worker_id="test",
        rule_version="spec-a-v1",
        input_source={"type": "test"},
    )
    await service.write_candidates(request)

    mock_writing.write_candidates_in_session.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    assert not mark_dirty_called, "mark_dirty_locked() must NOT be called when saved_count == 0"


# ---------------------------------------------------------------------------
# BaseAgent._memory_section() delegates to state.memory_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_agent_memory_section_calls_memory_service() -> None:
    """_memory_section() should delegate to state.memory_service.retrieve_for_prompt()
    and return its result.section, not call retrieve_memory_section() directly."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from sebastian.core.base_agent import BaseAgent
    from sebastian.memory.contracts.retrieval import PromptMemoryResult
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "test"

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
        db_factory=MagicMock(),  # non-None so _db_factory guard passes
    )
    agent._current_depth["sess"] = 1

    mock_service = MagicMock()
    mock_service.retrieve_for_prompt = AsyncMock(
        return_value=PromptMemoryResult(section="## Memory\n- 喜欢茶")
    )

    import sebastian.gateway.state as gw_state

    with patch.object(gw_state, "memory_service", mock_service, create=True):
        # resolve_subject needs a db session — patch it to return a fixed value
        with patch(
            "sebastian.memory.subject.resolve_subject",
            AsyncMock(return_value="user:owner"),
        ):
            result = await agent._memory_section(
                session_id="sess",
                agent_context="sebastian",
                user_message="我喜欢茶",
                resident_record_ids={"rec-1"},
                resident_dedupe_keys={"key-1"},
                resident_canonical_bullets={"bullet-1"},
            )

    assert result == "## Memory\n- 喜欢茶"
    mock_service.retrieve_for_prompt.assert_awaited_once()
    call_request: PromptMemoryRequest = mock_service.retrieve_for_prompt.call_args[0][0]
    assert call_request.session_id == "sess"
    assert call_request.agent_type == "sebastian"
    assert call_request.user_message == "我喜欢茶"
    assert call_request.subject_id == "user:owner"
    assert call_request.resident_record_ids == {"rec-1"}
    assert call_request.resident_dedupe_keys == {"key-1"}
    assert call_request.resident_canonical_bullets == {"bullet-1"}
    assert call_request.active_project_or_agent_context == {"agent_type": "sebastian"}


@pytest.mark.asyncio
async def test_memory_service_disabled_write_candidates_returns_empty() -> None:
    """When memory is disabled, write_candidates() must return empty result without writing."""
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.memory.services.memory_service import MemoryService

    mock_writing = MagicMock()
    mock_writing.write_candidates = AsyncMock()

    service = MemoryService(
        db_factory=MagicMock(),
        writing=mock_writing,
        memory_settings_fn=lambda: False,
    )

    request = MemoryWriteRequest(
        candidates=[],
        session_id="sess-dis",
        agent_type="sebastian",
        worker_id="test",
        rule_version="spec-a-v1",
        input_source={"type": "test"},
    )
    result = await service.write_candidates(request)

    assert result.saved_count == 0
    assert result.decisions == []
    mock_writing.write_candidates.assert_not_called()


@pytest.mark.asyncio
async def test_memory_service_disabled_write_candidates_in_session_returns_empty() -> None:
    """When memory is disabled, write_candidates_in_session() returns empty without writing."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from sebastian.memory.writing.decision_log import MemoryDecisionLogger
    from sebastian.memory.stores.entity_registry import EntityRegistry
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.services.memory_service import MemoryService
    from sebastian.memory.writing.slot_proposals import SlotProposalHandler
    from sebastian.memory.writing.slots import SlotRegistry

    mock_writing = MagicMock()
    mock_writing.write_candidates_in_session = AsyncMock()

    service = MemoryService(
        db_factory=MagicMock(),
        writing=mock_writing,
        memory_settings_fn=lambda: False,
    )

    mock_session = MagicMock(spec=AsyncSession)
    request = MemoryWriteRequest(
        candidates=[],
        session_id="sess-dis",
        agent_type="sebastian",
        worker_id="test",
        rule_version="spec-a-v1",
        input_source={"type": "test"},
    )
    result = await service.write_candidates_in_session(
        request,
        db_session=mock_session,
        profile_store=MagicMock(spec=ProfileMemoryStore),
        episode_store=MagicMock(spec=EpisodeMemoryStore),
        entity_registry=MagicMock(spec=EntityRegistry),
        decision_logger=MagicMock(spec=MemoryDecisionLogger),
        slot_registry=SlotRegistry(slots=[]),
        slot_proposal_handler=MagicMock(spec=SlotProposalHandler),
    )

    assert result.saved_count == 0
    assert result.decisions == []
    mock_writing.write_candidates_in_session.assert_not_called()


@pytest.mark.asyncio
async def test_base_agent_memory_section_absent_service_returns_empty() -> None:
    """Fail-closed: when state.memory_service is None, return empty string."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from sebastian.core.base_agent import BaseAgent
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "test"

    agent = TestAgent(
        gate=MagicMock(),
        session_store=MagicMock(spec=SessionStore),
        db_factory=MagicMock(),
    )
    agent._current_depth["sess"] = 1

    import sebastian.gateway.state as gw_state

    with patch.object(gw_state, "memory_service", None, create=True):
        with patch(
            "sebastian.memory.subject.resolve_subject",
            AsyncMock(return_value="user:owner"),
        ):
            result = await agent._memory_section(
                session_id="sess",
                agent_context="sebastian",
                user_message="hello",
            )

    assert result == ""

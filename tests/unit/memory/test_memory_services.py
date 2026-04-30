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

    monkeypatch.setattr("sebastian.memory.services.retrieval.retrieve_memory_section", fake_retrieve)

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


@pytest.mark.asyncio
async def test_retrieval_service_search_returns_empty_on_no_data(db_session, monkeypatch) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "sebastian.memory.profile_store.ProfileMemoryStore.search_active",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.profile_store.ProfileMemoryStore.search_recent_context",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.episode_store.EpisodeMemoryStore.search_summaries_by_query",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.episode_store.EpisodeMemoryStore.search_episodes_only",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "sebastian.memory.entity_registry.EntityRegistry.list_relations",
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

    from sebastian.memory.contracts.writing import MemoryWriteRequest
    from sebastian.memory.decision_log import MemoryDecisionLogger
    from sebastian.memory.entity_registry import EntityRegistry
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.pipeline import PipelineResult
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.services.writing import MemoryWriteService
    from sebastian.memory.slot_proposals import SlotProposalHandler
    from sebastian.memory.slots import SlotRegistry

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

    from sebastian.memory.contracts.writing import MemoryWriteRequest
    from sebastian.memory.pipeline import PipelineResult
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

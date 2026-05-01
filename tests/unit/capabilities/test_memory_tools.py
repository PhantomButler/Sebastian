from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import sebastian.gateway.state as state_module
from sebastian.store import models  # noqa: F401 – registers ORM models
from sebastian.store.database import Base

if TYPE_CHECKING:
    from sebastian.memory.types import ResolveDecision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_in_memory_factory() -> tuple[AsyncEngine, async_sessionmaker]:
    """Build an in-memory SQLite async session factory with all tables created.

    Returns (engine, factory). Caller must ``await engine.dispose()`` when done.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Episode FTS table (needed by EpisodeMemoryStore.add_episode)
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        # Profile FTS table (needed by ProfileMemoryStore.add)
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def enabled_memory_state(monkeypatch):
    """Patch gateway.state with memory enabled and a real in-memory DB factory."""
    from sebastian.memory.services.memory_service import MemoryService

    fake_settings = MagicMock()
    fake_settings.enabled = True
    monkeypatch.setattr(state_module, "memory_settings", fake_settings, raising=False)

    engine, factory = await _create_in_memory_factory()
    monkeypatch.setattr(state_module, "db_factory", factory, raising=False)

    memory_service = MemoryService(
        db_factory=factory,
        memory_settings_fn=lambda: True,
    )
    monkeypatch.setattr(state_module, "memory_service", memory_service, raising=False)

    yield factory
    await engine.dispose()
    # 等 aiosqlite worker 线程退出，避免 PytestUnhandledThreadExceptionWarning
    await asyncio.sleep(0)


@pytest.fixture
def disabled_memory_state(monkeypatch):
    """Patch gateway.state with memory disabled."""
    fake_settings = MagicMock()
    fake_settings.enabled = False
    monkeypatch.setattr(state_module, "memory_settings", fake_settings, raising=False)
    monkeypatch.setattr(state_module, "db_factory", None, raising=False)


@pytest.fixture
def no_db_state(monkeypatch):
    """Patch gateway.state with memory enabled but db_factory unavailable."""
    fake_settings = MagicMock()
    fake_settings.enabled = True
    monkeypatch.setattr(state_module, "memory_settings", fake_settings, raising=False)
    monkeypatch.setattr(state_module, "db_factory", None, raising=False)


# ---------------------------------------------------------------------------
# memory_save tests
# ---------------------------------------------------------------------------


def _preference_candidate():
    """Valid CandidateArtifact for use in mocked extractor responses."""
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )

    return CandidateArtifact(
        kind=MemoryKind.PREFERENCE,
        content="以后回答简洁中文",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )


def _mock_extractor(monkeypatch, candidates):
    """Patch MemoryExtractor.extract_with_slot_retry to return a fake ExtractorOutput."""
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.memory.consolidation.extraction import ExtractorOutput

    fake_output = ExtractorOutput(artifacts=candidates, proposed_slots=[])

    fake_llm_registry = MagicMock()
    monkeypatch.setattr(state_module, "llm_registry", fake_llm_registry, raising=False)

    mock = AsyncMock(return_value=fake_output)
    monkeypatch.setattr(
        "sebastian.memory.consolidation.extraction.MemoryExtractor.extract_with_slot_retry",
        mock,
        raising=True,
    )
    return mock


@pytest.mark.asyncio
async def test_memory_save_returns_ok(enabled_memory_state, monkeypatch, caplog) -> None:
    """memory_save 同步等待完成后返回 ok=True，DB 有记录，output 含 saved_count。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryStatus
    from sebastian.store.models import ProfileMemoryRecord

    _mock_extractor(monkeypatch, [_preference_candidate()])
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")

    result = await memory_save(content="以后回答简洁中文")

    assert result.ok is True
    assert result.output["saved_count"] >= 1
    assert "summary" in result.output

    async with enabled_memory_state() as session:
        rows = (await session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].content == "以后回答简洁中文"
    assert rows[0].slot_id == "user.preference.response_style"
    assert rows[0].status == MemoryStatus.ACTIVE.value
    assert "MEMORY_TRACE tool.memory_save.done" in caplog.text


@pytest.mark.asyncio
async def test_memory_save_extractor_empty_skips_save(
    enabled_memory_state, monkeypatch, caplog
) -> None:
    """extractor 返回空列表时，不写入任何记录，output 中 saved_count == 0。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import ProfileMemoryRecord

    _mock_extractor(monkeypatch, [])
    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")

    result = await memory_save(content="用户喜欢深色主题")

    assert result.ok is True
    assert result.output["saved_count"] == 0

    async with enabled_memory_state() as session:
        rows = (await session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_memory_save_disabled_returns_error(disabled_memory_state) -> None:
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(content="some content")

    assert result.ok is False
    assert "关闭" in (result.error or "")


@pytest.mark.asyncio
async def test_memory_save_no_db_returns_error(no_db_state) -> None:
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(content="some content")

    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_memory_save_invalid_slot_logs_discard(enabled_memory_state, monkeypatch) -> None:
    """extractor 返回未知 slot 的 candidate → validate 失败 → DISCARD 进 decision log，无记录。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import (
        CandidateArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
    )
    from sebastian.store.models import MemoryDecisionLogRecord, ProfileMemoryRecord

    bad_candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="x",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id="no.such.slot",
        cardinality=None,
        resolution_policy=None,
        confidence=0.95,
        source=MemorySource.EXPLICIT,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    _mock_extractor(monkeypatch, [bad_candidate])

    result = await memory_save(content="x")
    assert result.ok is True

    async with enabled_memory_state() as s:
        profile_rows = (await s.scalars(select(ProfileMemoryRecord))).all()
        log_rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(profile_rows) == 0
    assert len(log_rows) == 1
    assert log_rows[0].decision == "DISCARD"


@pytest.mark.asyncio
async def test_memory_save_discard_writes_decision_log(enabled_memory_state, monkeypatch) -> None:
    """resolver 返回 DISCARD 时 decision log 有记录。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    _mock_extractor(monkeypatch, [_preference_candidate()])

    async def fake_resolve(
        candidate,
        *,
        subject_id,
        profile_store,
        slot_registry,
        episode_store=None,
    ) -> ResolveDecision:
        return ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason="test",
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        )

    monkeypatch.setattr("sebastian.memory.writing.pipeline.resolve_candidate", fake_resolve)

    result = await memory_save(content="x")
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) == 1
    assert rows[0].decision == MemoryDecisionType.DISCARD.value


@pytest.mark.asyncio
async def test_memory_save_decision_log_has_input_source(enabled_memory_state, monkeypatch) -> None:
    """decision log 的 input_source["type"] == "memory_save_tool"。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import MemoryDecisionLogRecord

    monkeypatch.setattr(_state, "current_session_id", "sess-tool-123", raising=False)
    _mock_extractor(monkeypatch, [_preference_candidate()])

    result = await memory_save(content="以后回答简洁中文")
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) >= 1
    for row in rows:
        assert row.input_source is not None
        assert row.input_source["type"] == "memory_save_tool"


@pytest.mark.asyncio
async def test_memory_save_provenance_contains_session_id(
    enabled_memory_state, monkeypatch
) -> None:
    """保存的记忆 provenance 包含 session_id 和 evidence。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import ProfileMemoryRecord

    monkeypatch.setattr(_state, "current_session_id", "sess-memory-save", raising=False)
    _mock_extractor(monkeypatch, [_preference_candidate()])

    result = await memory_save(content="以后回答简洁中文")
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    assert rows[0].provenance is not None


@pytest.mark.asyncio
async def test_memory_save_provenance_no_session_id_when_absent(
    enabled_memory_state, monkeypatch
) -> None:
    """未设置 session_id 时记忆仍能正常保存。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import ProfileMemoryRecord

    monkeypatch.setattr(_state, "current_session_id", None, raising=False)
    _mock_extractor(monkeypatch, [_preference_candidate()])

    result = await memory_save(content="以后回答简洁中文")
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_memory_save_discard_decision_log_has_input_source(
    enabled_memory_state, monkeypatch
) -> None:
    """DISCARD 路径下 decision log 也有 input_source["type"] == "memory_save_tool"。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    _mock_extractor(monkeypatch, [_preference_candidate()])

    async def fake_resolve(
        candidate,
        *,
        subject_id,
        profile_store,
        slot_registry,
        episode_store=None,
    ) -> ResolveDecision:
        return ResolveDecision(
            decision=MemoryDecisionType.DISCARD,
            reason="test-discard",
            old_memory_ids=[],
            new_memory=None,
            candidate=candidate,
            subject_id=subject_id,
            scope=candidate.scope,
            slot_id=candidate.slot_id,
        )

    monkeypatch.setattr("sebastian.memory.writing.pipeline.resolve_candidate", fake_resolve)

    result = await memory_save(content="x")
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) == 1
    assert rows[0].input_source is not None
    assert rows[0].input_source["type"] == "memory_save_tool"


@pytest.mark.asyncio
async def test_memory_save_delegates_to_memory_service(enabled_memory_state, monkeypatch) -> None:
    """_do_save() 通过 state.memory_service.write_candidates() 写入，
    并将返回的 MemoryWriteResult 正确转换为 MemorySaveResult。
    """
    from unittest.mock import AsyncMock

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.contracts.writing import MemoryWriteRequest, MemoryWriteResult
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision

    _mock_extractor(monkeypatch, [_preference_candidate()])

    cand = _preference_candidate()
    # A DISCARD decision (new_memory=None) — discarded_count == 1, saved_count == 0
    fake_decision = ResolveDecision(
        decision=MemoryDecisionType.DISCARD,
        reason="duplicate",
        old_memory_ids=[],
        new_memory=None,
        candidate=cand,
        subject_id="owner",
        scope=cand.scope,
        slot_id=cand.slot_id,
    )
    fake_write_result = MemoryWriteResult(
        decisions=[fake_decision],
        proposed_slots_registered=["user.preference.response_style"],
        proposed_slots_rejected=[],
    )
    mock_write = AsyncMock(return_value=fake_write_result)
    monkeypatch.setattr(_state.memory_service, "write_candidates", mock_write)

    result = await memory_save(content="以后回答简洁中文")

    assert result.ok is True
    mock_write.assert_called_once()
    call_args = mock_write.call_args[0][0]
    assert isinstance(call_args, MemoryWriteRequest)
    assert call_args.worker_id == "memory_save_tool"
    assert call_args.rule_version == "spec-a-v1"
    assert call_args.input_source["type"] == "memory_save_tool"

    # Verify MemoryWriteResult → MemorySaveResult conversion
    assert result.output["saved_count"] == 0
    assert result.output["discarded_count"] == 1
    assert result.output["proposed_slots_registered"] == ["user.preference.response_style"]
    assert "summary" in result.output


# ---------------------------------------------------------------------------
# memory_search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_returns_structured_items(enabled_memory_state, caplog) -> None:
    """Profile + episode records should be returned as structured citation items."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    now = datetime.now(UTC)
    profile_artifact = MemoryArtifact(
        id="profile-1",
        kind=MemoryKind.PREFERENCE,
        scope=MemoryScope.USER,
        subject_id="owner",
        slot_id="user.preference.response_style",
        cardinality=None,
        resolution_policy=None,
        content="以后回答简洁中文",
        structured_payload={},
        source=MemorySource.EXPLICIT,
        confidence=1.0,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=now,
        last_accessed_at=None,
        access_count=0,
        provenance={},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )
    episode_artifact = MemoryArtifact(
        id="episode-1",
        kind=MemoryKind.EPISODE,
        scope=MemoryScope.USER,
        subject_id="owner",
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        content="上次讨论了 Python 异步编程",
        structured_payload={},
        source=MemorySource.OBSERVED,
        confidence=0.8,
        status=MemoryStatus.ACTIVE,
        valid_from=None,
        valid_until=None,
        recorded_at=now,
        last_accessed_at=None,
        access_count=0,
        provenance={"session_id": "s1"},
        links=[],
        embedding_ref=None,
        dedupe_key=None,
        policy_tags=[],
    )

    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(profile_artifact)
        await EpisodeMemoryStore(session).add_episode(episode_artifact)
        await session.commit()

    # memory_search bypasses MemoryRetrievalPlanner — all four lanes run. The
    # profile PREFERENCE record will surface via the profile lane; the episode
    # via the episode lane. The context lane's recency fallback may also return
    # the profile record when FTS terms miss, so we assert on lane presence
    # rather than exact item count.
    result = await memory_search(query="上次我喜欢")

    assert result.ok is True
    assert isinstance(result.output, dict)
    items = result.output["items"]
    assert isinstance(items, list)
    assert len(items) >= 2

    required_keys = {"kind", "content", "source", "confidence", "is_current"}
    for item in items:
        assert required_keys <= set(item.keys())

    profile_item = next(
        i for i in items if i["kind"] == MemoryKind.PREFERENCE.value and i["lane"] == "profile"
    )
    episode_item = next(
        i for i in items if i["kind"] == MemoryKind.EPISODE.value and i["lane"] == "episode"
    )
    assert profile_item["is_current"] is True
    assert profile_item["source"] == MemorySource.EXPLICIT.value
    assert episode_item["is_current"] is False
    assert episode_item["source"] == MemorySource.OBSERVED.value
    assert "MEMORY_TRACE tool.memory_search.start" in caplog.text
    assert "MEMORY_TRACE tool.memory_search.done" in caplog.text


@pytest.mark.asyncio
async def test_memory_search_empty_returns_empty_items(enabled_memory_state, caplog) -> None:
    """Searching an empty DB should return ok=True with empty items and hint."""
    from sebastian.capabilities.tools.memory_search import memory_search

    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    result = await memory_search(query="something")

    assert result.ok is True
    assert result.output == {"items": []}
    assert result.empty_hint is not None
    assert "MEMORY_TRACE tool.memory_search.done" in caplog.text
    assert "result_count=0" in caplog.text


@pytest.mark.asyncio
async def test_memory_search_respects_limit(enabled_memory_state) -> None:
    """Total items must not exceed effective_limit (= max(limit, n_active_lanes)).

    With 4 lanes always active and cross-lane dedup, a small `limit` is raised
    to n_active (=4) to ensure every lane gets a slot. Dedup can further reduce
    count when the same record would appear in multiple lanes. The invariant is
    `len(items) <= effective_limit`.
    """
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        store = ProfileMemoryStore(session)
        for idx in range(5):
            await store.add(
                MemoryArtifact(
                    id=f"profile-{idx}",
                    kind=MemoryKind.PREFERENCE,
                    scope=MemoryScope.USER,
                    subject_id="owner",
                    slot_id=f"user.preference.slot_{idx}",
                    cardinality=None,
                    resolution_policy=None,
                    content=f"偏好 {idx}",
                    structured_payload={},
                    source=MemorySource.EXPLICIT,
                    confidence=1.0,
                    status=MemoryStatus.ACTIVE,
                    valid_from=None,
                    valid_until=None,
                    recorded_at=now,
                    last_accessed_at=None,
                    access_count=0,
                    provenance={},
                    links=[],
                    embedding_ref=None,
                    dedupe_key=None,
                    policy_tags=[],
                )
            )
        await session.commit()

    result = await memory_search(query="偏好", limit=2)

    assert result.ok is True
    assert isinstance(result.output, dict)
    # limit=2 with 4 active lanes → effective_limit = max(2, 4) = 4.
    # Cross-lane dedup can collapse context-lane FTS matches into profile-lane
    # when both pick the same record, so the observable count is [1, 4].
    assert 1 <= len(result.output["items"]) <= 4


@pytest.mark.asyncio
async def test_memory_search_disabled_returns_error(disabled_memory_state) -> None:
    from sebastian.capabilities.tools.memory_search import memory_search

    result = await memory_search(query="简洁中文")

    assert result.ok is False
    assert "关闭" in (result.error or "")


@pytest.mark.asyncio
async def test_memory_search_no_db_returns_error(no_db_state) -> None:
    from sebastian.capabilities.tools.memory_search import memory_search

    result = await memory_search(query="简洁中文")

    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_memory_search_citation_type_profile(enabled_memory_state) -> None:
    """Profile record should have citation_type='current_truth' and is_current=True."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(
            MemoryArtifact(
                id="profile-ct-1",
                kind=MemoryKind.PREFERENCE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.preference.response_style",
                cardinality=None,
                resolution_policy=None,
                content="简洁中文",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=1.0,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    result = await memory_search(query="偏好")
    assert result.ok is True
    items = result.output["items"]
    profile_item = next(i for i in items if i["kind"] == MemoryKind.PREFERENCE.value)
    assert profile_item["citation_type"] == "current_truth"
    assert profile_item["is_current"] is True


@pytest.mark.asyncio
async def test_memory_search_citation_type_summary(enabled_memory_state) -> None:
    """Summary episode record: citation_type='historical_summary', is_current=False."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await EpisodeMemoryStore(session).add_episode(
            MemoryArtifact(
                id="summary-ct-1",
                kind=MemoryKind.SUMMARY,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上周讨论了 Python 异步编程的总结",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.9,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={"session_id": "s2"},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    result = await memory_search(query="上次讨论总结")
    assert result.ok is True
    items = result.output["items"]
    summary_item = next(i for i in items if i["kind"] == MemoryKind.SUMMARY.value)
    assert summary_item["citation_type"] == "historical_summary"
    assert summary_item["is_current"] is False


@pytest.mark.asyncio
async def test_memory_search_citation_type_episode(enabled_memory_state) -> None:
    """Episode record should have citation_type='historical_evidence' and is_current=False."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await EpisodeMemoryStore(session).add_episode(
            MemoryArtifact(
                id="episode-ct-1",
                kind=MemoryKind.EPISODE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上次讨论了机器学习基础",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.8,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={"session_id": "s3"},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    result = await memory_search(query="上次讨论")
    assert result.ok is True
    items = result.output["items"]
    episode_item = next(i for i in items if i["kind"] == MemoryKind.EPISODE.value)
    assert episode_item["citation_type"] == "historical_evidence"
    assert episode_item["is_current"] is False


@pytest.mark.asyncio
async def test_memory_search_context_lane(enabled_memory_state) -> None:
    """Context-lane: a recent active profile record should appear with lane='context'."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        profile_store = ProfileMemoryStore(session)
        # High-confidence filler whose content does NOT match the query — profile
        # lane (ranked by confidence) will pick this one.
        await profile_store.add(
            MemoryArtifact(
                id="ctx-filler",
                kind=MemoryKind.PREFERENCE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.preference.response_style",
                cardinality=None,
                resolution_policy=None,
                content="喜欢喝绿茶",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=1.0,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        # Lower-confidence record that DOES match the FTS query — context lane
        # (FTS-ranked) picks this, distinct from the profile-lane pick so
        # cross-lane dedup preserves both.
        await profile_store.add(
            MemoryArtifact(
                id="ctx-1",
                kind=MemoryKind.FACT,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.fact.current_project",
                cardinality=None,
                resolution_policy=None,
                content="正在做 Sebastian 项目",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=0.5,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    # limit=4 → each lane budget=1; profile picks the filler by confidence,
    # context FTS picks ctx-1 ("正在做 Sebastian 项目").
    result = await memory_search(query="现在在做什么项目", limit=4)

    assert result.ok is True
    items = result.output["items"]
    assert any(item.get("lane") == "context" for item in items), (
        f"Expected at least one context-lane item, got: {items}"
    )
    context_item = next(i for i in items if i.get("lane") == "context")
    assert context_item["citation_type"] == "current_truth"
    assert context_item["is_current"] is True


@pytest.mark.asyncio
async def test_memory_search_relation_lane(enabled_memory_state) -> None:
    """Relation-lane: an active RelationCandidateRecord should appear with lane='relation'."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.store.models import RelationCandidateRecord

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        session.add(
            RelationCandidateRecord(
                id=str(uuid4()),
                subject_id="owner",
                predicate="works_on",
                source_entity_id="owner",
                target_entity_id="sebastian-project",
                content="owner works_on sebastian-project",
                structured_payload={},
                confidence=0.9,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    # "project" triggers relation lane keyword
    result = await memory_search(query="this project related to", limit=5)

    assert result.ok is True
    items = result.output["items"]
    assert any(item.get("lane") == "relation" for item in items), (
        f"Expected at least one relation-lane item, got: {items}"
    )
    relation_item = next(i for i in items if i.get("lane") == "relation")
    assert relation_item["citation_type"] == "current_truth"
    assert relation_item["is_current"] is True


@pytest.mark.asyncio
async def test_memory_search_summary_first(enabled_memory_state) -> None:
    """Summary-first: when both summary and episode match, summary appears before episode."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        store = EpisodeMemoryStore(session)
        await store.add_episode(
            MemoryArtifact(
                id="summary-sf-1",
                kind=MemoryKind.SUMMARY,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上次讨论了 Python 的总结",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.9,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={"session_id": "s-sf-1"},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await store.add_episode(
            MemoryArtifact(
                id="episode-sf-1",
                kind=MemoryKind.EPISODE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上次讨论了 Python 的细节",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.8,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={"session_id": "s-sf-2"},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    # "上次讨论" triggers episode lane. limit=8 so episode lane still gets >=2
    # after being split across all 4 active lanes (memory_search bypasses planner).
    result = await memory_search(query="上次讨论", limit=8)

    assert result.ok is True
    items = result.output["items"]
    episode_items = [i for i in items if i.get("lane") == "episode"]
    assert len(episode_items) >= 2, f"Expected at least 2 episode-lane items, got: {episode_items}"

    # Summary should come before raw episode
    summary_idx = next(
        (idx for idx, i in enumerate(episode_items) if i.get("kind") == MemoryKind.SUMMARY.value),
        None,
    )
    episode_idx = next(
        (idx for idx, i in enumerate(episode_items) if i.get("kind") == MemoryKind.EPISODE.value),
        None,
    )
    assert summary_idx is not None, "No summary item found"
    assert episode_idx is not None, "No episode item found"
    assert summary_idx < episode_idx, (
        f"Summary (idx={summary_idx}) should come before episode (idx={episode_idx})"
    )


@pytest.mark.asyncio
async def test_memory_search_profile_does_not_starve_episode_lane(
    enabled_memory_state,
) -> None:
    """With 5 profile records and limit=5, episode lane must still appear in results."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        profile_store = ProfileMemoryStore(session)
        for idx in range(5):
            await profile_store.add(
                MemoryArtifact(
                    id=f"profile-starve-{idx}",
                    kind=MemoryKind.PREFERENCE,
                    scope=MemoryScope.USER,
                    subject_id="owner",
                    slot_id=f"user.preference.starve_{idx}",
                    cardinality=None,
                    resolution_policy=None,
                    content=f"偏好设置 {idx}",
                    structured_payload={},
                    source=MemorySource.EXPLICIT,
                    confidence=1.0,
                    status=MemoryStatus.ACTIVE,
                    valid_from=None,
                    valid_until=None,
                    recorded_at=now,
                    last_accessed_at=None,
                    access_count=0,
                    provenance={},
                    links=[],
                    embedding_ref=None,
                    dedupe_key=None,
                    policy_tags=[],
                )
            )
        await EpisodeMemoryStore(session).add_episode(
            MemoryArtifact(
                id="episode-starve-1",
                kind=MemoryKind.EPISODE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上次讨论了记忆模块设计",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.9,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    # "上次" triggers episode lane; profile is always on
    result = await memory_search(query="上次讨论偏好", limit=5)

    assert result.ok is True
    items = result.output["items"]
    lanes = [item["lane"] for item in items]
    # effective_limit = max(5, 2 active lanes) = 5
    assert len(items) <= 5, f"Total must not exceed effective lane-aware budget, got {len(items)}"
    assert "episode" in lanes, f"Episode lane must appear despite 5 profile records; lanes={lanes}"


@pytest.mark.asyncio
async def test_memory_search_all_lanes_represented_within_limit(
    enabled_memory_state,
) -> None:
    """When all 4 lanes activate, each must appear at least once and total <= limit."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )
    from sebastian.store.models import RelationCandidateRecord

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        profile_store = ProfileMemoryStore(session)
        # 3 high-confidence records that do NOT match the query's FTS terms —
        # profile lane picks them.
        for idx in range(3):
            await profile_store.add(
                MemoryArtifact(
                    id=f"profile-alllane-{idx}",
                    kind=MemoryKind.FACT,
                    scope=MemoryScope.USER,
                    subject_id="owner",
                    slot_id=f"user.fact.alllane_{idx}",
                    cardinality=None,
                    resolution_policy=None,
                    content=f"事实 {idx}",
                    structured_payload={},
                    source=MemorySource.EXPLICIT,
                    confidence=1.0,
                    status=MemoryStatus.ACTIVE,
                    valid_from=None,
                    valid_until=None,
                    recorded_at=now,
                    last_accessed_at=None,
                    access_count=0,
                    provenance={},
                    links=[],
                    embedding_ref=None,
                    dedupe_key=None,
                    policy_tags=[],
                )
            )
        # Lower-confidence record whose content matches the query's FTS terms —
        # context lane picks it distinctly from the profile-lane top-N.
        await profile_store.add(
            MemoryArtifact(
                id="ctx-alllane",
                kind=MemoryKind.FACT,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.fact.alllane_ctx",
                cardinality=None,
                resolution_policy=None,
                content="现在在做 Sebastian 项目",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=0.5,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await EpisodeMemoryStore(session).add_episode(
            MemoryArtifact(
                id="episode-alllane-1",
                kind=MemoryKind.EPISODE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上次讨论了项目架构",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.9,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        session.add(
            RelationCandidateRecord(
                id=str(uuid4()),
                subject_id="owner",
                predicate="works_on",
                source_entity_id="owner",
                target_entity_id="sebastian-project",
                content="owner works_on sebastian-project",
                structured_payload={},
                confidence=0.9,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    # jieba planner requires explicit trigger words per lane
    # "现在"→context, "上次"→episode, "项目"→relation, "喜欢"→profile
    result = await memory_search(query="现在上次项目我喜欢", limit=5)

    assert result.ok is True
    items = result.output["items"]
    lanes = [item["lane"] for item in items]
    # effective_limit = max(5, 4 active lanes) = 5, so hard cap is 5
    assert len(items) <= 5, f"Total must not exceed effective lane-aware budget, got {len(items)}"
    assert "profile" in lanes, f"Profile lane missing; lanes={lanes}"
    assert "context" in lanes, f"Context lane missing; lanes={lanes}"
    assert "episode" in lanes, f"Episode lane missing; lanes={lanes}"
    assert "relation" in lanes, f"Relation lane missing; lanes={lanes}"


@pytest.mark.asyncio
async def test_memory_search_raises_effective_limit_to_cover_active_lanes(
    enabled_memory_state,
) -> None:
    """When limit < active lane count, effective_limit is raised to n_active so every lane gets 1 slot."""  # noqa: E501
    from datetime import UTC, datetime
    from uuid import uuid4

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.episode_store import EpisodeMemoryStore
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )
    from sebastian.store.models import RelationCandidateRecord

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        profile_store = ProfileMemoryStore(session)
        # 3 high-confidence records whose content does NOT match the query's
        # FTS terms — profile lane picks them by confidence.
        for idx in range(3):
            await profile_store.add(
                MemoryArtifact(
                    id=f"profile-eff-{idx}",
                    kind=MemoryKind.FACT,
                    scope=MemoryScope.USER,
                    subject_id="owner",
                    slot_id=f"user.fact.eff_{idx}",
                    cardinality=None,
                    resolution_policy=None,
                    content=f"事实 {idx}",
                    structured_payload={},
                    source=MemorySource.EXPLICIT,
                    confidence=1.0,
                    status=MemoryStatus.ACTIVE,
                    valid_from=None,
                    valid_until=None,
                    recorded_at=now,
                    last_accessed_at=None,
                    access_count=0,
                    provenance={},
                    links=[],
                    embedding_ref=None,
                    dedupe_key=None,
                    policy_tags=[],
                )
            )
        # Lower-confidence record whose content matches the query's FTS terms —
        # distinct from profile-lane top-N so cross-lane dedup preserves the
        # context-lane item.
        await profile_store.add(
            MemoryArtifact(
                id="ctx-eff",
                kind=MemoryKind.FACT,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.fact.eff_ctx",
                cardinality=None,
                resolution_policy=None,
                content="现在在做 Sebastian 项目",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=0.5,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await EpisodeMemoryStore(session).add_episode(
            MemoryArtifact(
                id="episode-eff-1",
                kind=MemoryKind.EPISODE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id=None,
                cardinality=None,
                resolution_policy=None,
                content="上次讨论了项目架构",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.9,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        session.add(
            RelationCandidateRecord(
                id=str(uuid4()),
                subject_id="owner",
                predicate="works_on",
                source_entity_id="owner",
                target_entity_id="sebastian-project",
                content="owner works_on sebastian-project",
                structured_payload={},
                confidence=0.9,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    # limit=2, but 4 lanes are activated → effective_limit = max(2, 4) = 4
    # Each lane gets exactly 1 slot; total should be 4, not 2
    # "现在"→context, "上次"→episode, "项目"→relation, "喜欢"→profile
    result = await memory_search(query="现在上次项目我喜欢", limit=2)

    assert result.ok is True
    items = result.output["items"]
    lanes = [item["lane"] for item in items]
    # effective_limit raised to 4 (n_active), so total ≤ 4 not ≤ 2
    assert len(items) <= 4, f"Total must not exceed effective_limit=4 (n_active), got {len(items)}"
    assert "profile" in lanes, f"Profile lane missing; lanes={lanes}"
    assert "context" in lanes, f"Context lane missing; lanes={lanes}"
    assert "episode" in lanes, f"Episode lane missing; lanes={lanes}"
    assert "relation" in lanes, f"Relation lane missing; lanes={lanes}"


# ---------------------------------------------------------------------------
# memory_search service delegation test (Task 7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_delegates_to_memory_service(monkeypatch) -> None:
    """memory_search 应委托给 state.memory_service.search()，返回相同的 ToolResult 结构。"""
    from unittest.mock import AsyncMock, MagicMock

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.contracts.retrieval import (
        ExplicitMemorySearchRequest,
        ExplicitMemorySearchResult,
    )

    fake_items = [
        {
            "lane": "profile",
            "kind": "preference",
            "content": "以后回答简洁中文",
            "source": "explicit",
            "confidence": 1.0,
            "citation_type": "current_truth",
            "is_current": True,
        }
    ]

    mock_service = MagicMock()
    mock_service.search = AsyncMock(return_value=ExplicitMemorySearchResult(items=fake_items))

    fake_settings = MagicMock()
    fake_settings.enabled = True
    monkeypatch.setattr(state_module, "memory_settings", fake_settings, raising=False)
    monkeypatch.setattr(state_module, "db_factory", MagicMock(), raising=False)
    monkeypatch.setattr(state_module, "memory_service", mock_service, raising=False)

    result = await memory_search(query="简洁中文", limit=5)

    assert result.ok is True
    assert result.output == {"items": fake_items}

    from sebastian.memory.writing.feedback import render_memory_search_display

    assert result.display == render_memory_search_display(fake_items)

    call_args = mock_service.search.call_args
    assert call_args is not None
    req: ExplicitMemorySearchRequest = call_args.args[0]
    assert isinstance(req, ExplicitMemorySearchRequest)
    assert req.query == "简洁中文"
    assert req.limit == 5


# ---------------------------------------------------------------------------
# memory_search filtering tests (Task 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_excludes_low_confidence_record(enabled_memory_state) -> None:
    """Record with confidence < 0.3 must not appear in memory_search results."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(
            MemoryArtifact(
                id="low-conf-1",
                kind=MemoryKind.PREFERENCE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.preference.response_style",
                cardinality=None,
                resolution_policy=None,
                content="低置信度记录不应出现",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=0.1,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    result = await memory_search(query="偏好")

    assert result.ok is True
    items = result.output["items"]
    for item in items:
        assert item["confidence"] >= 0.3, (
            f"Record with confidence {item['confidence']} below threshold should be excluded"
        )


@pytest.mark.asyncio
async def test_memory_search_excludes_expired_record(enabled_memory_state) -> None:
    """Record with valid_until in the past must not appear in memory_search results."""
    from datetime import UTC, datetime, timedelta

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    expired_until = now - timedelta(days=1)
    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(
            MemoryArtifact(
                id="expired-1",
                kind=MemoryKind.PREFERENCE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.preference.language",
                cardinality=None,
                resolution_policy=None,
                content="已过期的记录不应出现",
                structured_payload={},
                source=MemorySource.OBSERVED,
                confidence=1.0,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=expired_until,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    result = await memory_search(query="偏好语言")

    assert result.ok is True
    items = result.output["items"]
    assert not any("已过期的记录不应出现" in item.get("content", "") for item in items), (
        "Expired record should not appear in memory_search results"
    )


@pytest.mark.asyncio
async def test_memory_search_returns_do_not_auto_inject_record(enabled_memory_state) -> None:
    """Record tagged do_not_auto_inject MUST appear in tool_search results (not blocked)."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(
            MemoryArtifact(
                id="dna-1",
                kind=MemoryKind.PREFERENCE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.preference.response_style",
                cardinality=None,
                resolution_policy=None,
                content="只在显式搜索时出现",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=1.0,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=["do_not_auto_inject"],
            )
        )
        await session.commit()

    result = await memory_search(query="偏好")

    assert result.ok is True
    items = result.output["items"]
    assert any("只在显式搜索时出现" in item.get("content", "") for item in items), (
        "Record tagged do_not_auto_inject should appear in tool_search results"
    )


@pytest.mark.asyncio
async def test_memory_search_bypasses_planner_trigger_words(enabled_memory_state) -> None:
    """Regression: memory_search must NOT gate lanes via MemoryRetrievalPlanner.

    The query "项目 project" only matches the relation-lane lexicon, so planner-gated
    routing would skip the profile lane entirely and miss a FACT record living there.
    memory_search is an explicit user/agent search path, so every lane must be probed.
    """
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        store = ProfileMemoryStore(session)
        await store.add(
            MemoryArtifact(
                id="fact-project-focus",
                kind=MemoryKind.FACT,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.current_project_focus",
                cardinality=None,
                resolution_policy=None,
                content="用户当前主要关注的项目是开发 Sebastian 的记忆系统",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=0.95,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    # "项目" / "project" 词表里仅匹配 relation lane。若 memory_search 仍走 planner，
    # profile lane 将不被激活，这条 FACT 永远查不到。
    result = await memory_search(query="项目 project", limit=5)

    assert result.ok is True
    items = result.output["items"]
    assert any(
        "用户当前主要关注的项目" in item.get("content", "") and item.get("lane") == "profile"
        for item in items
    ), f"Expected profile-lane FACT in results, got: {items}"


@pytest.mark.asyncio
async def test_memory_search_unaffected_by_resident_dedup(enabled_memory_state) -> None:
    """memory_search must return a profile record even if it would be filtered by resident dedup.

    The resident dedup filter lives exclusively in MemorySectionAssembler.assemble() (the
    context_injection path). The memory_search tool uses a different code path
    (access_purpose="tool_search") and must never silently hide records from the agent.
    """
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(
            MemoryArtifact(
                id="resident-dedup-target",
                kind=MemoryKind.PREFERENCE,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.preference.language",
                cardinality=None,
                resolution_policy=None,
                content="用户偏好使用中文交流",
                structured_payload={"value": "中文"},
                source=MemorySource.EXPLICIT,
                confidence=1.0,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    # memory_search does NOT consult RetrievalContext.resident_* sets; the record
    # must always be returned regardless of whether resident memory already injected it.
    result = await memory_search(query="偏好语言")

    assert result.ok is True
    items = result.output["items"]
    assert any("用户偏好使用中文交流" in item.get("content", "") for item in items), (
        "memory_search must return the record even if it would be filtered by resident dedup"
    )


@pytest.mark.asyncio
async def test_memory_search_dedups_cross_lane_duplicates(enabled_memory_state) -> None:
    """Regression: 同一条画像记录在 profile_lane 和 context_lane 各命中一次时，
    应按 lane 优先级（profile > context）只保留一次，不给 LLM/UI 返回重复项。"""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.stores.profile_store import ProfileMemoryStore
    from sebastian.memory.types import (
        MemoryArtifact,
        MemoryKind,
        MemoryScope,
        MemorySource,
        MemoryStatus,
    )

    now = datetime.now(UTC)
    async with enabled_memory_state() as session:
        await ProfileMemoryStore(session).add(
            MemoryArtifact(
                id="fact-dedup-1",
                kind=MemoryKind.FACT,
                scope=MemoryScope.USER,
                subject_id="owner",
                slot_id="user.current_project_focus",
                cardinality=None,
                resolution_policy=None,
                content="用户当前主要关注的项目是开发 Sebastian 的记忆系统",
                structured_payload={},
                source=MemorySource.EXPLICIT,
                confidence=0.95,
                status=MemoryStatus.ACTIVE,
                valid_from=None,
                valid_until=None,
                recorded_at=now,
                last_accessed_at=None,
                access_count=0,
                provenance={},
                links=[],
                embedding_ref=None,
                dedupe_key=None,
                policy_tags=[],
            )
        )
        await session.commit()

    # "项目 工作" 会让 profile lane (search_active) 和 context lane
    # (search_recent_context 的 recency fallback) 都返回同一条记录。
    result = await memory_search(query="项目 工作", limit=10)

    assert result.ok is True
    items = result.output["items"]
    # 同一 id 只应出现一次，并且保留在更高优先级的 profile lane
    matching = [i for i in items if "用户当前主要关注的项目" in i.get("content", "")]
    assert len(matching) == 1, f"Expected single dedup-ed item, got {len(matching)}: {matching}"
    assert matching[0]["lane"] == "profile"

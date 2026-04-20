from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import sebastian.gateway.state as state_module
from sebastian.store import models  # noqa: F401 – registers ORM models
from sebastian.store.database import Base

if TYPE_CHECKING:
    from sebastian.memory.profile_store import ProfileMemoryStore
    from sebastian.memory.slots import SlotRegistry
    from sebastian.memory.types import CandidateArtifact, ResolveDecision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_in_memory_factory():
    """Build an in-memory SQLite async session factory with all tables created."""
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
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def enabled_memory_state(monkeypatch):
    """Patch gateway.state with memory enabled and a real in-memory DB factory."""
    fake_settings = MagicMock()
    fake_settings.enabled = True
    monkeypatch.setattr(state_module, "memory_settings", fake_settings, raising=False)

    factory = await _create_in_memory_factory()
    monkeypatch.setattr(state_module, "db_factory", factory, raising=False)
    return factory


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


@pytest.mark.asyncio
async def test_memory_save_returns_ok(enabled_memory_state, caplog) -> None:
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryStatus
    from sebastian.store.models import ProfileMemoryRecord

    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    result = await memory_save(
        content="以后回答简洁中文",
        slot_id="user.preference.response_style",
    )

    assert result.ok is True
    assert result.output is not None
    assert result.output["saved"] == "以后回答简洁中文"
    assert result.output["slot_id"] == "user.preference.response_style"

    # DB-state assertion: verify the record was actually persisted correctly.
    async with enabled_memory_state() as session:
        rows = (await session.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.content == "以后回答简洁中文"
    assert row.slot_id == "user.preference.response_style"
    assert row.status == MemoryStatus.ACTIVE.value
    assert "MEMORY_TRACE tool.memory_save.start" in caplog.text
    assert "MEMORY_TRACE tool.memory_save.done" in caplog.text


@pytest.mark.asyncio
async def test_memory_save_without_slot_id_rejected(enabled_memory_state, caplog) -> None:
    """Saving without a slot_id yields FACT kind, which requires a slot → validation rejects."""
    from sebastian.capabilities.tools.memory_save import memory_save

    caplog.set_level(logging.DEBUG, logger="sebastian.memory.trace")
    result = await memory_save(content="用户喜欢深色主题")

    assert result.ok is False
    assert "slot" in (result.error or "").lower()
    assert "MEMORY_TRACE tool.memory_save.reject" in caplog.text


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


# ---------------------------------------------------------------------------
# memory_search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_search_returns_structured_items(enabled_memory_state, caplog) -> None:
    """Profile + episode records should be returned as structured citation items."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore
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

    # Query contains episode-lane keyword "上次" so both lanes activate.
    result = await memory_search(query="上次讨论")

    assert result.ok is True
    assert isinstance(result.output, dict)
    items = result.output["items"]
    assert isinstance(items, list)
    assert len(items) == 2

    required_keys = {"kind", "content", "source", "confidence", "is_current"}
    for item in items:
        assert required_keys <= set(item.keys())

    profile_item = next(i for i in items if i["kind"] == MemoryKind.PREFERENCE.value)
    episode_item = next(i for i in items if i["kind"] == MemoryKind.EPISODE.value)
    assert profile_item["is_current"] is True
    assert profile_item["source"] == MemorySource.EXPLICIT.value
    assert episode_item["is_current"] is False
    assert episode_item["source"] == MemorySource.OBSERVED.value
    assert "MEMORY_TRACE tool.memory_search.start" in caplog.text
    assert "MEMORY_TRACE tool.memory_search.done" in caplog.text
    assert "result_count=2" in caplog.text


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
    """Limit parameter should cap the number of returned items."""
    from datetime import UTC, datetime

    from sebastian.capabilities.tools.memory_search import memory_search
    from sebastian.memory.profile_store import ProfileMemoryStore
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
    assert len(result.output["items"]) == 2


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
    from sebastian.memory.profile_store import ProfileMemoryStore
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
    from sebastian.memory.episode_store import EpisodeMemoryStore
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
    from sebastian.memory.episode_store import EpisodeMemoryStore
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
    from sebastian.memory.profile_store import ProfileMemoryStore
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

    # "现在" triggers context lane keyword
    result = await memory_search(query="现在在做什么项目", limit=5)

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
    from sebastian.memory.episode_store import EpisodeMemoryStore
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

    # "上次讨论" triggers episode lane
    result = await memory_search(query="上次讨论", limit=5)

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
async def test_memory_save_discard_writes_decision_log(enabled_memory_state, monkeypatch) -> None:
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    async def fake_resolve(
        candidate: CandidateArtifact,
        *,
        subject_id: str,
        profile_store: ProfileMemoryStore,
        slot_registry: SlotRegistry,
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

    monkeypatch.setattr(
        "sebastian.capabilities.tools.memory_save.resolve_candidate",
        fake_resolve,
        raising=False,
    )

    result = await memory_save(content="x", slot_id="user.preference.language")
    assert result.ok is False

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
        assert len(rows) == 1
        assert rows[0].decision == MemoryDecisionType.DISCARD.value


@pytest.mark.asyncio
async def test_memory_save_rejects_unknown_slot(enabled_memory_state) -> None:
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(content="x", slot_id="no.such.slot")
    assert result.ok is False
    assert "slot" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_memory_save_decision_log_has_input_source(enabled_memory_state, monkeypatch) -> None:
    """memory_save 写出的 decision log 应有 input_source["type"] == "memory_save_tool"。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import MemoryDecisionLogRecord

    # 设置 session_id 便于断言
    monkeypatch.setattr(_state, "current_session_id", "sess-tool-123", raising=False)

    result = await memory_save(
        content="以后回答简洁中文",
        slot_id="user.preference.response_style",
    )
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
    """memory_save 保存的记忆 provenance 应包含 session_id 和 evidence。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import ProfileMemoryRecord

    monkeypatch.setattr(_state, "current_session_id", "sess-memory-save", raising=False)

    result = await memory_save(
        content="以后回答简洁中文",
        slot_id="user.preference.response_style",
    )
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    prov = rows[0].provenance
    assert prov is not None
    assert prov.get("session_id") == "sess-memory-save"
    assert prov.get("evidence") == [{"session_id": "sess-memory-save"}]


@pytest.mark.asyncio
async def test_memory_save_provenance_no_session_id_when_absent(
    enabled_memory_state, monkeypatch
) -> None:
    """未设置 session_id 时 provenance.evidence 应为空列表，无 session_id 键。"""
    from sqlalchemy import select

    import sebastian.gateway.state as _state
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.store.models import ProfileMemoryRecord

    # Ensure no session_id is set
    monkeypatch.setattr(_state, "current_session_id", None, raising=False)

    result = await memory_save(
        content="以后回答简洁中文",
        slot_id="user.preference.response_style",
    )
    assert result.ok is True

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(ProfileMemoryRecord))).all()
    assert len(rows) == 1
    prov = rows[0].provenance
    assert prov is not None
    assert prov.get("evidence") == []
    assert "session_id" not in prov


@pytest.mark.asyncio
async def test_memory_save_discard_decision_log_has_input_source(
    enabled_memory_state, monkeypatch
) -> None:
    """DISCARD 路径下 decision log 也应有 input_source["type"] == "memory_save_tool"。"""
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    async def fake_resolve(
        candidate: CandidateArtifact,
        *,
        subject_id: str,
        profile_store: ProfileMemoryStore,
        slot_registry: SlotRegistry,
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

    monkeypatch.setattr(
        "sebastian.capabilities.tools.memory_save.resolve_candidate",
        fake_resolve,
        raising=False,
    )

    result = await memory_save(content="x", slot_id="user.preference.language")
    assert result.ok is False

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
    assert len(rows) == 1
    assert rows[0].input_source is not None
    assert rows[0].input_source["type"] == "memory_save_tool"

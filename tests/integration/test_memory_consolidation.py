from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.consolidation import (
    ConsolidationResult,
    ConsolidatorInput,
    MemorySummary,
    SessionConsolidationWorker,
)
from sebastian.memory.extraction import ExtractorOutput
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    ResolutionPolicy,
)
from sebastian.store.models import (
    Base,
    EntityRecord,
    EpisodeMemoryRecord,
    MemoryDecisionLogRecord,
    ProfileMemoryRecord,
    SessionConsolidationRecord,
)

# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


class FakeSessionStore:
    async def get_context_timeline_items(self, session_id: str, agent_type: str) -> list[dict]:
        raise RuntimeError("no timeline API in test stub")

    async def get_messages(self, session_id: str, agent_type: str = "sebastian") -> list[dict]:
        return [
            {"role": "user", "content": "帮我记住这个"},
            {"role": "assistant", "content": "好的"},
        ]


class FakeExtractor:
    """In-memory stand-in for :class:`MemoryExtractor`.

    Returns ``artifacts`` verbatim and records whether ``extract`` was called.
    """

    def __init__(self, artifacts: list[CandidateArtifact] | None = None) -> None:
        self.artifacts = artifacts or []
        self.called = False
        self.last_input = None

    async def extract(self, input):  # type: ignore[no-untyped-def]
        self.called = True
        self.last_input = input
        return ExtractorOutput(artifacts=list(self.artifacts))

    async def extract_with_slot_retry(self, input, *, attempt_register):  # type: ignore[no-untyped-def]
        self.called = True
        self.last_input = input
        return ExtractorOutput(artifacts=list(self.artifacts))


class FakeConsolidator:
    """Returns a preset ConsolidationResult without calling any LLM."""

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        return ConsolidationResult(
            summaries=[
                MemorySummary(
                    content="会话摘要",
                    scope="user",
                )
            ],
            artifacts=[
                CandidateArtifact(
                    kind=MemoryKind.PREFERENCE,
                    content="用户喜欢简洁回复",
                    structured_payload={},
                    subject_hint="owner",
                    scope=MemoryScope.USER,
                    slot_id="user.preference.response_style",
                    cardinality=Cardinality.SINGLE,
                    resolution_policy=ResolutionPolicy.SUPERSEDE,
                    confidence=1.0,
                    source=MemorySource.EXPLICIT,
                    evidence=[],
                    valid_from=None,
                    valid_until=None,
                    policy_tags=[],
                    needs_review=False,
                )
            ],
            proposed_actions=[],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create FTS virtual tables required by memory stores
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    yield eng
    await eng.dispose()


@pytest.fixture
def db_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def worker(db_factory):
    return SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeConsolidator(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_session_writes_records(worker, db_factory):
    """Happy path: records are written to all expected tables."""
    await worker.consolidate_session("sess-001", "sebastian")

    async with db_factory() as session:
        # SessionConsolidationRecord exists
        record = await session.get(
            SessionConsolidationRecord,
            {"session_id": "sess-001", "agent_type": "sebastian"},
        )
        assert record is not None
        assert record.worker_version == "phase_c_v1"

        # EpisodeMemoryRecord with summary content exists
        ep_result = await session.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.content == "会话摘要")
        )
        episodes = list(ep_result.all())
        assert len(episodes) == 1

        # ProfileMemoryRecord with preference content exists
        pr_result = await session.scalars(
            select(ProfileMemoryRecord).where(ProfileMemoryRecord.content == "用户喜欢简洁回复")
        )
        profiles = list(pr_result.all())
        assert len(profiles) == 1

        # At least one MemoryDecisionLogRecord exists
        log_result = await session.scalars(select(MemoryDecisionLogRecord))
        logs = list(log_result.all())
        assert len(logs) >= 1


@pytest.mark.asyncio
async def test_consolidate_session_idempotent(worker, db_factory):
    """Calling consolidate_session twice must not create duplicate episode records."""
    await worker.consolidate_session("sess-001", "sebastian")
    await worker.consolidate_session("sess-001", "sebastian")

    async with db_factory() as session:
        ep_result = await session.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.content == "会话摘要")
        )
        episodes = list(ep_result.all())
        assert len(episodes) == 1


class FakeSummaryOnlyConsolidator:
    """Returns a ConsolidationResult that contains only summaries, no artifacts."""

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        return ConsolidationResult(
            summaries=[
                MemorySummary(
                    content="会话摘要（仅摘要）",
                    scope="user",
                )
            ],
            artifacts=[],
            proposed_actions=[],
        )


@pytest.mark.asyncio
async def test_consolidate_logs_summary_decision(db_factory):
    """Summaries from consolidator must go through resolver and produce ADD log entries."""
    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeSummaryOnlyConsolidator(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )

    await worker.consolidate_session("sess-summary", "sebastian")

    async with db_factory() as session:
        log_result = await session.scalars(select(MemoryDecisionLogRecord))
        logs = list(log_result.all())
        summary_logs = [
            log for log in logs if log.candidate.get("kind") == MemoryKind.SUMMARY.value
        ]
        assert len(summary_logs) >= 1
        assert all(log.decision == "ADD" for log in summary_logs)
        # The corresponding episode record must also exist.
        ep_result = await session.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.content == "会话摘要（仅摘要）")
        )
        episodes = list(ep_result.all())
        assert len(episodes) == 1


class FakeMaliciousSubjectConsolidator:
    """Consolidator that returns a summary; subject_id is always resolved server-side."""

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        return ConsolidationResult(
            summaries=[
                MemorySummary(
                    content="伪装摘要",
                    scope="user",
                )
            ],
            artifacts=[],
            proposed_actions=[],
        )


@pytest.mark.asyncio
async def test_summary_subject_id_resolved_from_scope(db_factory):
    """USER-scope summary subject_id must always be resolved server-side to 'owner'."""
    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeMaliciousSubjectConsolidator(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )

    await worker.consolidate_session("sess-mal", "sebastian")

    async with db_factory() as session:
        ep_result = await session.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.content == "伪装摘要")
        )
        episodes = list(ep_result.all())
        assert len(episodes) == 1
        assert episodes[0].subject_id == "owner"

        log_result = await session.scalars(select(MemoryDecisionLogRecord))
        summary_logs = [
            log
            for log in list(log_result.all())
            if log.candidate.get("kind") == MemoryKind.SUMMARY.value
        ]
        assert len(summary_logs) == 1
        assert summary_logs[0].subject_id == "owner"


class CapturingConsolidator:
    """Captures the ConsolidatorInput for assertion and returns an empty result."""

    def __init__(self) -> None:
        self.last_input: ConsolidatorInput | None = None

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        self.last_input = input
        return ConsolidationResult()


@pytest.mark.asyncio
async def test_consolidator_input_includes_full_context(db_factory):
    """ConsolidatorInput must carry active memories, recent summaries, slot
    definitions, and an entity registry snapshot so the LLM can avoid
    duplicating existing memories.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    async with db_factory() as session:
        # Two active profile memories for owner
        session.add(
            ProfileMemoryRecord(
                id="pm-1",
                subject_id="owner",
                scope=MemoryScope.USER.value,
                slot_id="user.preference.response_style",
                kind=MemoryKind.PREFERENCE.value,
                content="用户偏好简洁回复",
                structured_payload={},
                source=MemorySource.EXPLICIT.value,
                confidence=0.9,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
                last_accessed_at=None,
                access_count=0,
            )
        )
        session.add(
            ProfileMemoryRecord(
                id="pm-2",
                subject_id="owner",
                scope=MemoryScope.USER.value,
                slot_id="user.preference.language",
                kind=MemoryKind.PREFERENCE.value,
                content="使用中文",
                structured_payload={},
                source=MemorySource.EXPLICIT.value,
                confidence=0.95,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
                last_accessed_at=None,
                access_count=0,
            )
        )
        # One summary episode for owner
        session.add(
            EpisodeMemoryRecord(
                id="ep-sum",
                subject_id="owner",
                scope=MemoryScope.USER.value,
                session_id="sess-prev",
                kind=MemoryKind.SUMMARY.value,
                content="上次会话摘要",
                content_segmented="上次 会话 摘要",
                structured_payload={},
                source=MemorySource.SYSTEM_DERIVED.value,
                confidence=0.8,
                status="active",
                recorded_at=now,
                provenance={},
                links=[],
                policy_tags=[],
                last_accessed_at=None,
                access_count=0,
            )
        )
        # One entity in the registry
        session.add(
            EntityRecord(
                id="ent-1",
                canonical_name="小橘",
                entity_type="pet",
                aliases=["橘猫"],
                entity_metadata={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    captor = CapturingConsolidator()
    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=captor,
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )
    await worker.consolidate_session("sess-ctx", "sebastian")

    inp = captor.last_input
    assert inp is not None
    assert len(inp.active_memories_for_subject) >= 2
    slot_ids = {m["slot_id"] for m in inp.active_memories_for_subject}
    assert "user.preference.response_style" in slot_ids
    assert "user.preference.language" in slot_ids

    assert len(inp.recent_summaries) >= 1
    assert inp.recent_summaries[0]["content"] == "上次会话摘要"

    # Nine built-in slots (updated in Tasks 13-14)
    assert len(inp.slot_definitions) == 9
    defined_ids = {s["slot_id"] for s in inp.slot_definitions}
    assert "user.preference.response_style" in defined_ids

    assert len(inp.entity_registry_snapshot) >= 1
    ent = inp.entity_registry_snapshot[0]
    assert ent["canonical_name"] == "小橘"
    assert ent["type"] == "pet"
    assert "橘猫" in ent["aliases"]


@pytest.mark.asyncio
async def test_consolidate_session_disabled_writes_nothing(db_factory):
    """When memory_settings_fn returns False nothing is written."""
    disabled_worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeConsolidator(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: False,
    )

    await disabled_worker.consolidate_session("sess-002", "sebastian")

    async with db_factory() as session:
        record = await session.get(
            SessionConsolidationRecord,
            {"session_id": "sess-002", "agent_type": "sebastian"},
        )
        assert record is None

        ep_result = await session.scalars(select(EpisodeMemoryRecord))
        assert list(ep_result.all()) == []


@pytest.mark.asyncio
async def test_worker_runs_extractor_before_consolidator(db_factory):
    """Extractor output must be handed to the consolidator as candidate_artifacts."""
    fake_artifact = CandidateArtifact(
        kind=MemoryKind.FACT,
        content="test",
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id=None,
        cardinality=None,
        resolution_policy=None,
        confidence=0.9,
        source=MemorySource.OBSERVED,
        evidence=[],
        valid_from=None,
        valid_until=None,
        policy_tags=[],
        needs_review=False,
    )
    extractor = FakeExtractor(artifacts=[fake_artifact])
    captor = CapturingConsolidator()
    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=captor,
        extractor=extractor,
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )

    await worker.consolidate_session("sess-extr", "sebastian")

    assert extractor.called
    assert captor.last_input is not None
    assert len(captor.last_input.candidate_artifacts) == 1
    assert captor.last_input.candidate_artifacts[0].content == "test"


class FakeExpireConsolidator:
    """Returns a ConsolidationResult that contains only an EXPIRE action."""

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        from sebastian.memory.consolidation import ProposedAction

        return ConsolidationResult(
            summaries=[],
            artifacts=[],
            proposed_actions=[
                ProposedAction(action="EXPIRE", memory_id="m-old", reason="stale data")
            ],
        )


@pytest.mark.asyncio
async def test_worker_executes_proposed_expire_action(db_factory):
    """Consolidator's EXPIRE action must mark the targeted profile EXPIRED and log it."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    async with db_factory() as session:
        session.add(
            ProfileMemoryRecord(
                id="m-old",
                subject_id="owner",
                scope=MemoryScope.USER.value,
                slot_id="",
                kind=MemoryKind.FACT.value,
                content="过期事实",
                structured_payload={},
                source=MemorySource.OBSERVED.value,
                confidence=0.7,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
                last_accessed_at=None,
                access_count=0,
            )
        )
        await session.commit()

    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeExpireConsolidator(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )
    await worker.consolidate_session("sess-exp", "sebastian")

    async with db_factory() as session:
        record = await session.get(ProfileMemoryRecord, "m-old")
        assert record is not None
        assert record.status == MemoryStatus.EXPIRED.value

        log_result = await session.scalars(select(MemoryDecisionLogRecord))
        expire_logs = [log for log in log_result.all() if log.decision == "EXPIRE"]
        assert len(expire_logs) == 1
        assert expire_logs[0].old_memory_ids == ["m-old"]
        assert expire_logs[0].conflicts == ["m-old"]
        assert expire_logs[0].reason == "stale data"


@pytest.mark.asyncio
async def test_consolidation_decision_log_has_input_source(db_factory):
    """SessionConsolidationWorker 写出的所有 decision log 都应有
    input_source["type"] == "session_consolidation"。"""
    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeConsolidator(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )
    await worker.consolidate_session("sess-input-src", "sebastian")

    async with db_factory() as session:
        log_result = await session.scalars(select(MemoryDecisionLogRecord))
        logs = list(log_result.all())

    assert len(logs) >= 1
    for log in logs:
        assert log.input_source is not None, f"log {log.id} missing input_source"
        assert log.input_source["type"] == "session_consolidation"
        assert log.input_source["session_id"] == "sess-input-src"
        assert log.input_source["agent_type"] == "sebastian"


@pytest.mark.asyncio
async def test_consolidation_expire_log_has_input_source(db_factory):
    """EXPIRE 路径下的 decision log 也应有 input_source["type"] == "session_consolidation"。"""
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    async with db_factory() as session:
        session.add(
            ProfileMemoryRecord(
                id="m-old-src",
                subject_id="owner",
                scope=MemoryScope.USER.value,
                slot_id="",
                kind=MemoryKind.FACT.value,
                content="过期事实 src test",
                structured_payload={},
                source=MemorySource.OBSERVED.value,
                confidence=0.7,
                status="active",
                valid_from=None,
                valid_until=None,
                provenance={},
                policy_tags=[],
                created_at=now,
                updated_at=now,
                last_accessed_at=None,
                access_count=0,
            )
        )
        await session.commit()

    class FakeExpireConsolidatorSrc:
        async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
            from sebastian.memory.consolidation import ProposedAction

            return ConsolidationResult(
                summaries=[],
                artifacts=[],
                proposed_actions=[
                    ProposedAction(action="EXPIRE", memory_id="m-old-src", reason="stale")
                ],
            )

    worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeExpireConsolidatorSrc(),
        extractor=FakeExtractor(),
        session_store=FakeSessionStore(),
        memory_settings_fn=lambda: True,
    )
    await worker.consolidate_session("sess-exp-src", "sebastian")

    async with db_factory() as session:
        log_result = await session.scalars(select(MemoryDecisionLogRecord))
        expire_logs = [log for log in log_result.all() if log.decision == "EXPIRE"]

    assert len(expire_logs) == 1
    assert expire_logs[0].input_source is not None
    assert expire_logs[0].input_source["type"] == "session_consolidation"
    assert expire_logs[0].input_source["session_id"] == "sess-exp-src"

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
from sebastian.memory.types import (
    CandidateArtifact,
    Cardinality,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ResolutionPolicy,
)
from sebastian.store.models import (
    Base,
    EpisodeMemoryRecord,
    MemoryDecisionLogRecord,
    ProfileMemoryRecord,
    SessionConsolidationRecord,
)

# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


class FakeSessionStore:
    async def get_messages(self, session_id: str, agent_type: str = "sebastian") -> list[dict]:
        return [
            {"role": "user", "content": "帮我记住这个"},
            {"role": "assistant", "content": "好的"},
        ]


class FakeConsolidator:
    """Returns a preset ConsolidationResult without calling any LLM."""

    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        return ConsolidationResult(
            summaries=[
                MemorySummary(
                    content="会话摘要",
                    subject_id="owner",
                    scope="user",
                )
            ],
            proposed_artifacts=[
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
        # Create FTS virtual table required by EpisodeMemoryStore
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
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


@pytest.mark.asyncio
async def test_consolidate_session_disabled_writes_nothing(db_factory):
    """When memory_settings_fn returns False nothing is written."""
    disabled_worker = SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=FakeConsolidator(),
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

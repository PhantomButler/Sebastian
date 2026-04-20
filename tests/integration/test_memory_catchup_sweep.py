from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.types import Session, SessionStatus
from sebastian.memory.consolidation import (
    ConsolidationResult,
    ConsolidatorInput,
    MemorySummary,
    SessionConsolidationWorker,
    sweep_unconsolidated,
)
from sebastian.memory.extraction import ExtractorOutput
from sebastian.memory.types import MemoryScope
from sebastian.store.index_store import IndexStore
from sebastian.store.models import (
    Base,
    EpisodeMemoryRecord,
    SessionConsolidationRecord,
)
from sebastian.store.session_store import SessionStore

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeExtractor:
    async def extract(self, input):  # type: ignore[no-untyped-def]
        return ExtractorOutput(artifacts=[])


class FakeConsolidator:
    async def consolidate(self, input: ConsolidatorInput) -> ConsolidationResult:
        return ConsolidationResult(
            summaries=[
                MemorySummary(
                    content="补齐摘要",
                    subject_id="owner",
                    scope=MemoryScope.USER,
                )
            ],
            proposed_artifacts=[],
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
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
async def stores(sessions_dir: Path):
    session_store = SessionStore(sessions_dir)
    index_store = IndexStore(sessions_dir, session_store=session_store)
    return session_store, index_store


async def _make_completed_session(
    session_store: SessionStore,
    index_store: IndexStore,
    *,
    session_id: str = "sess-sweep-1",
    agent_type: str = "sebastian",
) -> Session:
    session = Session(
        id=session_id,
        agent_type=agent_type,
        title="done",
        status=SessionStatus.COMPLETED,
    )
    await session_store.create_session(session)
    await index_store.upsert(session)
    return session


def _make_worker(db_factory, session_store, consolidator=None, extractor=None):
    return SessionConsolidationWorker(
        db_factory=db_factory,
        consolidator=consolidator or FakeConsolidator(),
        extractor=extractor or FakeExtractor(),
        session_store=session_store,
        memory_settings_fn=lambda: True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_consolidates_orphaned_completed_session(db_factory, stores):
    session_store, index_store = stores
    session = await _make_completed_session(session_store, index_store)
    worker = _make_worker(db_factory, session_store)

    await sweep_unconsolidated(
        db_factory=db_factory,
        worker=worker,
        index_store=index_store,
        memory_settings_fn=lambda: True,
    )

    async with db_factory() as db:
        marker = await db.get(
            SessionConsolidationRecord,
            {"session_id": session.id, "agent_type": "sebastian"},
        )
        assert marker is not None

        ep_result = await db.scalars(
            select(EpisodeMemoryRecord).where(EpisodeMemoryRecord.content == "补齐摘要")
        )
        episodes = list(ep_result.all())
        assert len(episodes) == 1


@pytest.mark.asyncio
async def test_sweep_short_circuits_when_memory_disabled(db_factory, stores):
    session_store, index_store = stores
    session = await _make_completed_session(session_store, index_store)
    worker = _make_worker(db_factory, session_store)

    await sweep_unconsolidated(
        db_factory=db_factory,
        worker=worker,
        index_store=index_store,
        memory_settings_fn=lambda: False,
    )

    async with db_factory() as db:
        marker = await db.get(
            SessionConsolidationRecord,
            {"session_id": session.id, "agent_type": "sebastian"},
        )
        assert marker is None


@pytest.mark.asyncio
async def test_sweep_skips_sessions_with_existing_marker(db_factory, stores):
    session_store, index_store = stores
    session = await _make_completed_session(session_store, index_store)

    calls: list[tuple[str, str]] = []

    class SpyWorker:
        async def consolidate_session(self, session_id: str, agent_type: str) -> None:
            calls.append((session_id, agent_type))

    from datetime import UTC, datetime

    async with db_factory() as db:
        db.add(
            SessionConsolidationRecord(
                session_id=session.id,
                agent_type="sebastian",
                consolidated_at=datetime.now(UTC),
                worker_version="phase_c_v1",
            )
        )
        await db.commit()

    await sweep_unconsolidated(
        db_factory=db_factory,
        worker=SpyWorker(),  # type: ignore[arg-type]
        index_store=index_store,
        memory_settings_fn=lambda: True,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_sweep_ignores_non_completed_sessions(db_factory, stores):
    session_store, index_store = stores
    active = Session(
        id="sess-active",
        agent_type="sebastian",
        title="still running",
        status=SessionStatus.ACTIVE,
    )
    await session_store.create_session(active)
    await index_store.upsert(active)

    calls: list[tuple[str, str]] = []

    class SpyWorker:
        async def consolidate_session(self, session_id: str, agent_type: str) -> None:
            calls.append((session_id, agent_type))

    await sweep_unconsolidated(
        db_factory=db_factory,
        worker=SpyWorker(),  # type: ignore[arg-type]
        index_store=index_store,
        memory_settings_fn=lambda: True,
    )

    assert calls == []

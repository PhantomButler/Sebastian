"""Integration test: SUPERSEDE 全链路.

Drives a full SUPERSEDE flow through the public ``memory_save`` and
``memory_search`` tool entrypoints plus the underlying profile/decision
stores. The scenario:

1. Seed one ACTIVE ``ProfileMemoryRecord`` in a SINGLE/SUPERSEDE slot.
2. Call ``memory_save`` with a conflicting value for the same slot.
3. Verify old row SUPERSEDED, new row ACTIVE, decision log entry created.
4. Call ``memory_search`` and verify only the new (active) record surfaces.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import sebastian.gateway.state as state_module
from sebastian.capabilities.tools.memory_save import memory_save
from sebastian.capabilities.tools.memory_search import memory_search
from sebastian.memory.consolidation.extraction import ExtractorOutput
from sebastian.memory.types import (
    CandidateArtifact,
    MemoryDecisionType,
    MemoryKind,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from sebastian.store import models  # noqa: F401 — registers ORM models
from sebastian.store.database import Base
from sebastian.store.models import MemoryDecisionLogRecord, ProfileMemoryRecord

# SINGLE/SUPERSEDE slot with FACT kind constraint (see sebastian/memory/slots.py).
_SLOT_ID = "user.current_project_focus"


@pytest.fixture
async def db_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Async generator fixture that creates an in-memory SQLite engine, yields
    the sessionmaker, and disposes the engine on teardown."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 virtual tables required by memory stores.
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
        await conn.execute(
            sqlalchemy.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS profile_memories_fts "
                "USING fts5(memory_id UNINDEXED, content_segmented, tokenize=unicode61)"
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def enabled_memory_state(
    monkeypatch, db_factory: async_sessionmaker[AsyncSession]
) -> async_sessionmaker[AsyncSession]:
    """Patch ``gateway.state`` with memory enabled and a real in-memory DB."""
    from sebastian.memory.services.memory_service import MemoryService

    fake_settings = MagicMock()
    fake_settings.enabled = True
    monkeypatch.setattr(state_module, "memory_settings", fake_settings, raising=False)
    monkeypatch.setattr(state_module, "db_factory", db_factory, raising=False)
    fake_llm_registry = MagicMock()
    monkeypatch.setattr(state_module, "llm_registry", fake_llm_registry, raising=False)
    memory_service = MemoryService(
        db_factory=db_factory,
        memory_settings_fn=lambda: True,
    )
    monkeypatch.setattr(state_module, "memory_service", memory_service, raising=False)
    return db_factory


@pytest.mark.asyncio
async def test_supersede_chain_from_memory_save_to_search(enabled_memory_state) -> None:
    """Full SUPERSEDE flow through public tools + stores.

    Old row gets demoted, new row becomes active, decision log records the
    transition, and ``memory_search`` filters out the superseded row.
    """
    factory = enabled_memory_state
    now = datetime.now(UTC)
    old_id = "pm-old"
    old_content = "旧项目 Alpha"
    new_content = "新项目 Beta"

    # --- Step 1: seed one ACTIVE profile record in the target slot ---------
    async with factory() as session:
        session.add(
            ProfileMemoryRecord(
                id=old_id,
                subject_id="owner",
                scope=MemoryScope.USER.value,
                slot_id=_SLOT_ID,
                kind=MemoryKind.FACT.value,
                content=old_content,
                structured_payload={},
                source=MemorySource.EXPLICIT.value,
                confidence=1.0,
                status=MemoryStatus.ACTIVE.value,
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

    # --- Step 2: memory_save a new value for the same SINGLE slot ----------
    # Patch extractor to return a candidate targeting the same slot so the
    # pipeline can detect and execute the SUPERSEDE resolution.
    new_candidate = CandidateArtifact(
        kind=MemoryKind.FACT,
        content=new_content,
        structured_payload={},
        subject_hint="owner",
        scope=MemoryScope.USER,
        slot_id=_SLOT_ID,
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
    fake_output = ExtractorOutput(artifacts=[new_candidate], proposed_slots=[])
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "sebastian.memory.consolidation.extraction.MemoryExtractor.extract_with_slot_retry",
            AsyncMock(return_value=fake_output),
        )
        save_result = await memory_save(content=new_content)
    assert save_result.ok is True, f"memory_save failed: {save_result.error}"

    # --- Step 3: assert SUPERSEDE bookkeeping ------------------------------
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ProfileMemoryRecord).where(ProfileMemoryRecord.slot_id == _SLOT_ID)
            )
        ).all()
        assert len(rows) == 2, f"expected old+new rows, got {[r.content for r in rows]}"

        actives = [r for r in rows if r.status == MemoryStatus.ACTIVE.value]
        supersededs = [r for r in rows if r.status == MemoryStatus.SUPERSEDED.value]
        assert len(actives) == 1
        assert len(supersededs) == 1
        active_row = actives[0]
        superseded_row = supersededs[0]
        assert superseded_row.id == old_id
        assert superseded_row.content == old_content
        assert active_row.content == new_content

        logs = (
            await session.scalars(
                select(MemoryDecisionLogRecord).where(
                    MemoryDecisionLogRecord.decision == MemoryDecisionType.SUPERSEDE.value
                )
            )
        ).all()
        assert len(logs) == 1, f"expected 1 SUPERSEDE log, got {len(logs)}"
        log = logs[0]
        assert log.old_memory_ids == [old_id]
        assert log.new_memory_id == active_row.id
        assert log.slot_id == _SLOT_ID

    # --- Step 4: memory_search must return the new row only ----------------
    # "我的项目进展" matches content; under jieba planner, profile lane
    # requires explicit trigger words (e.g. "我的") to activate — plain
    # "项目" only hits RELATION_LANE_STATIC_WORDS, not PROFILE_LANE_WORDS.
    # The superseded row would surface here if search_active failed to
    # filter by status.
    search_result = await memory_search(query="我的项目进展", limit=5)
    assert search_result.ok is True
    assert isinstance(search_result.output, dict)

    items = search_result.output["items"]
    contents = [item["content"] for item in items]
    assert new_content in contents
    assert old_content not in contents

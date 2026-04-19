from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import sebastian.gateway.state as state_module
from sebastian.store import models  # noqa: F401 – registers ORM models
from sebastian.store.database import Base

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
async def test_memory_save_returns_ok(enabled_memory_state) -> None:
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(
        content="以后回答简洁中文",
        slot_id="user.preference.response_style",
    )

    assert result.ok is True
    assert result.output is not None
    assert result.output["saved"] == "以后回答简洁中文"
    assert result.output["slot_id"] == "user.preference.response_style"


@pytest.mark.asyncio
async def test_memory_save_without_slot_id(enabled_memory_state) -> None:
    """Saving without a slot_id uses MemoryKind.FACT and confidence=1.0 (above threshold)."""
    from sebastian.capabilities.tools.memory_save import memory_save

    result = await memory_save(content="用户喜欢深色主题")

    assert result.ok is True
    assert result.output["saved"] == "用户喜欢深色主题"
    assert result.output["slot_id"] is None


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
async def test_memory_search_returns_ok_with_output(enabled_memory_state) -> None:
    """After saving a preference, searching for it should return ok=True with output."""
    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.capabilities.tools.memory_search import memory_search

    # Save something first so there is content to retrieve
    await memory_save(
        content="以后回答简洁中文",
        slot_id="user.preference.response_style",
    )

    result = await memory_search(query="简洁中文")

    assert result.ok is True
    # output is either a non-empty string or a dict/non-None value
    assert result.output is not None


@pytest.mark.asyncio
async def test_memory_search_empty_db_returns_ok(enabled_memory_state) -> None:
    """Searching an empty DB should return ok=True with an empty-hint."""
    from sebastian.capabilities.tools.memory_search import memory_search

    result = await memory_search(query="something")

    assert result.ok is True


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
async def test_memory_save_discard_writes_decision_log(
    enabled_memory_state, monkeypatch
):
    from sqlalchemy import select

    from sebastian.capabilities.tools.memory_save import memory_save
    from sebastian.memory.types import MemoryDecisionType, ResolveDecision
    from sebastian.store.models import MemoryDecisionLogRecord

    async def fake_resolve(candidate, *, subject_id, profile_store, slot_registry):
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

    result = await memory_save(content="x")
    assert result.ok is False

    async with enabled_memory_state() as s:
        rows = (await s.scalars(select(MemoryDecisionLogRecord))).all()
        assert len(rows) == 1
        assert rows[0].decision == MemoryDecisionType.DISCARD.value

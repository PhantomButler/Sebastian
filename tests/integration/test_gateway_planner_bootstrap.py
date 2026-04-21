from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.entity_registry import EntityRegistry
from sebastian.memory.retrieval import (
    DEFAULT_RETRIEVAL_PLANNER,
    RetrievalContext,
)
from sebastian.memory.retrieval_lexicon import RELATION_LANE_STATIC_WORDS
from sebastian.store.database import Base


@pytest.fixture
async def db_session_factory():
    """Return an async session factory backed by an in-memory SQLite database."""
    from sebastian.store import models  # noqa: F401 – registers ORM models

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_planner() -> None:
    """Reset DEFAULT_RETRIEVAL_PLANNER before and after each test."""
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS
    yield  # type: ignore[misc]
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS


@pytest.mark.asyncio
async def test_gateway_startup_bootstraps_planner_entity_triggers(
    db_session_factory,
) -> None:
    """bootstrap_entity_triggers merges entity names/aliases into the planner trigger set."""
    # Seed an entity (simulate historical data)
    async with db_session_factory() as session:
        await EntityRegistry(session).upsert_entity(
            canonical_name="王总", entity_type="person", aliases=["王先生"]
        )
        await session.commit()

    # Trigger bootstrap (same logic as gateway lifespan)
    async with db_session_factory() as session:
        await DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers(EntityRegistry(session))

    assert "王总" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set
    assert "王先生" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set
    assert RELATION_LANE_STATIC_WORDS <= DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set

    plan = DEFAULT_RETRIEVAL_PLANNER.plan(
        RetrievalContext(
            subject_id="user:eric",
            session_id="s1",
            agent_type="sebastian",
            user_message="王总来找我",
        )
    )
    assert plan.relation_lane is True


@pytest.mark.asyncio
async def test_write_path_registry_auto_reloads_planner(
    db_session_factory,
) -> None:
    """EntityRegistry constructed with planner= triggers reload on upsert_entity."""
    # Bootstrap with empty DB first
    async with db_session_factory() as session:
        await DEFAULT_RETRIEVAL_PLANNER.bootstrap_entity_triggers(EntityRegistry(session))

    assert "新人物" not in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set

    # Write path: upsert a new entity with planner wired
    async with db_session_factory() as session:
        registry = EntityRegistry(session, planner=DEFAULT_RETRIEVAL_PLANNER)
        await registry.upsert_entity(
            canonical_name="新人物", entity_type="person", aliases=["新别名"]
        )
        await session.commit()

    assert "新人物" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set
    assert "新别名" in DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set

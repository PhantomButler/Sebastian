from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.slots import SlotRegistry
from sebastian.memory.startup import bootstrap_slot_registry, seed_builtin_slots
from sebastian.store.models import Base


@pytest.fixture
async def fresh_gateway_db():
    """In-memory SQLite factory with all tables created and builtin slots seeded."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed builtin slots (simulates what lifespan does before bootstrap)
    async with factory() as session:
        await seed_builtin_slots(session)

    yield factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_slot_registry_loads_all_seeds(fresh_gateway_db):
    """bootstrap_slot_registry должен загрузить все 9 builtin-слотов из DB в registry."""
    registry = SlotRegistry(slots=[])
    async with fresh_gateway_db() as session:
        await bootstrap_slot_registry(session, registry)

    # 9 builtin slots should all be in the in-memory registry
    assert len(registry.list_all()) == 9
    assert registry.get("user.profile.name") is not None


@pytest.mark.asyncio
async def test_bootstrap_slot_registry_is_additive(fresh_gateway_db):
    """bootstrap_from_db should add DB slots on top of any already-registered slots."""
    # Start with 9 builtin slots already in registry (as DEFAULT_SLOT_REGISTRY would)
    from sebastian.memory.slots import _BUILTIN_SLOTS

    registry = SlotRegistry(slots=_BUILTIN_SLOTS)
    assert len(registry.list_all()) == 9

    async with fresh_gateway_db() as session:
        await bootstrap_slot_registry(session, registry)

    # After bootstrap, count should still be 9 (no duplicates)
    assert len(registry.list_all()) == 9


@pytest.mark.asyncio
async def test_bootstrap_slot_registry_empty_db():
    """bootstrap_slot_registry on empty DB should leave registry unchanged."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    registry = SlotRegistry(slots=[])
    async with factory() as session:
        await bootstrap_slot_registry(session, registry)

    assert len(registry.list_all()) == 0
    await engine.dispose()

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore
from sebastian.memory.slots import SlotRegistry
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)
from sebastian.store.models import Base


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_bootstrap_loads_db_rows(db) -> None:
    async with db() as session:
        store = SlotDefinitionStore(session)
        await store.insert(
            SlotDefinition(
                slot_id="user.profile.hobby",
                scope=MemoryScope.USER,
                subject_kind="user",
                cardinality=Cardinality.MULTI,
                resolution_policy=ResolutionPolicy.APPEND_ONLY,
                kind_constraints=[MemoryKind.PREFERENCE],
                description="爱好",
            ),
            is_builtin=False,
            proposed_by="extractor",
            proposed_in_session=None,
            created_at=datetime.now(UTC),
        )
        await session.commit()

    registry = SlotRegistry(slots=[])
    assert registry.get("user.profile.hobby") is None

    async with db() as session:
        store = SlotDefinitionStore(session)
        await registry.bootstrap_from_db(store)

    assert registry.get("user.profile.hobby") is not None


def test_register_adds_to_memory() -> None:
    registry = SlotRegistry(slots=[])
    schema = SlotDefinition(
        slot_id="user.profile.x",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="x",
    )
    registry.register(schema)
    assert registry.get("user.profile.x") is schema


def test_register_overrides_existing() -> None:
    registry = SlotRegistry(slots=[])
    s1 = SlotDefinition(
        slot_id="user.profile.x",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.SINGLE,
        resolution_policy=ResolutionPolicy.SUPERSEDE,
        kind_constraints=[MemoryKind.FACT],
        description="old",
    )
    s2 = s1.model_copy(update={"description": "new"})
    registry.register(s1)
    registry.register(s2)
    assert registry.get("user.profile.x").description == "new"

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.memory.stores.slot_definition_store import SlotDefinitionStore
from sebastian.memory.types import (
    Cardinality,
    MemoryKind,
    MemoryScope,
    ResolutionPolicy,
    SlotDefinition,
)
from sebastian.store.models import Base


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_schema() -> SlotDefinition:
    return SlotDefinition(
        slot_id="user.profile.hobby",
        scope=MemoryScope.USER,
        subject_kind="user",
        cardinality=Cardinality.MULTI,
        resolution_policy=ResolutionPolicy.APPEND_ONLY,
        kind_constraints=[MemoryKind.PREFERENCE],
        description="用户爱好",
    )


@pytest.mark.asyncio
async def test_insert_and_get(session_factory) -> None:
    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        await store.insert(
            _make_schema(),
            is_builtin=False,
            proposed_by="extractor",
            proposed_in_session="sess-1",
            created_at=datetime.now(UTC),
        )
        await session.commit()

    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        row = await store.get("user.profile.hobby")
    assert row is not None
    assert row.slot_id == "user.profile.hobby"
    assert row.proposed_by == "extractor"
    assert row.proposed_in_session == "sess-1"


@pytest.mark.asyncio
async def test_duplicate_slot_id_raises(session_factory) -> None:
    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        schema = _make_schema()
        await store.insert(
            schema,
            is_builtin=False,
            proposed_by=None,
            proposed_in_session=None,
            created_at=datetime.now(UTC),
        )
        await session.commit()

    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        with pytest.raises(IntegrityError):
            await store.insert(
                _make_schema(),
                is_builtin=False,
                proposed_by=None,
                proposed_in_session=None,
                created_at=datetime.now(UTC),
            )
            await session.commit()


@pytest.mark.asyncio
async def test_list_all_returns_schemas(session_factory) -> None:
    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        await store.insert(
            _make_schema(),
            is_builtin=False,
            proposed_by=None,
            proposed_in_session=None,
            created_at=datetime.now(UTC),
        )
        await session.commit()

    async with session_factory() as session:
        store = SlotDefinitionStore(session)
        rows = await store.list_all()
    assert len(rows) == 1
    assert rows[0].slot_id == "user.profile.hobby"
    assert rows[0].cardinality == Cardinality.MULTI

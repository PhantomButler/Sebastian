from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.database import Base
from sebastian.store.owner_store import OwnerStore


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db", future=True)
    async with engine.begin() as conn:
        from sebastian.store import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_exists_false_on_empty_db(session_factory) -> None:
    store = OwnerStore(session_factory)
    assert await store.owner_exists() is False


@pytest.mark.asyncio
async def test_create_owner_then_exists_true(session_factory) -> None:
    store = OwnerStore(session_factory)

    await store.create_owner(name="Eric", password_hash="$2b$12$fakehash")

    assert await store.owner_exists() is True


@pytest.mark.asyncio
async def test_get_owner_returns_record(session_factory) -> None:
    store = OwnerStore(session_factory)
    await store.create_owner(name="Eric", password_hash="$2b$12$fakehash")

    owner = await store.get_owner()

    assert owner is not None
    assert owner.name == "Eric"
    assert owner.password_hash == "$2b$12$fakehash"
    assert owner.role == "owner"


@pytest.mark.asyncio
async def test_get_owner_none_when_empty(session_factory) -> None:
    store = OwnerStore(session_factory)
    assert await store.get_owner() is None


@pytest.mark.asyncio
async def test_create_owner_refuses_second_owner(session_factory) -> None:
    store = OwnerStore(session_factory)
    await store.create_owner(name="Eric", password_hash="$2b$12$a")

    with pytest.raises(ValueError, match="owner already exists"):
        await store.create_owner(name="Bob", password_hash="$2b$12$b")

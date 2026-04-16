from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base, _install_sqlite_fk_pragma


@pytest.mark.asyncio
async def test_agent_binding_record_can_insert_and_load() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

    async with factory() as session:
        provider = LLMProviderRecord(
            name="p1",
            provider_type="anthropic",
            api_key_enc="x",
            model="claude-opus-4-6",
            is_default=False,
        )
        session.add(provider)
        await session.flush()
        binding = AgentLLMBindingRecord(agent_type="forge", provider_id=provider.id)
        session.add(binding)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(AgentLLMBindingRecord))
        loaded = result.scalars().all()
        assert len(loaded) == 1
        assert loaded[0].agent_type == "forge"
        assert loaded[0].provider_id == provider.id
        assert isinstance(loaded[0].updated_at, datetime)
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_binding_provider_on_delete_set_null() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

    async with factory() as session:
        provider = LLMProviderRecord(
            name="p1",
            provider_type="anthropic",
            api_key_enc="x",
            model="claude-opus-4-6",
            is_default=False,
        )
        session.add(provider)
        await session.flush()
        provider_id = provider.id
        binding = AgentLLMBindingRecord(agent_type="forge", provider_id=provider_id)
        session.add(binding)
        await session.commit()

        # Delete the provider - binding should be set to NULL, not removed
        await session.delete(provider)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(AgentLLMBindingRecord))
        loaded = result.scalars().all()
        assert len(loaded) == 1
        assert loaded[0].agent_type == "forge"
        assert loaded[0].provider_id is None
    await engine.dispose()

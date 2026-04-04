from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def registry_with_db():
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield LLMProviderRegistry(factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_registry_returns_env_fallback_when_no_default(
    registry_with_db, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fallback")
    from sebastian.llm.anthropic import AnthropicProvider

    provider = await registry_with_db.get_default()
    assert isinstance(provider, AnthropicProvider)


@pytest.mark.asyncio
async def test_registry_create_and_list(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="My Claude",
        provider_type="anthropic",
        api_key="sk-ant-abc",
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    assert len(records) == 1
    assert records[0].name == "My Claude"


@pytest.mark.asyncio
async def test_registry_get_default_uses_db_record(registry_with_db) -> None:
    from sebastian.llm.anthropic import AnthropicProvider
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="DB Claude",
        provider_type="anthropic",
        api_key="sk-ant-db",
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry_with_db.create(record)
    provider = await registry_with_db.get_default()
    assert isinstance(provider, AnthropicProvider)
    assert provider._client.api_key == "sk-ant-db"


@pytest.mark.asyncio
async def test_registry_delete(registry_with_db) -> None:
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="To Delete",
        provider_type="anthropic",
        api_key="sk-ant-del",
        model="claude-opus-4-6",
        is_default=False,
    )
    await registry_with_db.create(record)
    records = await registry_with_db.list_all()
    record_id = records[0].id
    deleted = await registry_with_db.delete(record_id)
    assert deleted is True
    assert await registry_with_db.list_all() == []

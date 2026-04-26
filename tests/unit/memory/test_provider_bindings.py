from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.crypto import encrypt
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base, _install_sqlite_fk_pragma
from sebastian.store.models import LLMAccountRecord


@pytest.fixture
async def registry_with_db(tmp_path, monkeypatch):
    data_subdir = tmp_path / "data"
    data_subdir.mkdir()
    key_file = data_subdir / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

    from sebastian.llm.registry import LLMProviderRegistry

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield LLMProviderRegistry(factory)
    await engine.dispose()


def test_memory_extractor_binding_constant() -> None:
    from sebastian.memory.provider_bindings import MEMORY_EXTRACTOR_BINDING

    assert MEMORY_EXTRACTOR_BINDING == "memory_extractor"


def test_memory_consolidator_binding_constant() -> None:
    from sebastian.memory.provider_bindings import MEMORY_CONSOLIDATOR_BINDING

    assert MEMORY_CONSOLIDATOR_BINDING == "memory_consolidator"


async def test_get_provider_memory_extractor_falls_back_to_default(
    registry_with_db,
) -> None:
    from sebastian.memory.provider_bindings import MEMORY_EXTRACTOR_BINDING

    account = LLMAccountRecord(
        name="default",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
    )
    await registry_with_db.create_account(account)

    await registry_with_db.set_binding("__default__", account.id, "claude-opus-4-7")

    resolved = await registry_with_db.get_provider(MEMORY_EXTRACTOR_BINDING)

    assert resolved.provider is not None
    assert resolved.model == "claude-opus-4-7"


async def test_get_provider_memory_consolidator_falls_back_to_default(
    registry_with_db,
) -> None:
    from sebastian.memory.provider_bindings import MEMORY_CONSOLIDATOR_BINDING

    account = LLMAccountRecord(
        name="default",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
    )
    await registry_with_db.create_account(account)

    await registry_with_db.set_binding("__default__", account.id, "claude-opus-4-7")

    resolved = await registry_with_db.get_provider(MEMORY_CONSOLIDATOR_BINDING)

    assert resolved.provider is not None
    assert resolved.model == "claude-opus-4-7"

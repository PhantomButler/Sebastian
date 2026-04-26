from __future__ import annotations

import pytest


def test_read_manifest_llm_removed() -> None:
    import sebastian.llm.registry as registry_mod

    assert not hasattr(registry_mod, "_read_manifest_llm"), (
        "_read_manifest_llm should have been removed; binding now lives in DB"
    )


def test_get_by_type_method_removed() -> None:
    from sebastian.llm.registry import LLMProviderRegistry

    assert not hasattr(LLMProviderRegistry, "_get_by_type"), (
        "_get_by_type is obsolete; resolution is by account_id via binding table"
    )


@pytest.mark.asyncio
async def test_registry_resolves_from_account_and_binding(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    key_file = user_data_dir / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from sebastian.llm.crypto import encrypt
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base, _install_sqlite_fk_pragma
    from sebastian.store.models import LLMAccountRecord

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = LLMProviderRegistry(factory)

    account = LLMAccountRecord(
        name="default",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
    )
    await registry.create_account(account)
    await registry.set_binding("__default__", account.id, "claude-sonnet-4-6")

    resolved = await registry.get_provider("forge")
    assert resolved.model == "claude-sonnet-4-6"
    await engine.dispose()

from __future__ import annotations

import pytest


def test_read_manifest_llm_removed() -> None:
    """`_read_manifest_llm` 必须已删除。"""
    import sebastian.llm.registry as registry_mod

    assert not hasattr(registry_mod, "_read_manifest_llm"), (
        "_read_manifest_llm should have been removed; binding now lives in DB"
    )


def test_get_by_type_method_removed() -> None:
    """Registry._get_by_type 必须已删除。"""
    from sebastian.llm.registry import LLMProviderRegistry

    assert not hasattr(LLMProviderRegistry, "_get_by_type"), (
        "_get_by_type is obsolete; resolution is by provider_id via binding table"
    )


@pytest.mark.asyncio
async def test_manifest_llm_section_is_ignored(tmp_path, monkeypatch) -> None:
    """即使 manifest 里残留 [llm] 段，也不应影响 provider 解析。"""
    key_file = tmp_path / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from sebastian.llm.crypto import encrypt
    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base, _install_sqlite_fk_pragma
    from sebastian.store.models import LLMProviderRecord

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = LLMProviderRegistry(factory)

    default = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-opus-4-6",
        is_default=True,
    )
    await registry.create(default)

    resolved = await registry.get_provider("forge")
    provider, model = resolved.provider, resolved.model
    assert model == "claude-opus-4-6"
    await engine.dispose()

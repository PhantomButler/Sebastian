from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.crypto import encrypt


@pytest_asyncio.fixture
async def registry(tmp_path, monkeypatch):
    user_data_dir = tmp_path / "data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    key_file = user_data_dir / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

    from sebastian.llm.registry import LLMProviderRegistry
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base, _install_sqlite_fk_pragma

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _install_sqlite_fk_pragma(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield LLMProviderRegistry(factory)
    await engine.dispose()


@pytest_asyncio.fixture
async def anthropic_account(registry) -> str:
    """Create a built-in Anthropic account and return its id."""
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="My Claude",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-ant-abc"),
    )
    await registry.create_account(record)
    return record.id


@pytest.mark.asyncio
async def test_no_default_binding_raises(registry) -> None:
    with pytest.raises(RuntimeError, match="No default LLM configured"):
        await registry.get_provider(None)


@pytest.mark.asyncio
async def test_create_and_list_accounts(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="My Claude",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-ant-abc"),
    )
    await registry.create_account(record)
    accounts = await registry.list_accounts()
    assert len(accounts) == 1
    assert accounts[0].name == "My Claude"
    assert accounts[0].catalog_provider_id == "anthropic"


@pytest.mark.asyncio
async def test_get_account(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="Test",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("key"),
    )
    await registry.create_account(record)
    fetched = await registry.get_account(record.id)
    assert fetched is not None
    assert fetched.name == "Test"
    assert await registry.get_account("nonexistent") is None


@pytest.mark.asyncio
async def test_update_account(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="Old",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("old-key"),
    )
    await registry.create_account(record)

    updated = await registry.update_account(record.id, name="New")
    assert updated is not None
    assert updated.name == "New"


@pytest.mark.asyncio
async def test_update_account_encrypts_api_key(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="Test",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("old-key"),
    )
    await registry.create_account(record)

    await registry.update_account(record.id, api_key="new-plain-key")
    refreshed = await registry.get_account(record.id)
    assert refreshed is not None
    from sebastian.llm.crypto import decrypt

    assert decrypt(refreshed.api_key_enc) == "new-plain-key"


@pytest.mark.asyncio
async def test_delete_account(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="To Delete",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("k"),
    )
    await registry.create_account(record)
    assert await registry.delete_account(record.id) is True
    assert await registry.get_account(record.id) is None
    assert await registry.delete_account("nonexistent") is False


@pytest.mark.asyncio
async def test_get_provider_uses_binding(registry, anthropic_account: str) -> None:
    from sebastian.llm.anthropic import AnthropicProvider

    await registry.set_binding(
        "forge", anthropic_account, "claude-opus-4-7", thinking_effort="high"
    )
    resolved = await registry.get_provider("forge")

    assert isinstance(resolved.provider, AnthropicProvider)
    assert resolved.model == "claude-opus-4-7"
    assert resolved.account_id == anthropic_account
    assert resolved.context_window_tokens == 1_000_000
    assert resolved.thinking_effort == "high"
    assert resolved.capability == "adaptive"
    assert resolved.thinking_format is None
    assert resolved.model_display_name == "Claude Opus 4.7"


@pytest.mark.asyncio
async def test_get_provider_falls_back_to_default(registry, anthropic_account: str) -> None:
    await registry.set_binding("__default__", anthropic_account, "claude-sonnet-4-6")
    resolved = await registry.get_provider("nonexistent-agent")

    assert resolved.model == "claude-sonnet-4-6"
    assert resolved.account_id == anthropic_account


@pytest.mark.asyncio
async def test_get_default_methods(registry, anthropic_account: str) -> None:
    await registry.set_binding("__default__", anthropic_account, "claude-haiku-4-5")

    provider = await registry.get_default()
    assert provider is not None

    provider2, model = await registry.get_default_with_model()
    assert model == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_thinking_coerced_by_capability(registry, anthropic_account: str) -> None:
    """claude-sonnet-4-6 has capability='adaptive'; effort='max' passes through."""
    await registry.set_binding(
        "forge", anthropic_account, "claude-sonnet-4-6", thinking_effort="max"
    )
    resolved = await registry.get_provider("forge")
    assert resolved.thinking_effort == "max"
    assert resolved.capability == "adaptive"


@pytest.mark.asyncio
async def test_thinking_effort_coerced_none_capability(registry) -> None:
    """claude-haiku-4-5 has capability='none'; effort is coerced to None."""
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="Test",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("k"),
    )
    await registry.create_account(record)
    await registry.set_binding("forge", record.id, "claude-haiku-4-5", thinking_effort="high")
    resolved = await registry.get_provider("forge")
    assert resolved.thinking_effort is None
    assert resolved.capability == "none"


@pytest.mark.asyncio
async def test_openai_provider_instantiation(registry) -> None:
    from sebastian.llm.openai_compat import OpenAICompatProvider
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="My OpenAI",
        catalog_provider_id="openai",
        provider_type="openai",
        api_key_enc=encrypt("sk-openai"),
    )
    await registry.create_account(record)
    await registry.set_binding("forge", record.id, "gpt-5.5")

    resolved = await registry.get_provider("forge")
    assert isinstance(resolved.provider, OpenAICompatProvider)
    assert resolved.model == "gpt-5.5"
    assert resolved.capability == "effort"


@pytest.mark.asyncio
async def test_base_url_override_wins(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="Custom Base",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("k"),
        base_url_override="https://custom-proxy.example.com",
    )
    await registry.create_account(record)
    await registry.set_binding("forge", record.id, "claude-sonnet-4-6")

    resolved = await registry.get_provider("forge")
    assert resolved.provider._client.base_url == "https://custom-proxy.example.com"


@pytest.mark.asyncio
async def test_catalog_base_url_used_when_no_override(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="Default URL",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("k"),
    )
    await registry.create_account(record)
    await registry.set_binding("forge", record.id, "claude-sonnet-4-6")

    resolved = await registry.get_provider("forge")
    assert resolved.provider._client.base_url == "https://api.anthropic.com"


@pytest.mark.asyncio
async def test_custom_account_without_override_raises(registry) -> None:
    from sebastian.store.models import LLMAccountRecord, LLMCustomModelRecord

    account = LLMAccountRecord(
        name="Custom",
        catalog_provider_id="custom",
        provider_type="openai",
        api_key_enc=encrypt("k"),
    )
    await registry.create_account(account)

    custom_model = LLMCustomModelRecord(
        account_id=account.id,
        model_id="my-local-model",
        display_name="My Local Model",
        context_window_tokens=32000,
        thinking_capability="none",
        thinking_format=None,
    )
    async with registry._db_factory() as session:
        session.add(custom_model)
        await session.commit()

    await registry.set_binding("forge", account.id, "my-local-model")

    with pytest.raises(RuntimeError, match="must have a base_url_override"):
        await registry.get_provider("forge")


@pytest.mark.asyncio
async def test_custom_account_with_override_works(registry) -> None:
    from sebastian.llm.openai_compat import OpenAICompatProvider
    from sebastian.store.models import LLMAccountRecord, LLMCustomModelRecord

    account = LLMAccountRecord(
        name="Custom",
        catalog_provider_id="custom",
        provider_type="openai",
        api_key_enc=encrypt("k"),
        base_url_override="http://localhost:8080/v1",
    )
    await registry.create_account(account)

    custom_model = LLMCustomModelRecord(
        account_id=account.id,
        model_id="my-local-model",
        display_name="My Local Model",
        context_window_tokens=32000,
        thinking_capability="always_on",
        thinking_format="think_tags",
    )
    async with registry._db_factory() as session:
        session.add(custom_model)
        await session.commit()

    await registry.set_binding("forge", account.id, "my-local-model")
    resolved = await registry.get_provider("forge")

    assert isinstance(resolved.provider, OpenAICompatProvider)
    assert resolved.model == "my-local-model"
    assert resolved.context_window_tokens == 32000
    assert resolved.capability == "always_on"
    assert resolved.thinking_format == "think_tags"
    assert resolved.thinking_effort is None
    assert resolved.model_display_name == "My Local Model"


@pytest.mark.asyncio
async def test_custom_model_not_found_raises(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    account = LLMAccountRecord(
        name="Custom",
        catalog_provider_id="custom",
        provider_type="openai",
        api_key_enc=encrypt("k"),
        base_url_override="http://localhost:8080/v1",
    )
    await registry.create_account(account)
    await registry.set_binding("forge", account.id, "nonexistent-model")

    with pytest.raises(RuntimeError, match="Custom model.*not found"):
        await registry.get_provider("forge")


@pytest.mark.asyncio
async def test_get_model_spec_builtin(registry, anthropic_account: str) -> None:
    account = await registry.get_account(anthropic_account)
    assert account is not None
    spec = await registry.get_model_spec(account, "claude-sonnet-4-6")
    assert spec.id == "claude-sonnet-4-6"
    assert spec.display_name == "Claude Sonnet 4.6"
    assert spec.context_window_tokens == 1_000_000
    assert spec.thinking_capability == "adaptive"


@pytest.mark.asyncio
async def test_get_model_spec_custom(registry) -> None:
    from sebastian.store.models import LLMAccountRecord, LLMCustomModelRecord

    account = LLMAccountRecord(
        name="Custom",
        catalog_provider_id="custom",
        provider_type="openai",
        api_key_enc=encrypt("k"),
    )
    await registry.create_account(account)

    custom_model = LLMCustomModelRecord(
        account_id=account.id,
        model_id="local-qwen",
        display_name="Local Qwen",
        context_window_tokens=64000,
        thinking_capability="always_on",
        thinking_format="reasoning_content",
    )
    async with registry._db_factory() as session:
        session.add(custom_model)
        await session.commit()

    spec = await registry.get_model_spec(account, "local-qwen")
    assert spec.id == "local-qwen"
    assert spec.context_window_tokens == 64000
    assert spec.thinking_format == "reasoning_content"


@pytest.mark.asyncio
async def test_binding_account_not_found_raises(registry) -> None:
    """Binding references a deleted account → RuntimeError."""
    await registry.set_binding("forge", "nonexistent-account-id", "some-model")

    with pytest.raises(RuntimeError, match="Account.*not found"):
        await registry.get_provider("forge")

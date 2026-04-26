from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.crypto import encrypt
from sebastian.store import models  # noqa: F401
from sebastian.store.database import Base, _install_sqlite_fk_pragma


@pytest_asyncio.fixture
async def registry(tmp_path, monkeypatch):
    user_data_dir = tmp_path / "data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    key_file = user_data_dir / "secret.key"
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


@pytest_asyncio.fixture
async def account_a_id(registry) -> str:
    from sebastian.store.models import LLMAccountRecord

    r = LLMAccountRecord(
        name="A",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("k1"),
    )
    await registry.create_account(r)
    return r.id


@pytest_asyncio.fixture
async def account_b_id(registry) -> str:
    from sebastian.store.models import LLMAccountRecord

    r = LLMAccountRecord(
        name="B",
        catalog_provider_id="openai",
        provider_type="openai",
        api_key_enc=encrypt("k2"),
    )
    await registry.create_account(r)
    return r.id


@pytest.mark.asyncio
async def test_set_and_get_binding(registry, account_a_id: str) -> None:
    binding = await registry.set_binding("forge", account_a_id, "claude-opus-4-7")
    assert binding.agent_type == "forge"
    assert binding.account_id == account_a_id
    assert binding.model_id == "claude-opus-4-7"

    fetched = await registry.get_binding("forge")
    assert fetched is not None
    assert fetched.account_id == account_a_id
    assert fetched.model_id == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_list_bindings(registry, account_a_id: str) -> None:
    await registry.set_binding("forge", account_a_id, "claude-opus-4-7")
    await registry.set_binding("sebastian", account_a_id, "claude-sonnet-4-6")

    bindings = await registry.list_bindings()
    assert len(bindings) == 2
    types = {b.agent_type for b in bindings}
    assert types == {"forge", "sebastian"}


@pytest.mark.asyncio
async def test_set_binding_upsert_overwrites(
    registry, account_a_id: str, account_b_id: str
) -> None:
    await registry.set_binding("forge", account_a_id, "claude-opus-4-7")
    await registry.set_binding("forge", account_b_id, "gpt-5.5", thinking_effort="low")

    bindings = await registry.list_bindings()
    assert len(bindings) == 1
    assert bindings[0].account_id == account_b_id
    assert bindings[0].model_id == "gpt-5.5"
    assert bindings[0].thinking_effort == "low"


@pytest.mark.asyncio
async def test_clear_binding_removes_row(registry, account_a_id: str) -> None:
    await registry.set_binding("forge", account_a_id, "claude-opus-4-7")
    await registry.clear_binding("forge")
    assert await registry.list_bindings() == []


@pytest.mark.asyncio
async def test_clear_binding_noop_when_missing(registry) -> None:
    await registry.clear_binding("nonexistent")
    assert await registry.list_bindings() == []


@pytest.mark.asyncio
async def test_get_binding_returns_none_when_missing(registry) -> None:
    assert await registry.get_binding("nonexistent") is None


@pytest.mark.asyncio
async def test_binding_with_thinking_effort(registry, account_a_id: str) -> None:
    await registry.set_binding("forge", account_a_id, "claude-sonnet-4-6", thinking_effort="medium")
    fetched = await registry.get_binding("forge")
    assert fetched is not None
    assert fetched.thinking_effort == "medium"


@pytest.mark.asyncio
async def test_binding_null_thinking_effort(registry, account_a_id: str) -> None:
    await registry.set_binding("forge", account_a_id, "claude-opus-4-7", thinking_effort=None)
    fetched = await registry.get_binding("forge")
    assert fetched is not None
    assert fetched.thinking_effort is None


@pytest.mark.asyncio
async def test_get_provider_uses_explicit_binding(
    registry, account_a_id: str, account_b_id: str
) -> None:
    await registry.set_binding("__default__", account_a_id, "claude-opus-4-7")
    await registry.set_binding("forge", account_b_id, "gpt-5.5")

    resolved = await registry.get_provider("forge")
    assert resolved.model == "gpt-5.5"
    assert resolved.account_id == account_b_id


@pytest.mark.asyncio
async def test_get_provider_falls_back_to_default(registry, account_a_id: str) -> None:
    await registry.set_binding("__default__", account_a_id, "claude-sonnet-4-6")

    resolved = await registry.get_provider("unbound-agent")
    assert resolved.model == "claude-sonnet-4-6"
    assert resolved.account_id == account_a_id


@pytest.mark.asyncio
async def test_delete_account_does_not_check_bindings(registry, account_a_id: str) -> None:
    """delete_account should succeed even if bindings reference it."""
    await registry.set_binding("forge", account_a_id, "claude-opus-4-7")
    assert await registry.delete_account(account_a_id) is True

    binding = await registry.get_binding("forge")
    assert binding is not None
    assert binding.account_id == account_a_id

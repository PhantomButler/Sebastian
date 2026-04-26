from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.crypto import encrypt
from sebastian.llm.registry import (
    LLMProviderRegistry,
    ResolvedProvider,
    _coerce_thinking,
)

# ---------------------------------------------------------------------------
# Pure-logic tests (no DB)
# ---------------------------------------------------------------------------


def test_coerce_capability_none_clears_effort():
    assert _coerce_thinking("high", "none") is None


def test_coerce_capability_always_on_clears_effort():
    assert _coerce_thinking("high", "always_on") is None


def test_coerce_effort_drops_max():
    assert _coerce_thinking("max", "effort") == "high"


def test_coerce_toggle_normalizes_values():
    assert _coerce_thinking("high", "toggle") == "on"
    assert _coerce_thinking("off", "toggle") == "off"


def test_coerce_adaptive_passes_through():
    assert _coerce_thinking("max", "adaptive") == "max"


def test_coerce_none_capability_returns_none():
    # None capability is treated as "no thinking" — effort is not meaningful
    assert _coerce_thinking("high", None) is None


def test_coerce_thinking_rejects_invalid_effort_for_effort_capability() -> None:
    assert _coerce_thinking("ultra", "effort") is None


def test_coerce_thinking_rejects_invalid_effort_for_adaptive_capability() -> None:
    assert _coerce_thinking("ultra", "adaptive") is None


# ---------------------------------------------------------------------------
# DB-backed async tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry(tmp_path, monkeypatch):
    data_subdir = tmp_path / "data"
    data_subdir.mkdir()
    key_file = data_subdir / "secret.key"
    key_file.write_text("test-secret")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(tmp_path))

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
async def default_account_id(registry) -> str:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="default-anthropic",
        catalog_provider_id="anthropic",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
    )
    await registry.create_account(record)
    return record.id


@pytest.mark.asyncio
async def test_resolved_provider_has_new_fields(registry, default_account_id: str) -> None:
    await registry.set_binding(
        "__default__", default_account_id, "claude-opus-4-7", thinking_effort="high"
    )
    resolved = await registry.get_provider("forge")

    assert isinstance(resolved, ResolvedProvider)
    assert resolved.model == "claude-opus-4-7"
    assert resolved.thinking_effort == "high"
    assert resolved.capability == "adaptive"
    assert resolved.context_window_tokens == 1_000_000
    assert resolved.thinking_format is None
    assert resolved.account_id == default_account_id
    assert resolved.model_display_name == "Claude Opus 4.7"


@pytest.mark.asyncio
async def test_fallback_to_default_binding(registry, default_account_id: str) -> None:
    await registry.set_binding("__default__", default_account_id, "claude-haiku-4-5")
    resolved = await registry.get_provider("some-agent")

    assert resolved.model == "claude-haiku-4-5"
    assert resolved.context_window_tokens == 200_000
    assert resolved.capability == "none"
    assert resolved.thinking_effort is None


@pytest.mark.asyncio
async def test_effort_coerced_max_to_high(registry, default_account_id: str) -> None:
    """capability='effort' (openai/gpt-5.5), effort='max' → coerced to 'high'."""
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="openai",
        catalog_provider_id="openai",
        provider_type="openai",
        api_key_enc=encrypt("sk-openai"),
    )
    await registry.create_account(record)

    await registry.set_binding("forge", record.id, "gpt-5.5", thinking_effort="max")
    resolved = await registry.get_provider("forge")

    assert resolved.thinking_effort == "high"
    assert resolved.capability == "effort"


@pytest.mark.asyncio
async def test_deepseek_thinking_format(registry) -> None:
    from sebastian.store.models import LLMAccountRecord

    record = LLMAccountRecord(
        name="deepseek",
        catalog_provider_id="deepseek",
        provider_type="openai",
        api_key_enc=encrypt("sk-ds"),
    )
    await registry.create_account(record)
    await registry.set_binding("forge", record.id, "deepseek-v4-pro")

    resolved = await registry.get_provider("forge")
    assert resolved.thinking_format == "reasoning_content"
    assert resolved.capability == "toggle"
    assert resolved.model_display_name == "DeepSeek V4 Pro"

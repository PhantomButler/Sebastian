from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider, _coerce_thinking


# ---------------------------------------------------------------------------
# Pure-logic tests (no DB)
# ---------------------------------------------------------------------------


def test_coerce_capability_none_clears_all():
    assert _coerce_thinking("high", True, "none") == (None, False)


def test_coerce_capability_always_on_clears_all():
    assert _coerce_thinking("high", True, "always_on") == (None, False)


def test_coerce_effort_drops_max_and_adaptive():
    assert _coerce_thinking("max", True, "effort") == ("high", False)


def test_coerce_toggle_drops_effort_values():
    assert _coerce_thinking("high", False, "toggle") == ("on", False)
    assert _coerce_thinking("off", False, "toggle") == ("off", False)


def test_coerce_adaptive_keeps_all():
    assert _coerce_thinking("max", True, "adaptive") == ("max", True)


def test_coerce_none_capability_returns_unmodified():
    # capability is None → pass through
    assert _coerce_thinking("high", False, None) == ("high", False)


# ---------------------------------------------------------------------------
# DB-backed async tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry(tmp_path, monkeypatch):
    """In-memory SQLite registry fixture, mirrors pattern in test_registry_bindings.py."""
    key_file = tmp_path / "secret.key"
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


@pytest.mark.asyncio
async def test_set_binding_stores_thinking(registry) -> None:
    """set_binding 带 effort/adaptive，get_provider 应返回对应钳制结果。"""
    from sebastian.llm.crypto import encrypt
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="adaptive-provider",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-adaptive"),
        model="claude-opus-4-6",
        thinking_capability="adaptive",
        is_default=True,
    )
    await registry.create(record)
    records = await registry.list_all()
    pid = records[0].id

    await registry.set_binding("forge", pid, thinking_effort="high", thinking_adaptive=True)
    resolved = await registry.get_provider("forge")

    assert isinstance(resolved, ResolvedProvider)
    assert resolved.model == "claude-opus-4-6"
    assert resolved.thinking_effort == "high"
    assert resolved.thinking_adaptive is True
    assert resolved.capability == "adaptive"


@pytest.mark.asyncio
async def test_get_provider_falls_back_to_default_when_no_binding(registry) -> None:
    from sebastian.llm.crypto import encrypt
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="default",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-default"),
        model="claude-haiku-4-5",
        thinking_capability="none",
        is_default=True,
    )
    await registry.create(record)

    resolved = await registry.get_provider("some-agent")
    assert isinstance(resolved, ResolvedProvider)
    assert resolved.model == "claude-haiku-4-5"
    assert resolved.thinking_effort is None
    assert resolved.thinking_adaptive is False


@pytest.mark.asyncio
async def test_get_provider_coerces_max_down_in_effort_capability(registry) -> None:
    """存入 capability=effort 的 provider，binding 设 effort=max adaptive=True，
    get_provider 应钳制返回 (high, False)。"""
    from sebastian.llm.crypto import encrypt
    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="effort-provider",
        provider_type="anthropic",
        api_key_enc=encrypt("sk-effort"),
        model="claude-sonnet-4-6",
        thinking_capability="effort",
        is_default=True,
    )
    await registry.create(record)
    records = await registry.list_all()
    pid = records[0].id

    await registry.set_binding("forge", pid, thinking_effort="max", thinking_adaptive=True)
    resolved = await registry.get_provider("forge")

    assert resolved.thinking_effort == "high"
    assert resolved.thinking_adaptive is False
    assert resolved.capability == "effort"

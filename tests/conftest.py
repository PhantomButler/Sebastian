from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session for unit tests."""
    from sebastian.store import models  # noqa: F401
    from sebastian.store.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """确保每个测试都有临时 secret.key，防止 config/auth 加载失败。"""
    data_dir = tmp_path / "_sebastian_test_data"
    data_dir.mkdir()
    key_file = data_dir / "secret.key"
    key_file.write_text("test-secret-key")
    monkeypatch.setattr("sebastian.config.settings.sebastian_data_dir", str(data_dir))


@pytest.fixture(autouse=True)
def _reset_event_bus() -> Generator[None, None, None]:
    yield
    from sebastian.protocol.events.bus import bus

    bus.reset()


@pytest.fixture(autouse=True)
def _reset_jwt_signer() -> Generator[None, None, None]:
    """Drop cached JwtSigner between tests so each test starts with a fresh signer.

    The signer is a module-level singleton in `sebastian.gateway.auth`; without
    this fixture, a test that writes a different secret.key or monkeypatches
    settings after another test has already materialized the signer would silently
    get stale state.
    """
    yield
    from sebastian.gateway.auth import reset_signer

    reset_signer()


@pytest.fixture(autouse=True)
def _reset_default_planner() -> Generator[None, None, None]:
    """Reset DEFAULT_RETRIEVAL_PLANNER singleton between tests.

    The planner accumulates entity triggers via bootstrap/reload; without
    cleanup, entity names from one test leak into subsequent tests.
    """
    from sebastian.memory.retrieval import DEFAULT_RETRIEVAL_PLANNER
    from sebastian.memory.retrieval_lexicon import RELATION_LANE_STATIC_WORDS

    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS
    yield
    DEFAULT_RETRIEVAL_PLANNER._relation_trigger_set = RELATION_LANE_STATIC_WORDS

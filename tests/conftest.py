from __future__ import annotations

from collections.abc import Generator

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
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保每个测试都有必要的环境变量，防止 config 加载失败。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret-key")


@pytest.fixture(autouse=True)
def _reset_event_bus() -> Generator[None, None, None]:
    yield
    from sebastian.protocol.events.bus import bus
    bus.reset()

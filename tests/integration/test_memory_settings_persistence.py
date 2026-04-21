from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.app_settings_store import APP_SETTING_MEMORY_ENABLED, AppSettingsStore
from sebastian.store.database import Base


@pytest_asyncio.fixture
async def db_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db", future=True)
    async with engine.begin() as conn:
        from sebastian.store import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_enabled_persisted_as_false(db_session) -> None:
    """PUT endpoint logic: after setting memory_enabled=false, DB stores 'false'."""
    store = AppSettingsStore(db_session)
    await store.set(APP_SETTING_MEMORY_ENABLED, "false")
    await db_session.commit()

    result = await store.get(APP_SETTING_MEMORY_ENABLED)
    assert result == "false"


@pytest.mark.asyncio
async def test_startup_reads_db_value_over_env_default(db_session) -> None:
    """Simulate gateway startup: DB value 'false' should override env default True."""
    store = AppSettingsStore(db_session)
    await store.set(APP_SETTING_MEMORY_ENABLED, "false")
    await db_session.commit()

    raw = await store.get(APP_SETTING_MEMORY_ENABLED)
    env_default = True
    mem_enabled = (raw.lower() == "true") if raw is not None else env_default
    assert mem_enabled is False


@pytest.mark.asyncio
async def test_startup_falls_back_to_env_when_db_empty(db_session) -> None:
    """When DB has no memory_enabled key, env default is used."""
    store = AppSettingsStore(db_session)
    raw = await store.get(APP_SETTING_MEMORY_ENABLED)
    env_default = True
    mem_enabled = (raw.lower() == "true") if raw is not None else env_default
    assert mem_enabled is True

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.soul_loader import SoulLoader
from sebastian.gateway.app import _restore_active_soul
from sebastian.store.app_settings_store import APP_SETTING_ACTIVE_SOUL, AppSettingsStore
from sebastian.store.models import Base

_BUILTIN = {"sebastian": "You are Sebastian.", "cortana": "You are Cortana."}


@pytest.fixture
async def db_factory(tmp_path: Path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def soul_loader(tmp_path: Path) -> SoulLoader:
    loader = SoulLoader(souls_dir=tmp_path / "souls", builtin_souls=_BUILTIN)
    loader.ensure_defaults()
    return loader


def _make_sebastian(persona: str = "You are Sebastian.") -> MagicMock:
    agent = MagicMock()
    agent.persona = persona
    agent.system_prompt = ""
    agent._gate = MagicMock()
    agent._agent_registry = {}
    agent.build_system_prompt = MagicMock(return_value="rebuilt_prompt")
    return agent


@pytest.mark.asyncio
async def test_restore_uses_active_soul_from_db(db_factory, soul_loader):
    async with db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_ACTIVE_SOUL, "cortana")
        await session.commit()

    agent = _make_sebastian()
    await _restore_active_soul(soul_loader, db_factory, agent)

    assert agent.persona == "You are Cortana."
    assert agent.system_prompt == "rebuilt_prompt"
    assert soul_loader.current_soul == "cortana"


@pytest.mark.asyncio
async def test_restore_defaults_to_sebastian_when_no_setting(db_factory, soul_loader):
    agent = _make_sebastian()
    await _restore_active_soul(soul_loader, db_factory, agent)

    assert agent.persona == "You are Sebastian."
    assert soul_loader.current_soul == "sebastian"


@pytest.mark.asyncio
async def test_restore_falls_back_to_hardcoded_when_file_missing(db_factory, soul_loader):
    async with db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_ACTIVE_SOUL, "ghost")
        await session.commit()

    agent = _make_sebastian(persona="HARDCODED")
    original_persona = agent.persona
    await _restore_active_soul(soul_loader, db_factory, agent)

    # soul file missing → persona unchanged, system_prompt NOT rebuilt
    assert agent.persona == original_persona
    agent.build_system_prompt.assert_not_called()

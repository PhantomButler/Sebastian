from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_state(souls_dir: Path, current_soul: str = "sebastian") -> MagicMock:
    from sebastian.core.soul_loader import SoulLoader

    loader = SoulLoader(
        souls_dir=souls_dir,
        builtin_souls={"sebastian": "You are Sebastian.", "cortana": "You are Cortana."},
    )
    loader.ensure_defaults()
    loader.current_soul = current_soul

    sebastian = MagicMock()
    sebastian.persona = "You are Sebastian."
    sebastian.system_prompt = "old_prompt"
    sebastian._gate = MagicMock()
    sebastian._agent_registry = {}
    sebastian.build_system_prompt = MagicMock(return_value="new_prompt")

    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    db_session = AsyncMock()
    db_session.execute = AsyncMock(return_value=execute_result)
    db_session.add = MagicMock()
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(return_value=db_session)
    db_cm.__aexit__ = AsyncMock(return_value=None)
    db_factory = MagicMock(return_value=db_cm)

    state = MagicMock()
    state.soul_loader = loader
    state.sebastian = sebastian
    state.db_factory = db_factory
    return state


@pytest.mark.asyncio
async def test_switch_soul_list(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path)
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("list")

    assert result.ok is True
    assert "sebastian" in result.output
    assert "cortana" in result.output


@pytest.mark.asyncio
async def test_switch_soul_already_active(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("sebastian")

    assert result.ok is True
    assert "已经在了" in result.output
    state.sebastian.build_system_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_switch_soul_file_not_found(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path)
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("ghost")

    assert result.ok is False
    assert "Do not retry automatically" in result.error
    assert "ghost" in result.error


@pytest.mark.asyncio
async def test_switch_soul_success(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("cortana")

    assert result.ok is True
    assert "cortana" in result.output
    assert state.sebastian.persona == "You are Cortana."
    assert state.sebastian.system_prompt == "new_prompt"
    assert state.soul_loader.current_soul == "cortana"
    # 验证 DB 持久化：commit 必须被调用，否则重启后 soul 不会恢复
    db_session = state.db_factory.return_value.__aenter__.return_value
    db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_soul_db_failure(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    # make db_factory raise on __aenter__
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))
    db_cm.__aexit__ = AsyncMock(return_value=None)
    state.db_factory = MagicMock(return_value=db_cm)

    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("cortana")

    assert result.ok is False
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_switch_soul_unexpected_exception(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    with patch(
        "sebastian.capabilities.tools.switch_soul._get_state", side_effect=RuntimeError("boom")
    ):
        result = await switch_soul("cortana")

    assert result.ok is False
    assert "Do not retry automatically" in result.error

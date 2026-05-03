from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_switch_soul_tool_description_frames_identity_as_front_stage_butler() -> None:
    import sebastian.capabilities.tools.switch_soul  # noqa: F401  # registers tool
    from sebastian.core.tool import get_tool

    entry = get_tool("switch_soul")

    assert entry is not None
    spec, _ = entry
    assert "当前前台管家身份配置" in spec.description
    assert "不要在面向用户的回复中自称为 soul、persona、配置或系统组成部分" in spec.description


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

    def _rebuild_system_prompt() -> None:
        sebastian.system_prompt = sebastian.build_system_prompt(
            sebastian._gate, sebastian._agent_registry
        )

    sebastian.rebuild_system_prompt = MagicMock(side_effect=_rebuild_system_prompt)

    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    db_session = AsyncMock()
    db_session.execute = AsyncMock(return_value=execute_result)
    db_session.add = MagicMock()
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(return_value=db_session)
    db_cm.__aexit__ = AsyncMock(return_value=None)
    db_factory = MagicMock(return_value=db_cm)

    event_bus = AsyncMock()

    state = MagicMock()
    state.soul_loader = loader
    state.sebastian = sebastian
    state.db_factory = db_factory
    state.event_bus = event_bus  # ← new
    return state


@pytest.mark.asyncio
async def test_switch_soul_list(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="cortana")
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("list")

    assert result.ok is True
    assert result.output == {"current": "cortana", "available": ["cortana", "sebastian"]}
    assert result.display is not None
    assert "- cortana (当前)" in result.display
    assert "- sebastian" in result.display


@pytest.mark.asyncio
async def test_switch_soul_list_restores_deleted_builtin_souls(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    (tmp_path / "cortana.md").unlink()

    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("list")

    assert result.ok is True
    assert result.output == {"current": "sebastian", "available": ["cortana", "sebastian"]}
    assert (tmp_path / "cortana.md").read_text(encoding="utf-8") == "You are Cortana."


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
    # soul.changed 事件必须被发布
    state.event_bus.publish.assert_awaited_once()
    published_event = state.event_bus.publish.call_args[0][0]
    assert published_event.data["soul_name"] == "cortana"


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
    # DB 失败时 soul_loader.current_soul 不能被修改
    assert state.soul_loader.current_soul == "sebastian"


@pytest.mark.asyncio
async def test_switch_soul_unexpected_exception(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    with patch(
        "sebastian.capabilities.tools.switch_soul._get_state", side_effect=RuntimeError("boom")
    ):
        result = await switch_soul("cortana")

    assert result.ok is False
    assert "Do not retry automatically" in result.error

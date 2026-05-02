from __future__ import annotations

import logging
from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.store.app_settings_store import APP_SETTING_ACTIVE_SOUL, AppSettingsStore

logger = logging.getLogger(__name__)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="switch_soul",
    description=(
        "列出或切换 Sebastian 的当前人格（soul）。"
        "soul_name='list' 查看可用列表，其他值执行切换。"
    ),
    permission_tier=PermissionTier.LOW,
    display_name="Soul",
)
async def switch_soul(soul_name: str) -> ToolResult:
    try:
        state = _get_state()
        soul_loader = state.soul_loader
        soul_loader.ensure_defaults()

        if soul_name == "list":
            souls = soul_loader.list_souls()
            return ToolResult(ok=True, output=souls, display=", ".join(souls))

        if soul_name == soul_loader.current_soul:
            msg = f"{soul_name} 已经在了，无需切换"
            return ToolResult(ok=True, output=msg, display=msg)

        content = soul_loader.load(soul_name)
        if content is None:
            return ToolResult(
                ok=False,
                error=(
                    f"找不到 soul: {soul_name}。Do not retry automatically；"
                    "请先调用 switch_soul('list') 查看可用列表"
                ),
            )

        try:
            async with state.db_factory() as session:
                store = AppSettingsStore(session)
                await store.set(APP_SETTING_ACTIVE_SOUL, soul_name)
                await session.commit()
        except Exception as e:
            return ToolResult(
                ok=False,
                error=f"切换失败: {e}。Do not retry automatically；请向用户报告此错误",
            )

        soul_loader.current_soul = soul_name
        state.sebastian.persona = content
        state.sebastian.system_prompt = state.sebastian.build_system_prompt(
            state.sebastian._gate, state.sebastian._agent_registry
        )
        msg = f"已切换到 {soul_name}"
        return ToolResult(ok=True, output=msg, display=msg)

    except Exception as e:
        logger.exception("switch_soul unexpected error: %s", e)
        return ToolResult(
            ok=False,
            error=f"switch_soul 内部错误: {e}。Do not retry automatically；请向用户报告此错误",
        )

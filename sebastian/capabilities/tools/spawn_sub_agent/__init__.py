from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import Session, ToolResult

logger = logging.getLogger(__name__)


def _get_state():
    import sebastian.gateway.state as state
    return state


@tool(
    name="spawn_sub_agent",
    description="分派子任务给组员处理。组员异步执行，你可以继续处理其他工作。",
)
async def spawn_sub_agent(
    goal: str,
    context: str = "",
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    if _ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")

    state = _get_state()
    agent_type = _ctx.agent_type
    parent_session_id = _ctx.session_id

    config = state.agent_registry.get(agent_type)
    if config is None:
        return ToolResult(ok=False, error=f"未知的 Agent 类型: {agent_type}")

    active = await state.index_store.list_active_children(agent_type, parent_session_id)
    if len(active) >= config.max_children:
        return ToolResult(
            ok=False,
            error=f"当前已有{len(active)}个组员在工作，已达上限{config.max_children}",
        )

    session = Session(
        agent_type=agent_type,
        title=goal[:40],
        depth=3,
        parent_session_id=parent_session_id,
    )
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    if agent_type not in state.agent_instances:
        return ToolResult(ok=False, error=f"Agent {agent_type} 尚未初始化")
    agent = state.agent_instances[agent_type]
    full_goal = f"{goal}\n\n背景信息：{context}" if context else goal

    from sebastian.core.session_runner import run_agent_session

    asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=full_goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )

    return ToolResult(ok=True, output=f"已安排组员处理：{goal}")

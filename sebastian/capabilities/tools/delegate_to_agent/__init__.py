from __future__ import annotations

import asyncio
import logging
from types import ModuleType
from typing import Any

from sebastian.core.tool import tool
from sebastian.core.types import Session, ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)


def _log_task_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Background agent session failed", exc_info=exc)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="delegate_to_agent",
    description="委派任务给指定的下属 Agent。任务将异步执行，你可以继续处理其他事务。",
    permission_tier=PermissionTier.LOW,
)
async def delegate_to_agent(
    agent_type: str,
    goal: str,
    context: str = "",
) -> ToolResult:
    state = _get_state()

    if agent_type not in state.agent_instances:
        return ToolResult(ok=False, error=f"未知的 Agent 类型: {agent_type}")

    session = Session(
        agent_type=agent_type,
        title=goal[:40],
        goal=goal,
        depth=2,
    )
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    agent = state.agent_instances[agent_type]
    full_goal = f"{goal}\n\n背景信息：{context}" if context else goal

    from sebastian.core.session_runner import run_agent_session

    task = asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=full_goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )
    task.add_done_callback(_log_task_failure)

    return ToolResult(ok=True, output=f"已安排 {agent_type.capitalize()} 处理：{goal}")

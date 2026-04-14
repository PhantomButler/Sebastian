from __future__ import annotations

import asyncio
import logging
from types import ModuleType
from typing import Any

from sebastian.core.tool import tool
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)


def _log_task_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("reply_to_agent: background session failed", exc_info=exc)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="reply_to_agent",
    description="向等待指示的子代理发送回复，恢复其任务执行。",
    permission_tier=PermissionTier.LOW,
)
async def reply_to_agent(session_id: str, instruction: str) -> ToolResult:
    state = _get_state()

    # 从 index_store 找到该 session 的基本信息
    all_sessions = await state.index_store.list_all()
    index_entry = next((s for s in all_sessions if s.get("id") == session_id), None)
    if index_entry is None:
        return ToolResult(ok=False, error=f"找不到 session: {session_id}")

    if index_entry.get("status") != SessionStatus.WAITING:
        return ToolResult(
            ok=False,
            error=f"session {session_id} 当前状态为 {index_entry.get('status')}，不在等待状态",
        )

    agent_type: str = index_entry.get("agent_type", "")
    session = await state.session_store.get_session(session_id, agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"找不到 session 数据: {session_id}")

    # 将指示写入子代理的对话历史
    await state.session_store.append_message(
        session_id,
        role="user",
        content=instruction,
        agent_type=agent_type,
    )

    # 找到对应 agent 实例
    agent = state.agent_instances.get(agent_type)
    if agent is None:
        return ToolResult(ok=False, error=f"Agent {agent_type} 未初始化")

    # 恢复 session 状态并重新启动
    session.status = SessionStatus.ACTIVE
    await state.session_store.update_session(session)
    await state.index_store.upsert(session)

    from sebastian.core.session_runner import run_agent_session

    task = asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=session.goal,
            session_store=state.session_store,
            index_store=state.index_store,
            event_bus=state.event_bus,
        )
    )
    task.add_done_callback(_log_task_failure)

    return ToolResult(ok=True, output="已向子代理发送指示，任务已恢复执行。")

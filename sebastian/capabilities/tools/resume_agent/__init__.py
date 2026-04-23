from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from sebastian.capabilities.tools._session_lock import get_session_lock
from sebastian.capabilities.tools._session_permission import assert_session_action_permission
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import Session, SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

_MISSING_CONTEXT_ERROR = (
    "工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。"
    "请向上汇报'内部上下文缺失，无法执行 resume_agent'，不要重试此工具。"
)
_RESUMABLE_STATUSES = {SessionStatus.WAITING.value, SessionStatus.IDLE.value}


def _log_task_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("resume_agent: background session failed", exc_info=exc)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


async def _schedule_session(*, state: ModuleType, agent: Any, session: Session) -> None:
    from sebastian.core.session_runner import run_agent_session

    task = asyncio.create_task(
        run_agent_session(
            agent=agent,
            session=session,
            goal=session.goal,
            session_store=state.session_store,
            event_bus=state.event_bus,
        )
    )
    task.add_done_callback(_log_task_failure)


@tool(
    name="resume_agent",
    description="恢复已暂停或等待指示的子代理 session，并可附带新的执行指示。",
    permission_tier=PermissionTier.LOW,
)
async def resume_agent(
    agent_type: str,
    session_id: str,
    instruction: str = "",
) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(ok=False, error=_MISSING_CONTEXT_ERROR)

    state = _get_state()
    async with get_session_lock(session_id):
        all_sessions = await state.session_store.list_sessions()
        index_entry = next((s for s in all_sessions if s.get("id") == session_id), None)
        if index_entry is None:
            return ToolResult(
                ok=False,
                error=(
                    f"找不到 session: {session_id}。"
                    "请先用 check_sub_agents 确认当前可恢复的 session 列表，不要猜测 id。"
                ),
            )

        actual_agent_type = index_entry.get("agent_type", "")
        if actual_agent_type != agent_type:
            return ToolResult(
                ok=False,
                error=(
                    f"session {session_id} 属于 {actual_agent_type}，不是你传入的 {agent_type}。"
                    "请重新核对 check_sub_agents 输出里的 agent_type 字段再调用。"
                ),
            )

        permission_error = assert_session_action_permission(
            action="resume",
            ctx_session_id=ctx.session_id,
            ctx_depth=ctx.depth,
            index_entry=index_entry,
            session_id=session_id,
        )
        if permission_error is not None:
            return ToolResult(ok=False, error=permission_error)

        session = await state.session_store.get_session(session_id, actual_agent_type)
        if session is None:
            return ToolResult(
                ok=False,
                error=(
                    f"找不到 session 数据: {session_id}。数据可能已被清理，请先重新检查子代理列表。"
                ),
            )

        current_status = session.status.value
        if current_status not in _RESUMABLE_STATUSES:
            return ToolResult(
                ok=False,
                error=(
                    f"session {session_id} 当前 status={current_status}，无需恢复。"
                    "ACTIVE 状态说明它正在执行，COMPLETED/FAILED/CANCELLED 说明已结束；"
                    "请用 inspect_session 查看详情后再决定。"
                ),
            )

        agent = state.agent_instances.get(actual_agent_type)
        if agent is None:
            return ToolResult(
                ok=False,
                error=(
                    f"Agent {actual_agent_type} 未初始化。"
                    "这是运行时异常，请向上汇报，不要重试此工具。"
                ),
            )

        timeline_items: list[dict[str, str]] = [
            {"kind": "system_event", "role": "system", "content": f"Agent {session_id} resumed"}
        ]
        if instruction:
            timeline_items.append({"kind": "user_message", "role": "user", "content": instruction})
        await state.session_store.append_timeline_items(
            session_id,
            actual_agent_type,
            timeline_items,
        )

        session.status = SessionStatus.ACTIVE
        await state.session_store.update_session(session)

        if state.event_bus is not None:
            await state.event_bus.publish(
                Event(
                    type=EventType.SESSION_RESUMED,
                    data={
                        "session_id": session_id,
                        "agent_type": actual_agent_type,
                        "resumed_by": ctx.session_id,
                        "instruction": instruction,
                        "from_status": current_status,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            )

        await _schedule_session(state=state, agent=agent, session=session)

        if instruction:
            return ToolResult(ok=True, output=f"已恢复 session {session_id}，并追加新的执行指示。")
        return ToolResult(ok=True, output=f"已恢复 session {session_id}")

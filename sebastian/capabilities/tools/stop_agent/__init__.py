from __future__ import annotations

from datetime import UTC, datetime
from types import ModuleType

from sebastian.capabilities.tools._session_lock import get_session_lock
from sebastian.capabilities.tools._session_permission import assert_session_action_permission
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.protocol.events.types import Event, EventType

_MISSING_CONTEXT_ERROR = (
    "工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。"
    "请向上汇报'内部上下文缺失，无法执行 stop_agent'，不要重试此工具。"
)
_STOPPABLE_STATUSES = {SessionStatus.ACTIVE, SessionStatus.STALLED}
_TERMINAL_STATUSES = {
    SessionStatus.COMPLETED,
    SessionStatus.FAILED,
    SessionStatus.CANCELLED,
}


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="stop_agent",
    description="暂停指定 sub-agent session 的执行，保留上下文以便恢复。",
    permission_tier=PermissionTier.LOW,
    display_name="Stop Agent",
)
async def stop_agent(
    agent_type: str,
    session_id: str,
    reason: str = "",
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
                    "请用 check_sub_agents 确认当前活跃 session 列表，不要用猜的 id 重试。"
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
            action="stop",
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
                    f"找不到 session 数据: {session_id}。"
                    "数据可能已被清理，请用 check_sub_agents 重新列出。"
                ),
            )

        current_status = session.status
        if current_status == SessionStatus.IDLE:
            return ToolResult(ok=True, output=f"session {session_id} 已是 IDLE 状态")

        if current_status in _TERMINAL_STATUSES:
            return ToolResult(
                ok=False,
                error=(
                    f"session {session_id} 已结束（status={current_status.value}），无法停止。"
                    "如需查看结果，使用 inspect_session。"
                ),
            )

        if current_status not in _STOPPABLE_STATUSES:
            return ToolResult(
                ok=False,
                error=(
                    f"session {session_id} 当前 status={current_status.value}，无法停止。"
                    "只能停止 ACTIVE 或 STALLED 状态的 session。"
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

        cancelled = await agent.cancel_session(session_id, intent="stop")
        if not cancelled:
            return ToolResult(
                ok=False,
                error=(
                    f"停止 session {session_id} 失败：当前没有可中断的活动流。"
                    "请用 inspect_session 确认最新状态后再决定是否重试。"
                ),
            )

        session.status = SessionStatus.IDLE
        session.last_activity_at = datetime.now(UTC)
        await state.session_store.update_session(session)

        content = f"[上级暂停] reason: {reason}" if reason else "[上级暂停]"
        await state.session_store.append_timeline_items(
            session_id,
            actual_agent_type,
            [{"kind": "system_event", "role": "system", "content": content}],
        )

        if state.event_bus is not None:
            await state.event_bus.publish(
                Event(
                    type=EventType.SESSION_PAUSED,
                    data={
                        "session_id": session_id,
                        "agent_type": actual_agent_type,
                        "stopped_by": ctx.session_id,
                        "reason": reason,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            )

        return ToolResult(ok=True, output=f"已暂停 session {session_id}")

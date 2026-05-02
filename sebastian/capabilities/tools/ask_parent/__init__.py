from __future__ import annotations

from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import SessionStatus, ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.protocol.events.types import Event, EventType


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="ask_parent",
    description=(
        "遇到无法自行决定的问题时，暂停当前任务并向上级请求指示。上级回复前请勿继续执行任何操作。"
    ),
    permission_tier=PermissionTier.LOW,
    display_name="Ask Parent",
)
async def ask_parent(question: str) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")
    if ctx.depth == 1:
        return ToolResult(ok=False, error="Sebastian 没有上级，无法调用此工具")

    state = _get_state()

    session = await state.session_store.get_session(ctx.session_id, ctx.agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"找不到 session: {ctx.session_id}")

    session.status = SessionStatus.WAITING
    await state.session_store.update_session(session)

    await state.event_bus.publish(
        Event(
            type=EventType.SESSION_WAITING,
            data={
                "session_id": ctx.session_id,
                "parent_session_id": session.parent_session_id,
                "agent_type": ctx.agent_type,
                "goal": session.goal,
                "question": question,
            },
        )
    )

    return ToolResult(
        ok=True,
        output="已向上级请求指示，请等待回复后继续。请不要继续执行任何操作。",
    )

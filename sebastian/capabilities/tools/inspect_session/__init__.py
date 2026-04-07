from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.permissions.types import ToolCallContext

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


def _get_state():
    import sebastian.gateway.state as state
    return state


@tool(
    name="inspect_session",
    description="查看指定 session 的最近消息和当前状态，用于判断下属任务进展。",
)
async def inspect_session(
    session_id: str,
    recent_n: int = 5,
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    state = _get_state()

    all_sessions = await state.index_store.list_all()
    session_entry = next((s for s in all_sessions if s["id"] == session_id), None)
    if session_entry is None:
        return ToolResult(ok=False, error=f"Session {session_id} 未找到")

    agent_type = session_entry["agent_type"]
    session = await state.session_store.get_session(session_id, agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"Session {session_id} 数据不存在")

    messages = await state.session_store.get_messages(
        session_id, agent_type, limit=recent_n,
    )

    lines = [
        f"Session: {session.title}",
        f"目标: {session.goal}",
        f"状态: {session.status}",
        f"Agent: {agent_type}",
        f"最后活动: {session.last_activity_at}",
        "",
        f"最近 {len(messages)} 条消息：",
    ]
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")[:200]
        lines.append(f"  [{role}] {content}")

    return ToolResult(ok=True, output="\n".join(lines))

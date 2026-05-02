from __future__ import annotations

from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="inspect_session",
    description="查看指定 session 的最近消息和当前状态，用于判断下属任务进展。",
    permission_tier=PermissionTier.LOW,
    display_name="Inspect Session",
)
async def inspect_session(
    session_id: str,
    recent_n: int = 5,
) -> ToolResult:
    state = _get_state()

    all_sessions = await state.session_store.list_sessions()
    session_entry = next((s for s in all_sessions if s["id"] == session_id), None)
    if session_entry is None:
        return ToolResult(ok=False, error=f"Session {session_id} 未找到")

    agent_type = session_entry["agent_type"]
    session = await state.session_store.get_session(session_id, agent_type)
    if session is None:
        return ToolResult(ok=False, error=f"Session {session_id} 数据不存在")

    items = await state.session_store.get_recent_timeline_items(
        session_id,
        agent_type,
        limit=recent_n,
    )

    lines = [
        f"Session: {session.title}",
        f"目标: {session.goal}",
        f"状态: {session.status}",
        f"Agent: {agent_type}",
        f"最后活动: {session.last_activity_at}",
        "",
        f"最近 {len(items)} 条 timeline 记录：",
    ]
    for item in items:
        kind = item.get("kind", "?")
        role = item.get("role", "?")
        content = item.get("content", "")[:200]
        lines.append(f"  [{kind}/{role}] {content}")

    return ToolResult(ok=True, output="\n".join(lines))

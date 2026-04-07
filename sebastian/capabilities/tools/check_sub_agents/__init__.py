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
    name="check_sub_agents",
    description="查看下属 Agent 的任务执行状态摘要。",
)
async def check_sub_agents(
    _ctx: ToolCallContext | None = None,
) -> ToolResult:
    if _ctx is None:
        return ToolResult(ok=False, error="缺少调用上下文")

    state = _get_state()
    all_sessions = await state.index_store.list_all()

    if _ctx.depth == 1:
        # Sebastian: show all depth=2 sessions
        sessions = [s for s in all_sessions if s.get("depth") == 2]
    else:
        # Leader: show only this leader's own depth=3 children
        sessions = [
            s for s in all_sessions
            if s.get("depth") == 3
            and s.get("agent_type") == _ctx.agent_type
            and s.get("parent_session_id") == _ctx.session_id
        ]

    if not sessions:
        return ToolResult(ok=True, output="当前没有下属任务。")

    status_counts: dict[str, int] = {}
    lines: list[str] = []
    for s in sessions:
        status = s.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        goal = s.get("goal", s.get("title", "无标题"))
        last_active = s.get("last_activity_at", "未知")
        lines.append(
            f"- [{status}] {goal} "
            f"(id: {s['id']}, agent: {s.get('agent_type')}, 最后活动: {last_active})"
        )

    summary_parts = [f"{count} {status}" for status, count in status_counts.items()]
    summary = f"{len(sessions)} 个下属任务：{', '.join(summary_parts)}\n\n"
    return ToolResult(ok=True, output=summary + "\n".join(lines))

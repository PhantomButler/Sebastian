from __future__ import annotations

from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="check_sub_agents",
    description="查看下属 Agent 的任务执行状态摘要。",
    permission_tier=PermissionTier.LOW,
)
async def check_sub_agents() -> ToolResult:
    ctx = get_tool_context()
    if ctx is None:
        return ToolResult(
            ok=False,
            error=(
                "工具未从 agent 执行上下文中调用（内部 ToolCallContext 缺失）。"
                "这是运行时异常，请向上汇报'内部上下文缺失，无法执行 check_sub_agents'，"
                "不要重试此工具。"
            ),
        )

    state = _get_state()
    all_sessions = await state.session_store.list_sessions()

    if ctx.depth == 1:
        # Sebastian: show only depth=2 sessions spawned in this conversation session
        sessions = [
            s
            for s in all_sessions
            if s.get("depth") == 2 and s.get("parent_session_id") == ctx.session_id
        ]
    else:
        # Leader: show only this leader's own depth=3 children
        sessions = [
            s
            for s in all_sessions
            if s.get("depth") == 3
            and s.get("agent_type") == ctx.agent_type
            and s.get("parent_session_id") == ctx.session_id
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

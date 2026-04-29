from __future__ import annotations

import sys

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

_STATUS_LABELS = {"pending": "待完成", "in_progress": "进行中", "completed": "已完成"}


@tool(
    name="todo_read",
    description=(
        "Read the current session's todo list. Returns all todo items with their "
        "content, activeForm, and status. Use when you need to inspect current task "
        "progress without modifying it."
    ),
    permission_tier=PermissionTier.LOW,
)
async def todo_read() -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(
            ok=False,
            error=(
                "todo_read requires session context. Do not invent todo state; "
                "tell the user the current todo list is unavailable."
            ),
        )

    state = sys.modules.get("sebastian.gateway.state")
    if state is None:
        import sebastian.gateway.state as _state  # noqa: PLC0415

        state = _state

    try:
        items = await state.todo_store.read(ctx.agent_type, ctx.session_id)
    except Exception as exc:
        return ToolResult(
            ok=False,
            error=(
                f"Todo service is unavailable: {exc}. Do not retry automatically; "
                "tell the user the current todo list could not be read."
            ),
        )

    if not items:
        return ToolResult(
            ok=True,
            display="当前没有待办",
            output={"todos": [], "count": 0, "session_id": ctx.session_id},
        )

    lines = [
        f"• {item.content}（{_STATUS_LABELS.get(item.status.value, item.status.value)}）"
        for item in items
    ]
    display_text = "\n".join(lines)

    todos = [item.model_dump(mode="json", by_alias=True) for item in items]

    return ToolResult(
        ok=True,
        display=display_text,
        output={"todos": todos, "count": len(todos), "session_id": ctx.session_id},
    )

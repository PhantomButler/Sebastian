from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import TodoItem, ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.protocol.events.types import Event, EventType


def _parse_todos(raw: list[dict[str, Any]]) -> list[TodoItem]:
    items: list[TodoItem] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(
                f"todo item #{idx} must be an object with content, activeForm, and status fields"
            )
        try:
            items.append(TodoItem(**entry))
        except ValidationError as e:
            first_err = e.errors()[0]
            loc = ".".join(str(p) for p in first_err.get("loc", ())) or "status"
            raise ValueError(f"todo item #{idx} invalid {loc}: {first_err['msg']}") from e
    return items


@tool(
    name="todo_write",
    description=(
        "Create or update the current session's todo list. Coverage-write "
        "semantics: every call replaces the entire list. Use proactively for "
        "multi-step tasks (3+ steps). Each item needs {content, activeForm, "
        "status: pending|in_progress|completed}. Keep exactly one item "
        "in_progress at a time while working. No ids — position is identity. "
        "The current list is injected into context each turn, so you do not "
        "need a separate read tool."
    ),
    permission_tier=PermissionTier.LOW,
)
async def todo_write(todos: list[dict[str, Any]]) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(ok=False, error="todo_write requires session context")

    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except (json.JSONDecodeError, ValueError):
            return ToolResult(
                ok=False,
                error="todos must be an array of objects, not a JSON string",
            )
    if not isinstance(todos, list):
        return ToolResult(ok=False, error="todos must be an array of todo item objects")

    try:
        items = _parse_todos(todos)
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))

    import sys

    state = sys.modules.get("sebastian.gateway.state")
    if state is None:
        import sebastian.gateway.state as _state  # noqa: PLC0415

        state = _state

    old = await state.todo_store.read(ctx.agent_type, ctx.session_id)
    await state.todo_store.write(ctx.agent_type, ctx.session_id, items)

    await state.event_bus.publish(
        Event(
            type=EventType.TODO_UPDATED,
            data={
                "session_id": ctx.session_id,
                "agent_type": ctx.agent_type,
                "count": len(items),
            },
        )
    )

    _status_labels = {"pending": "待完成", "in_progress": "进行中", "completed": "已完成"}
    lines = [
        f"• {item.content}（{_status_labels.get(item.status.value, item.status.value)}）"
        for item in items
    ]
    display_text = f"写入 {len(items)} 个待办\n" + "\n".join(lines)

    return ToolResult(
        ok=True,
        display=display_text,
        output={
            "old_count": len(old),
            "new_count": len(items),
            "session_id": ctx.session_id,
        },
    )

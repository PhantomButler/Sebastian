"""Helper functions for ``BaseAgent._stream_inner`` tool dispatch.

Extracted to keep ``base_agent.py`` under 800 lines.  Nothing in this module
should hold mutable state — all logic is expressed as pure functions or async
functions that operate on explicit arguments.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging
from typing import Any

from sebastian.core.agent_loop import _tool_result_content
from sebastian.core.stream_events import ToolCallReady
from sebastian.core.stream_events import ToolResult as StreamToolResult
from sebastian.core.tool import get_tool
from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)


def _resolve_display_name(
    name: str,
    inputs: dict[str, Any],
    spec_display_name: str | None,
) -> str:
    """Compute the UI display name for a tool call.

    Handles three tools that need dynamic titles built from agent_type;
    all others use spec_display_name or fall back to the internal name.
    spawn_sub_agent is NOT in the match — its display name comes from @tool(display_name="Worker").
    """
    agent_type = inputs.get("agent_type", "") if isinstance(inputs, dict) else ""
    match name:
        case "delegate_to_agent":
            return f"Agent: {agent_type.capitalize()}" if agent_type else "Agent"
        case "stop_agent":
            return f"Stop Agent: {agent_type.capitalize()}" if agent_type else "Stop Agent"
        case "resume_agent":
            return f"Resume Agent: {agent_type.capitalize()}" if agent_type else "Resume Agent"
    return spec_display_name or name


_DISPLAY_MAX = 4000


def format_tool_display(result: ToolResult) -> str:
    """Convert a ToolResult into a human-readable ``result_summary`` string.

    Priority: ``result.display`` → ``result.empty_hint`` → ``str(result.output)``
    → empty string.  All paths are truncated to ``_DISPLAY_MAX`` characters.

    Note: the fallback uses ``str()`` (Python repr), not JSON — this is the UI
    display path only.  The LLM-facing path (``_tool_result_content``) is
    handled separately and must not be unified here.
    """
    if result.display is not None:
        text = result.display
    elif result.empty_hint is not None:
        text = result.empty_hint
    elif result.output is not None:
        text = str(result.output)
    else:
        text = ""
    if len(text) > _DISPLAY_MAX:
        return text[:_DISPLAY_MAX] + "…"
    return text


def _artifact_model_content(artifact: dict[str, Any], display: str) -> str:
    if display:
        return display
    filename = artifact.get("filename")
    label = "图片" if artifact.get("kind") == "image" else "文件"
    if isinstance(filename, str) and filename:
        return f"已向用户发送{label} {filename}"
    return f"已向用户发送{label}"


def _tool_result_model_content(result: StreamToolResult, display: str) -> str:
    if isinstance(result.output, dict):
        artifact = result.output.get("artifact")
        if isinstance(artifact, dict):
            return _artifact_model_content(artifact, display)
    return _tool_result_content(result)


def append_tool_result_block(
    blocks: list[dict[str, Any]],
    *,
    tool_id: str,
    tool_name: str,
    result: StreamToolResult,
    display: str,
    assistant_turn_id: str | None,
    provider_call_index: int | None,
    block_index: int,
) -> None:
    """Append a ``tool_result`` block dict to *blocks* in place."""
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_call_id": tool_id,
        "tool_name": tool_name,
        "model_content": _tool_result_model_content(result, display),
        "display": display,
        "ok": result.ok,
        "assistant_turn_id": assistant_turn_id,
        "provider_call_index": provider_call_index,
        "block_index": block_index,
    }
    if result.error is not None:
        block["error"] = result.error
    if isinstance(result.output, dict):
        artifact = result.output.get("artifact")
        if isinstance(artifact, dict):
            block["artifact"] = artifact
    blocks.append(block)


def ensure_tool_results_for_pending_calls(
    blocks: list[dict[str, Any]],
    *,
    reason: str,
) -> None:
    """Add synthetic failed tool_result blocks for persisted tool_calls without results."""
    result_ids = {
        block.get("tool_call_id")
        for block in blocks
        if block.get("type") == "tool_result" and block.get("tool_call_id")
    }
    block_indexes = [
        block_index
        for block in blocks
        if isinstance((block_index := block.get("block_index")), int)
    ]
    next_block_index = max(block_indexes, default=-1) + 1
    for block in list(blocks):
        if block.get("type") != "tool":
            continue
        tool_id = block.get("tool_call_id")
        if not tool_id or tool_id in result_ids:
            continue
        tool_name = block.get("tool_name", "")
        result = StreamToolResult(
            tool_id=tool_id,
            name=tool_name,
            ok=False,
            output=None,
            error=reason,
        )
        append_tool_result_block(
            blocks,
            tool_id=tool_id,
            tool_name=tool_name,
            result=result,
            display=reason,
            assistant_turn_id=block.get("assistant_turn_id") or block.get("turn_id"),
            provider_call_index=block.get("provider_call_index"),
            block_index=next_block_index,
        )
        next_block_index += 1
        result_ids.add(tool_id)


async def dispatch_tool_call(
    event: ToolCallReady,
    *,
    session_id: str,
    task_id: str | None,
    agent_context: str,
    assistant_turn_id: str,
    assistant_blocks: list[dict[str, Any]],
    current_pci: int,
    block_index: int,
    # Callables injected from BaseAgent to avoid circular imports
    gate_call: Any,
    update_activity: Any,
    publish: Any,
    current_task_goals: dict[str, str],
    current_depth: dict[str, int],
    allowed_tools: list[str] | None,
    pending_blocks: dict[str, list[dict[str, Any]]],
) -> tuple[StreamToolResult, int]:
    """Execute one ``ToolCallReady`` event and append result blocks.

    Returns ``(send_value, updated_block_index)`` for the agent loop.

    All mutable state is passed as explicit arguments so this function remains
    side-effect-free with respect to the ``BaseAgent`` instance.
    """
    from sebastian.protocol.events.types import EventType

    tool_entry = get_tool(event.name)
    spec_display_name = tool_entry[0].display_name if tool_entry else None
    display_name = _resolve_display_name(event.name, event.inputs, spec_display_name)

    await publish(
        session_id,
        EventType.TOOL_BLOCK_STOP,
        dataclasses.asdict(event),
    )
    await publish(
        session_id,
        EventType.TOOL_RUNNING,
        {"tool_id": event.tool_id, "name": event.name, "display_name": display_name, "input": event.inputs},
    )
    record: dict[str, Any] = {
        "type": "tool",
        "tool_call_id": event.tool_id,
        "tool_name": event.name,
        "display_name": display_name,
        "input": event.inputs,
        "status": "failed",
        "assistant_turn_id": assistant_turn_id,
        "provider_call_index": current_pci,
        "block_index": block_index,
    }
    assistant_blocks.append(record)
    block_index += 1
    pending_blocks[session_id] = assistant_blocks
    await update_activity(session_id, agent_context)

    from sebastian.permissions.types import ToolCallContext

    try:
        context = ToolCallContext(
            task_goal=current_task_goals.get(session_id, ""),
            session_id=session_id,
            task_id=task_id,
            agent_type=agent_context,
            depth=current_depth.get(session_id, 1),
            allowed_tools=(frozenset(allowed_tools) if allowed_tools is not None else None),
            progress_cb=functools.partial(publish, session_id, EventType.TOOL_RUNNING),
        )
        result = await gate_call(event.name, event.inputs, context)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - exercised via async failure paths
        logger.exception("Tool %s dispatch failed", event.name)
        error = str(exc)
        record["result"] = error
        stream_result = StreamToolResult(
            tool_id=event.tool_id, name=event.name, ok=False, output=None, error=error
        )
        append_tool_result_block(
            assistant_blocks,
            tool_id=event.tool_id,
            tool_name=event.name,
            result=stream_result,
            display=error,
            assistant_turn_id=assistant_turn_id,
            provider_call_index=current_pci,
            block_index=block_index,
        )
        block_index += 1
        pending_blocks[session_id] = assistant_blocks
        await publish(
            session_id,
            EventType.TOOL_FAILED,
            {"tool_id": event.tool_id, "name": event.name, "display_name": display_name, "error": error},
        )
        return stream_result, block_index

    if result.ok:
        display = format_tool_display(result)
        record["status"] = "done"
        record["result"] = display
        event_data: dict[str, Any] = {
            "tool_id": event.tool_id,
            "name": event.name,
            "display_name": display_name,
            "result_summary": display,
        }
        if isinstance(result.output, dict):
            artifact = result.output.get("artifact")
            if isinstance(artifact, dict):
                event_data["artifact"] = artifact
        await publish(
            session_id,
            EventType.TOOL_EXECUTED,
            event_data,
        )
    else:
        record["result"] = result.error or ""
        await publish(
            session_id,
            EventType.TOOL_FAILED,
            {"tool_id": event.tool_id, "name": event.name, "display_name": display_name, "error": result.error},
        )
    stream_result = StreamToolResult(
        tool_id=event.tool_id,
        name=event.name,
        ok=result.ok,
        output=result.output,
        error=result.error,
        empty_hint=result.empty_hint,
    )
    display_content = display if result.ok else (result.error or "")
    append_tool_result_block(
        assistant_blocks,
        tool_id=event.tool_id,
        tool_name=event.name,
        result=stream_result,
        display=display_content,
        assistant_turn_id=assistant_turn_id,
        provider_call_index=current_pci,
        block_index=block_index,
    )
    block_index += 1
    pending_blocks[session_id] = assistant_blocks
    return stream_result, block_index

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import ToolCallReady
from sebastian.core.stream_events import ToolResult as StreamToolResult

# ---------------------------------------------------------------------------
# append_tool_result_block
# ---------------------------------------------------------------------------


def _make_stream_result(
    output: object, ok: bool = True, error: str | None = None
) -> StreamToolResult:
    return StreamToolResult(
        tool_id="toolu_1",
        name="send_file",
        ok=ok,
        output=output,
        error=error,
    )


def test_append_tool_result_block_preserves_artifact() -> None:
    from sebastian.core.stream_helpers import append_tool_result_block

    artifact = {
        "kind": "text_file",
        "attachment_id": "att-1",
        "filename": "notes.md",
        "download_url": "/api/v1/attachments/att-1",
        "text_excerpt": "# private excerpt",
    }
    result = _make_stream_result(output={"artifact": artifact})
    blocks: list = []
    append_tool_result_block(
        blocks,
        tool_id="toolu_1",
        tool_name="send_file",
        result=result,
        display="已向用户发送文件 notes.md",
        assistant_turn_id="turn-1",
        provider_call_index=0,
        block_index=0,
    )
    assert len(blocks) == 1
    assert blocks[0]["artifact"]["attachment_id"] == "att-1"
    assert blocks[0]["artifact"]["kind"] == "text_file"
    assert blocks[0]["artifact"]["filename"] == "notes.md"
    assert blocks[0]["model_content"] == "已向用户发送文件 notes.md"
    assert "attachment_id" not in blocks[0]["model_content"]
    assert "download_url" not in blocks[0]["model_content"]
    assert "private excerpt" not in blocks[0]["model_content"]


def test_append_tool_result_block_artifact_fallback_model_content() -> None:
    from sebastian.core.stream_helpers import append_tool_result_block

    cases = [
        ({"kind": "image", "filename": "photo.png"}, "已向用户发送图片 photo.png"),
        ({"kind": "text_file", "filename": "notes.md"}, "已向用户发送文件 notes.md"),
        ({"kind": "unknown", "filename": "data.bin"}, "已向用户发送文件 data.bin"),
    ]
    for artifact, expected in cases:
        result = _make_stream_result(output={"artifact": artifact})
        blocks: list = []
        append_tool_result_block(
            blocks,
            tool_id="toolu_1",
            tool_name="send_file",
            result=result,
            display="",
            assistant_turn_id="turn-1",
            provider_call_index=0,
            block_index=0,
        )
        assert blocks[0]["model_content"] == expected


def test_append_tool_result_block_no_artifact() -> None:
    from sebastian.core.stream_helpers import append_tool_result_block

    result = _make_stream_result(output={"count": 1})
    blocks: list = []
    append_tool_result_block(
        blocks,
        tool_id="toolu_1",
        tool_name="list_files",
        result=result,
        display="1 file",
        assistant_turn_id="turn-1",
        provider_call_index=0,
        block_index=0,
    )
    assert len(blocks) == 1
    assert "artifact" not in blocks[0]


def test_append_tool_result_block_output_is_not_dict_no_artifact() -> None:
    from sebastian.core.stream_helpers import append_tool_result_block

    result = _make_stream_result(output="plain string output")
    blocks: list = []
    append_tool_result_block(
        blocks,
        tool_id="toolu_1",
        tool_name="echo",
        result=result,
        display="plain string output",
        assistant_turn_id="turn-1",
        provider_call_index=0,
        block_index=0,
    )
    assert "artifact" not in blocks[0]


def test_append_tool_result_block_artifact_not_dict_not_forwarded() -> None:
    """If output["artifact"] is not a dict it must not be forwarded."""
    from sebastian.core.stream_helpers import append_tool_result_block

    result = _make_stream_result(output={"artifact": "not-a-dict"})
    blocks: list = []
    append_tool_result_block(
        blocks,
        tool_id="toolu_1",
        tool_name="send_file",
        result=result,
        display="done",
        assistant_turn_id="turn-1",
        provider_call_index=0,
        block_index=0,
    )
    assert "artifact" not in blocks[0]


# ---------------------------------------------------------------------------
# dispatch_tool_call — artifact in TOOL_EXECUTED event
# ---------------------------------------------------------------------------


def _make_event() -> ToolCallReady:
    return ToolCallReady(
        block_id="blk_0",
        tool_id="toolu_1",
        name="send_file",
        inputs={"attachment_id": "att-1"},
    )


@pytest.mark.asyncio
async def test_dispatch_tool_call_publishes_artifact_on_tool_executed() -> None:
    from sebastian.core.stream_helpers import dispatch_tool_call
    from sebastian.protocol.events.types import EventType

    artifact = {"kind": "image", "attachment_id": "att-1", "filename": "photo.png"}

    gate_call = AsyncMock(
        return_value=MagicMock(
            ok=True,
            output={"artifact": artifact},
            error=None,
            empty_hint=None,
            display=None,
        )
    )
    update_activity = AsyncMock()
    published: list[tuple] = []

    async def publish(session_id: str, event_type: EventType, data: object) -> None:
        published.append((session_id, event_type, data))

    blocks: list = []
    await dispatch_tool_call(
        _make_event(),
        session_id="sess-1",
        task_id=None,
        agent_context="sebastian",
        assistant_turn_id="turn-1",
        assistant_blocks=blocks,
        current_pci=0,
        block_index=1,
        gate_call=gate_call,
        update_activity=update_activity,
        publish=publish,
        current_task_goals={},
        current_depth={},
        allowed_tools=None,
        pending_blocks={},
    )

    executed_events = [
        (sid, et, data) for (sid, et, data) in published if et == EventType.TOOL_EXECUTED
    ]
    assert len(executed_events) == 1
    _, _, data = executed_events[0]
    assert data["artifact"]["attachment_id"] == "att-1"


@pytest.mark.asyncio
async def test_dispatch_tool_call_failed_result_publishes_tool_failed_without_artifact() -> None:
    from sebastian.core.stream_helpers import dispatch_tool_call
    from sebastian.protocol.events.types import EventType

    gate_call = AsyncMock(
        return_value=MagicMock(
            ok=False,
            output=None,
            error="File not found. Do not retry.",
            empty_hint=None,
            display=None,
        )
    )
    update_activity = AsyncMock()
    published: list[tuple] = []

    async def publish(session_id: str, event_type: EventType, data: object) -> None:
        published.append((session_id, event_type, data))

    blocks: list = []
    await dispatch_tool_call(
        _make_event(),
        session_id="sess-1",
        task_id=None,
        agent_context="sebastian",
        assistant_turn_id="turn-1",
        assistant_blocks=blocks,
        current_pci=0,
        block_index=1,
        gate_call=gate_call,
        update_activity=update_activity,
        publish=publish,
        current_task_goals={},
        current_depth={},
        allowed_tools=None,
        pending_blocks={},
    )

    event_types = [et for (_, et, _) in published]
    assert EventType.TOOL_FAILED in event_types
    assert EventType.TOOL_EXECUTED not in event_types

    # No artifact in any event
    for _, _, data in published:
        assert "artifact" not in data

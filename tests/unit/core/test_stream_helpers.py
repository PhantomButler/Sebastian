from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


def test_append_tool_result_block_preserves_download_artifact_unchanged() -> None:
    from sebastian.core.stream_helpers import append_tool_result_block

    artifact = {
        "kind": "download",
        "attachment_id": "att-download",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1234,
        "download_url": "/api/v1/attachments/att-download",
    }
    result = _make_stream_result(output={"artifact": artifact})
    blocks: list = []
    append_tool_result_block(
        blocks,
        tool_id="toolu_1",
        tool_name="browser_download",
        result=result,
        display="",
        assistant_turn_id="turn-1",
        provider_call_index=0,
        block_index=0,
    )

    assert blocks[0]["artifact"] == artifact
    assert blocks[0]["model_content"] == "已向用户发送文件 report.pdf"


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

    mock_spec = MagicMock()
    mock_spec.display_name = "Send File"

    blocks: list = []
    with patch("sebastian.core.stream_helpers.get_tool", return_value=(mock_spec, MagicMock())):
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
    assert data["display_name"] == "Send File"  # display_name wired from spec through to event

    running_events = [(sid, et, d) for (sid, et, d) in published if et == EventType.TOOL_RUNNING]
    assert len(running_events) == 1
    _, _, running_data = running_events[0]
    assert running_data["display_name"] == "Send File"


@pytest.mark.asyncio
async def test_dispatch_tool_call_publishes_download_artifact_unchanged() -> None:
    from sebastian.core.stream_helpers import dispatch_tool_call
    from sebastian.protocol.events.types import EventType

    artifact = {
        "kind": "download",
        "attachment_id": "att-download",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1234,
        "download_url": "/api/v1/attachments/att-download",
    }

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

    mock_spec = MagicMock()
    mock_spec.display_name = "Browser Download"

    blocks: list = []
    with patch("sebastian.core.stream_helpers.get_tool", return_value=(mock_spec, MagicMock())):
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

    executed = [data for _, event_type, data in published if event_type == EventType.TOOL_EXECUTED]
    assert len(executed) == 1
    assert executed[0]["artifact"] == artifact
    tool_results = [block for block in blocks if block["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["artifact"] == artifact


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

    mock_spec = MagicMock()
    mock_spec.display_name = "Send File"

    blocks: list = []
    with patch("sebastian.core.stream_helpers.get_tool", return_value=(mock_spec, MagicMock())):
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

    failed_events = [(sid, et, d) for (sid, et, d) in published if et == EventType.TOOL_FAILED]
    assert len(failed_events) == 1
    _, _, failed_data = failed_events[0]
    # display_name wired from spec through to event
    assert failed_data["display_name"] == "Send File"


# ---------------------------------------------------------------------------
# _resolve_display_name
# ---------------------------------------------------------------------------


def test_resolve_display_name_delegate_with_agent_type() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("delegate_to_agent", {"agent_type": "forge"}, None)
    assert result == "Agent: Forge"


def test_resolve_display_name_delegate_without_agent_type() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("delegate_to_agent", {}, None)
    assert result == "Agent"


def test_resolve_display_name_stop_agent() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("stop_agent", {"agent_type": "forge"}, None)
    assert result == "Stop Agent: Forge"


def test_resolve_display_name_resume_agent() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("resume_agent", {"agent_type": "builder"}, None)
    assert result == "Resume Agent: Builder"


def test_resolve_display_name_spec_display_name_for_spawn_sub_agent() -> None:
    """spawn_sub_agent has no match case — its display name comes from spec_display_name."""
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("spawn_sub_agent", {"goal": "do stuff"}, "Worker")
    assert result == "Worker"


def test_resolve_display_name_uses_spec_display_name() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("memory_save", {}, "Save Memory")
    assert result == "Save Memory"


def test_resolve_display_name_falls_back_to_name() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("some_tool", {}, None)
    assert result == "some_tool"


def test_resolve_display_name_non_dict_inputs() -> None:
    from sebastian.core.stream_helpers import _resolve_display_name

    result = _resolve_display_name("delegate_to_agent", "not-a-dict", None)
    assert result == "Agent"

# Agent File Send and Todo Read Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `todo_read` and `send_file`, with agent-sent images/files shown as assistant attachment blocks in realtime and after timeline hydration.

**Architecture:** `todo_read` mirrors `todo_write` as a LOW-risk read-only session tool. `send_file` copies supported local image/text files into `AttachmentStore`, returns a structured `artifact`, persists that artifact on the existing `tool_result`, and sends it over `tool.executed` so Android can replace the transient tool card with an attachment block without refreshing the full message list.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest, Kotlin, Jetpack Compose, Moshi/JSONObject SSE parsing, JUnit4.

---

## Spec And Context

- Spec: `docs/superpowers/specs/2026-04-28-agent-file-send-and-todo-read-design.md`
- Backend tool guide: `sebastian/capabilities/tools/README.md`
- Android guide: `ui/mobile-android/README.md`
- Android chat guide: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`

Before editing Python code, use JetBrains PyCharm MCP for symbol/text lookups. Android Studio MCP is not exposed in the current session; this is a “当前 agent 无工具暴露” fallback case, so use PyCharm MCP for Android file text/index lookups.

After code changes, run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

## File Structure

Backend:

- Create `sebastian/capabilities/tools/todo_read/__init__.py`
  - Defines `todo_read()` and checklist display formatting.
- Create `sebastian/capabilities/tools/send_file/__init__.py`
  - Resolves file path, classifies supported file type, uploads bytes through `AttachmentStore`, marks attachment as agent-sent, returns artifact.
- Modify `sebastian/store/attachments.py`
  - Add `mark_agent_sent()` for `uploaded -> attached` session binding.
- Modify `sebastian/core/stream_helpers.py`
  - Copy `ToolResult.output["artifact"]` into the persisted/streamed tool result block.
  - Include optional `artifact` in `tool.executed` SSE data.
- Modify `sebastian/store/session_timeline.py`
  - Preserve `artifact` in `tool_result.payload`.
- Modify `sebastian/orchestrator/sebas.py`
  - Add `todo_read` and `send_file` to Sebastian allowed tools.
- Modify `sebastian/agents/forge/manifest.toml`
  - Add `todo_read` and `send_file` to Forge allowed tools.
- Modify `sebastian/agents/aide/manifest.toml`
  - Add `todo_read` and `send_file` to Aide allowed tools.
- Modify `sebastian/agents/README.md` and agent README files if their tool lists are documented.
- Modify docs:
  - `sebastian/capabilities/tools/README.md`
  - `sebastian/capabilities/README.md`

Backend tests:

- Create `tests/unit/capabilities/test_todo_read_tool.py`
- Create `tests/unit/capabilities/test_send_file_tool.py`
- Modify or create focused stream/timeline tests in:
  - `tests/unit/core/test_base_agent_provider.py` or a new `tests/unit/core/test_stream_helpers.py`
  - `tests/unit/store/test_session_context.py` or a new `tests/unit/store/test_session_timeline_artifacts.py`
- Add an integration/API assertion in `tests/integration/test_gateway_attachments.py`

Android:

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
  - Add `AttachmentArtifact` model and optional `artifact` on `ToolExecuted`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`
  - Parse optional `artifact` object from `tool.executed`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt`
  - Add helper for nested payload maps if needed.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
  - Convert successful `send_file` artifacts into assistant `ImageBlock` / `FileBlock`.
  - Suppress the corresponding `send_file` `ToolBlock` on success.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
  - Replace the active `send_file` `ToolBlock` with an attachment block on realtime `ToolExecuted`.
  - Append with `attachment_id` de-dupe if the `ToolBlock` is absent but the current assistant message exists.
- Modify docs:
  - `ui/mobile-android/README.md`
  - `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`

Android tests:

- Modify `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`
- Modify `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`
- Add or modify parser tests if a focused `SseFrameDto` test exists; otherwise add coverage near existing SSE tests.

---

### Task 1: Backend `todo_read` Tool

**Files:**
- Create: `sebastian/capabilities/tools/todo_read/__init__.py`
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/agents/forge/manifest.toml`
- Modify: `sebastian/agents/aide/manifest.toml`
- Test: `tests/unit/capabilities/test_todo_read_tool.py`
- Later docs in Task 6

- [ ] **Step 1: Write failing tests for `todo_read`**

Create `tests/unit/capabilities/test_todo_read_tool.py` using the same patched-state pattern as `tests/unit/capabilities/test_todo_write_tool.py`.

Test cases:

```python
@pytest.mark.asyncio
async def test_todo_read_returns_current_todos(patched_state, set_ctx) -> None:
    _, store = patched_state
    set_ctx("s1", "sebastian")
    await store.write(
        "sebastian",
        "s1",
        [
            TodoItem(content="plan", activeForm="planning", status=TodoStatus.IN_PROGRESS),
            TodoItem(content="test", activeForm="testing", status=TodoStatus.PENDING),
        ],
    )

    from sebastian.capabilities.tools.todo_read import todo_read

    result = await todo_read()

    assert result.ok is True
    assert result.output["count"] == 2
    assert result.output["todos"][0]["content"] == "plan"
    assert result.output["todos"][0]["activeForm"] == "planning"
    assert result.output["todos"][0]["status"] == "in_progress"
    assert "plan" in result.display
```

Also test empty todos and missing context:

```python
assert result.output["todos"] == []
assert "没有待办" in result.display

assert result.ok is False
assert "context" in result.error.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/unit/capabilities/test_todo_read_tool.py -v
```

Expected: FAIL with import error for `sebastian.capabilities.tools.todo_read`.

- [ ] **Step 3: Implement `todo_read`**

Create `sebastian/capabilities/tools/todo_read/__init__.py`:

```python
from __future__ import annotations

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


@tool(
    name="todo_read",
    description=(
        "Read the current session's todo list. Use when you need to inspect "
        "current task progress before deciding the next step. Returns the "
        "complete list with content, activeForm, and status."
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

    import sys

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

    todos = [item.model_dump(mode="json", by_alias=True) for item in items]
    if not todos:
        display = "当前没有待办"
    else:
        labels = {"pending": "待完成", "in_progress": "进行中", "completed": "已完成"}
        display = "\n".join(
            f"• {item.content}（{labels.get(item.status.value, item.status.value)}）"
            for item in items
        )

    return ToolResult(
        ok=True,
        output={
            "todos": todos,
            "count": len(todos),
            "session_id": ctx.session_id,
        },
        display=display,
    )
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/unit/capabilities/test_todo_read_tool.py -v
```

Expected: PASS.

- [ ] **Step 5: Add tool to Sebastian allowed tools**

Modify `sebastian/orchestrator/sebas.py`:

```python
allowed_tools = [
    ...
    "todo_write",
    "todo_read",
    ...
]
```

Also add `todo_read` to explicit sub-agent manifests:

- `sebastian/agents/forge/manifest.toml`
- `sebastian/agents/aide/manifest.toml`

Keep the existing six core file/shell tools and append `todo_read`. These manifests have explicit `allowed_tools`, so not adding the tool here would make it unavailable to sub-agents.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/unit/capabilities/test_todo_read_tool.py tests/unit/capabilities/test_todo_write_tool.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add sebastian/capabilities/tools/todo_read/__init__.py tests/unit/capabilities/test_todo_read_tool.py sebastian/orchestrator/sebas.py sebastian/agents/forge/manifest.toml sebastian/agents/aide/manifest.toml
git commit -m "feat(tools): 新增 todo_read 工具" -m "Co-Authored-By: gpt-5 <noreply@openai.com>"
```

---

### Task 2: Backend `send_file` Tool And Attachment Binding

**Files:**
- Create: `sebastian/capabilities/tools/send_file/__init__.py`
- Modify: `sebastian/store/attachments.py`
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/agents/forge/manifest.toml`
- Modify: `sebastian/agents/aide/manifest.toml`
- Test: `tests/unit/capabilities/test_send_file_tool.py`

- [ ] **Step 1: Write failing tests for AttachmentStore agent binding**

In `tests/unit/capabilities/test_send_file_tool.py`, create SQLite fixture like `test_todo_write_tool.py`.

Test `mark_agent_sent()`:

```python
@pytest.mark.asyncio
async def test_mark_agent_sent_binds_uploaded_attachment(db_factory, tmp_path) -> None:
    store = AttachmentStore(tmp_path / "attachments", db_factory)
    uploaded = await store.upload_bytes(
        filename="notes.md",
        content_type="text/markdown",
        kind="text_file",
        data=b"# hello",
    )

    await store.mark_agent_sent(uploaded.id, "sebastian", "s1")
    record = await store.get(uploaded.id)

    assert record.status == "attached"
    assert record.agent_type == "sebastian"
    assert record.session_id == "s1"
    assert record.attached_at is not None
```

Also test conflict:

```python
with pytest.raises(AttachmentConflictError):
    await store.mark_agent_sent(uploaded.id, "sebastian", "s2")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py::test_mark_agent_sent_binds_uploaded_attachment -v
```

Expected: FAIL with missing `mark_agent_sent`.

- [ ] **Step 3: Implement `AttachmentStore.mark_agent_sent()`**

Modify `sebastian/store/attachments.py`:

```python
async def mark_agent_sent(
    self,
    attachment_id: str,
    agent_type: str,
    session_id: str,
) -> AttachmentRecord:
    now = datetime.now(UTC)
    async with self._db_factory() as session:
        record = await session.get(AttachmentRecord, attachment_id)
        if record is None:
            raise AttachmentNotFoundError(f"Attachment not found: {attachment_id}")
        if record.status != "uploaded" or record.session_id is not None:
            raise AttachmentConflictError(
                f"Attachment {attachment_id!r} is not available for agent send"
            )
        record.status = "attached"
        record.agent_type = agent_type
        record.session_id = session_id
        record.attached_at = now
        await session.commit()
        await session.refresh(record)
        return record
```

- [ ] **Step 4: Run binding tests**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py -v
```

Expected: mark-agent-sent tests PASS; send_file tests still not present or failing if already written.

- [ ] **Step 5: Write failing tests for `send_file`**

Add tests:

```python
@pytest.mark.asyncio
async def test_send_file_uploads_text_file_and_returns_artifact(patched_state, set_ctx, tmp_path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# hello", encoding="utf-8")
    set_ctx("s1", "sebastian")

    from sebastian.capabilities.tools.send_file import send_file

    result = await send_file(str(file_path))

    assert result.ok is True
    artifact = result.output["artifact"]
    assert artifact["kind"] == "text_file"
    assert artifact["filename"] == "notes.md"
    assert artifact["download_url"].startswith("/api/v1/attachments/")
    assert artifact["text_excerpt"] == "# hello"
    assert "已向用户发送文件 notes.md" == result.display
```

Add image test with minimal JPEG bytes and `display_name`.

Add deterministic failure tests:

```python
result = await send_file(str(file_path))  # with no ToolCallContext set
assert result.ok is False
assert "session context" in result.error

result = await send_file(str(tmp_path / "missing.md"))
assert result.ok is False
assert "Do not retry automatically" in result.error

result = await send_file(str(tmp_path))
assert result.ok is False
assert "directory" in result.error.lower()

bad = tmp_path / "archive.zip"
bad.write_bytes(b"zip")
result = await send_file(str(bad))
assert result.ok is False
assert "Unsupported file type" in result.error
```

Add attachment-store-unavailable and size tests:

```python
fake_state.attachment_store = None
result = await send_file(str(file_path))
assert result.ok is False
assert "Attachment service is unavailable" in result.error

too_large = tmp_path / "big.txt"
too_large.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
result = await send_file(str(too_large))
assert result.ok is False
assert "too large" in result.error.lower() or "exceeds" in result.error.lower()
```

For successful send, directly assert the uploaded attachment is bound:

```python
record = await fake_state.attachment_store.get(artifact["attachment_id"])
assert record.status == "attached"
assert record.agent_type == "sebastian"
assert record.session_id == "s1"
```

- [ ] **Step 6: Run tests to verify failures**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py -v
```

Expected: FAIL with missing `send_file`.

- [ ] **Step 7: Implement `send_file`**

Create `sebastian/capabilities/tools/send_file/__init__.py`.

Implementation outline:

```python
from __future__ import annotations

import mimetypes
from pathlib import Path

from sebastian.capabilities.tools._path_utils import resolve_path
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.store.attachments import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_TYPES,
    ALLOWED_TEXT_EXTENSIONS,
    ALLOWED_TEXT_MIME_TYPES,
    AttachmentValidationError,
)


def _error(message: str) -> ToolResult:
    return ToolResult(ok=False, error=f"{message} Do not retry automatically; tell the user or ask for new input.")


def _classify(source_path: Path, mime_type: str) -> str | None:
    suffix = source_path.suffix.lower()
    if suffix in ALLOWED_IMAGE_EXTENSIONS and mime_type in ALLOWED_IMAGE_MIME_TYPES:
        return "image"
    if suffix in ALLOWED_TEXT_EXTENSIONS and mime_type in ALLOWED_TEXT_MIME_TYPES:
        return "text_file"
    return None


def _upload_filename(source_path: Path, display_name: str | None) -> str:
    if not display_name:
        return source_path.name
    candidate = Path(display_name)
    if candidate.suffix:
        return candidate.name
    return f"{candidate.name}{source_path.suffix}"


@tool(
    name="send_file",
    description=(
        "Send a local image or supported text file to the user as a chat attachment. "
        "Use only when you have an existing file path to share. If it fails, do not "
        "retry the same path automatically; tell the user the reason."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def send_file(file_path: str, display_name: str | None = None) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(
            ok=False,
            error=(
                "send_file requires session context. Do not retry automatically; "
                "tell the user the file could not be sent in this conversation."
            ),
        )

    path = resolve_path(file_path)
    if not path.exists():
        return _error(f"File not found: {file_path}.")
    if path.is_dir():
        return _error(f"Path is a directory, not a file: {file_path}.")

    filename = _upload_filename(path, display_name)
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    kind = _classify(path, mime_type)
    if kind is None:
        return _error(f"Unsupported file type: {path.suffix.lower()!r}.")

    import sebastian.gateway.state as state

    if state.attachment_store is None:
        return ToolResult(
            ok=False,
            error=(
                "Attachment service is unavailable. Do not retry automatically; "
                "tell the user sending files is currently unavailable."
            ),
        )

    data = path.read_bytes()
    try:
        uploaded = await state.attachment_store.upload_bytes(
            filename=filename,
            content_type=mime_type,
            kind=kind,
            data=data,
        )
        await state.attachment_store.mark_agent_sent(
            uploaded.id, ctx.agent_type, ctx.session_id
        )
    except AttachmentValidationError as exc:
        return ToolResult(
            ok=False,
            error=f"{exc}. Do not retry automatically; tell the user the file could not be sent.",
        )

    artifact = {
        "kind": uploaded.kind,
        "attachment_id": uploaded.id,
        "filename": uploaded.filename,
        "mime_type": uploaded.mime_type,
        "size_bytes": uploaded.size_bytes,
        "download_url": f"/api/v1/attachments/{uploaded.id}",
    }
    if uploaded.kind == "image":
        artifact["thumbnail_url"] = f"/api/v1/attachments/{uploaded.id}/thumbnail"
        display = f"已向用户发送图片 {uploaded.filename}"
    else:
        artifact["text_excerpt"] = uploaded.text_excerpt
        display = f"已向用户发送文件 {uploaded.filename}"

    return ToolResult(ok=True, output={"artifact": artifact}, display=display)
```

Adjust exact allowed extensions/MIME by importing or reusing constants from `AttachmentStore` if preferable. Keep logic aligned with `upload_bytes()` to avoid divergence.

- [ ] **Step 8: Add tool to allowed tool lists**

Modify `sebastian/orchestrator/sebas.py`:

```python
allowed_tools = [
    ...
    "send_file",
    ...
]
```

Also add `send_file` to explicit sub-agent manifests:

- `sebastian/agents/forge/manifest.toml`
- `sebastian/agents/aide/manifest.toml`

- [ ] **Step 9: Run focused backend tests**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit Task 2**

```bash
git add sebastian/store/attachments.py sebastian/capabilities/tools/send_file/__init__.py tests/unit/capabilities/test_send_file_tool.py sebastian/orchestrator/sebas.py sebastian/agents/forge/manifest.toml sebastian/agents/aide/manifest.toml
git commit -m "feat(tools): 新增 send_file 工具" -m "Co-Authored-By: gpt-5 <noreply@openai.com>"
```

---

### Task 3: Persist And Stream Tool Artifacts

**Files:**
- Modify: `sebastian/core/stream_helpers.py`
- Modify: `sebastian/store/session_timeline.py`
- Test: `tests/unit/core/test_stream_helpers.py` or existing core tests
- Test: `tests/unit/store/test_session_context.py` or new timeline test
- Test: `tests/integration/test_gateway_attachments.py`

- [ ] **Step 1: Write failing unit test for `append_tool_result_block()` artifact copy**

Create `tests/unit/core/test_stream_helpers.py` if no suitable file exists:

```python
from sebastian.core.stream_events import ToolResult as StreamToolResult
from sebastian.core.stream_helpers import append_tool_result_block


def test_append_tool_result_block_preserves_artifact() -> None:
    blocks = []
    result = StreamToolResult(
        tool_id="toolu_1",
        name="send_file",
        ok=True,
        output={
            "artifact": {
                "kind": "image",
                "attachment_id": "att-1",
                "filename": "photo.png",
            }
        },
    )

    append_tool_result_block(
        blocks,
        tool_id="toolu_1",
        tool_name="send_file",
        result=result,
        display="已向用户发送图片 photo.png",
        assistant_turn_id="turn-1",
        provider_call_index=0,
        block_index=1,
    )

    assert blocks[0]["artifact"]["attachment_id"] == "att-1"
```

If this file also tests `dispatch_tool_call()`, import both ToolResult types explicitly:

```python
from sebastian.core.stream_events import ToolCallReady
from sebastian.core.stream_events import ToolResult as StreamToolResult
from sebastian.core.types import ToolResult
```

Use `StreamToolResult` only for direct `append_tool_result_block()` tests. Use `sebastian.core.types.ToolResult` for mocked `gate_call()` returns.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/core/test_stream_helpers.py -v
```

Expected: FAIL because block lacks `artifact`.

- [ ] **Step 3: Implement artifact copy and SSE event payload**

Modify `sebastian/core/stream_helpers.py`.

In `append_tool_result_block()`:

```python
if isinstance(result.output, dict) and isinstance(result.output.get("artifact"), dict):
    block["artifact"] = result.output["artifact"]
```

In `dispatch_tool_call()`, before publishing `EventType.TOOL_EXECUTED`:

```python
event_data = {"tool_id": event.tool_id, "name": event.name, "result_summary": display}
if isinstance(result.output, dict) and isinstance(result.output.get("artifact"), dict):
    event_data["artifact"] = result.output["artifact"]
await publish(session_id, EventType.TOOL_EXECUTED, event_data)
```

- [ ] **Step 4: Run stream helper tests**

Run:

```bash
pytest tests/unit/core/test_stream_helpers.py tests/unit/core/test_base_agent_provider.py -v
```

Expected: PASS.

- [ ] **Step 5: Write failing backend test for realtime SSE artifact payload**

Add a focused test in `tests/unit/core/test_stream_helpers.py` for `dispatch_tool_call()`:

```python
@pytest.mark.asyncio
async def test_dispatch_tool_call_publishes_artifact_on_tool_executed() -> None:
    published: list[tuple[EventType, dict[str, Any]]] = []

    async def publish(_session_id: str, event_type: EventType, data: dict[str, Any]) -> None:
        published.append((event_type, data))

    async def gate_call(_name: str, _inputs: dict[str, Any], _context: ToolCallContext) -> ToolResult:
        return ToolResult(
            ok=True,
            output={
                "artifact": {
                    "kind": "image",
                    "attachment_id": "att-1",
                    "filename": "photo.png",
                }
            },
            display="已向用户发送图片 photo.png",
        )

    await dispatch_tool_call(
        ToolCallReady(block_id="block-0", tool_id="toolu_1", name="send_file", inputs={}),
        session_id="s1",
        task_id=None,
        agent_context="sebastian",
        assistant_turn_id="turn-1",
        assistant_blocks=[],
        current_pci=0,
        block_index=0,
        gate_call=gate_call,
        update_activity=AsyncMock(),
        publish=publish,
        current_task_goals={},
        current_depth={},
        allowed_tools=None,
        pending_blocks={},
    )

    executed = [data for event_type, data in published if event_type == EventType.TOOL_EXECUTED]
    assert executed
    assert executed[0]["artifact"]["attachment_id"] == "att-1"
```

Also add a failure contract test:

```python
@pytest.mark.asyncio
async def test_dispatch_tool_call_failed_result_publishes_tool_failed_without_artifact() -> None:
    ...
    async def gate_call(...):
        return ToolResult(ok=False, error="File not found. Do not retry automatically; ask the user.")
    ...
    assert any(event_type == EventType.TOOL_FAILED for event_type, _ in published)
    assert not any(event_type == EventType.TOOL_EXECUTED for event_type, _ in published)
```

- [ ] **Step 6: Run tests to verify SSE artifact failure before implementation**

Run:

```bash
pytest tests/unit/core/test_stream_helpers.py -v
```

Expected: FAIL until `dispatch_tool_call()` includes artifact in `tool.executed`.

- [ ] **Step 7: Write failing timeline payload persistence test**

Add a test around `SessionTimeline.append_message_compat()` or `SessionStore.append_message()`:

```python
@pytest.mark.asyncio
async def test_tool_result_artifact_persisted_in_timeline_payload(store, session_in_db):
    blocks = [
        {
            "type": "tool",
            "tool_call_id": "toolu_1",
            "tool_name": "send_file",
            "input": {"file_path": "photo.png"},
            "assistant_turn_id": "turn-1",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "type": "tool_result",
            "tool_call_id": "toolu_1",
            "tool_name": "send_file",
            "model_content": "已向用户发送图片 photo.png",
            "display": "已向用户发送图片 photo.png",
            "ok": True,
            "artifact": {
                "kind": "image",
                "attachment_id": "att-1",
                "filename": "photo.png",
            },
            "assistant_turn_id": "turn-1",
            "provider_call_index": 0,
            "block_index": 1,
        },
    ]

    await store.append_message(session_in_db.id, "assistant", "", agent_type="sebastian", blocks=blocks)
    items = await store.get_timeline_items(session_in_db.id, "sebastian")
    result = next(i for i in items if i["kind"] == "tool_result")

    assert result["payload"]["artifact"]["attachment_id"] == "att-1"
```

- [ ] **Step 8: Run test to verify it fails if artifact is stripped**

Run:

```bash
pytest tests/unit/store/test_session_context.py::test_tool_result_artifact_persisted_in_timeline_payload -v
```

Expected: FAIL before preservation if `_normalize_block_payload()` drops or does not receive artifact.

- [ ] **Step 9: Ensure `session_timeline._normalize_block_payload()` preserves artifact**

Current payload normalization drops `model_content` for `tool_result`. Keep that behavior, but do not drop `artifact`.

If `artifact` is already preserved after Step 3, no code change may be needed. Keep the test anyway as a contract.

- [ ] **Step 10: Add integration/API artifact contract test**

In `tests/integration/test_gateway_attachments.py`, use a lower-level store call if full LLM/tool execution is too expensive. The contract to assert is API output:

1. Create or reuse an authenticated test session.
2. Append assistant blocks with a `send_file` tool call and artifact tool result to `state.session_store`.
3. Call `GET /api/v1/sessions/{session_id}?include_archived=true`.
4. Assert returned `timeline_items` includes `kind == "tool_result"` with `payload.artifact.attachment_id`.

Example assertion:

```python
timeline = response.json()["timeline_items"]
tool_result = next(i for i in timeline if i["kind"] == "tool_result")
assert tool_result["payload"]["artifact"]["attachment_id"] == "att-1"
assert tool_result["payload"]["artifact"]["download_url"] == "/api/v1/attachments/att-1"
```

- [ ] **Step 11: Run focused tests**

Run:

```bash
pytest tests/unit/core/test_stream_helpers.py tests/unit/store/test_session_context.py tests/integration/test_gateway_attachments.py -v
```

Expected: PASS.

- [ ] **Step 12: Commit Task 3**

```bash
git add sebastian/core/stream_helpers.py sebastian/store/session_timeline.py tests/unit/core/test_stream_helpers.py tests/unit/store/test_session_context.py tests/integration/test_gateway_attachments.py
git commit -m "feat(stream): 持久化并推送工具附件 artifact" -m "Co-Authored-By: gpt-5 <noreply@openai.com>"
```

---

### Task 4: Android Artifact Parsing And Timeline Hydration

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`
- Test: existing or new SSE parser test

- [ ] **Step 1: Write failing TimelineMapper tests**

Add to `TimelineMapperTest.kt`:

```kotlin
@Test
fun `send_file image artifact produces assistant ImageBlock and hides tool card`() {
    val items = listOf(
        item(
            seq = 1, kind = "tool_call", content = """{"file_path":"photo.png"}""",
            assistantTurnId = "t1", providerCallIndex = 0, blockIndex = 0,
            payload = mapOf("tool_call_id" to "toolu_1", "tool_name" to "send_file"),
        ),
        item(
            seq = 2, kind = "tool_result", content = "已向用户发送图片 photo.png",
            assistantTurnId = "t1", providerCallIndex = 0, blockIndex = 1,
            payload = mapOf(
                "tool_call_id" to "toolu_1",
                "ok" to true,
                "artifact" to mapOf(
                    "kind" to "image",
                    "attachment_id" to "att-1",
                    "filename" to "photo.png",
                    "mime_type" to "image/png",
                    "size_bytes" to 12345.0,
                    "download_url" to "/api/v1/attachments/att-1",
                    "thumbnail_url" to "/api/v1/attachments/att-1/thumbnail",
                ),
            ),
        ),
    )

    val msg = items.toMessagesFromTimeline(baseUrl = "http://server").single()
    assertEquals(MessageRole.ASSISTANT, msg.role)
    assertTrue(msg.blocks.none { it is ContentBlock.ToolBlock })
    val image = msg.blocks.single() as ContentBlock.ImageBlock
    assertEquals("att-1", image.attachmentId)
    assertEquals("http://server/api/v1/attachments/att-1", image.downloadUrl)
}
```

Add equivalent text file test and failed send_file test:

```kotlin
assertTrue(msg.blocks.single() is ContentBlock.ToolBlock)
assertEquals(ToolStatus.FAILED, (msg.blocks.single() as ContentBlock.ToolBlock).status)
```

- [ ] **Step 2: Run mapper tests to verify failure**

Run:

```bash
cd ui/mobile-android && ./gradlew testDebugUnitTest --tests com.sebastian.android.data.remote.dto.TimelineMapperTest
```

Expected: FAIL because send_file still maps to ToolBlock.

- [ ] **Step 3: Add Android `AttachmentArtifact` model**

Modify `StreamEvent.kt`:

```kotlin
data class AttachmentArtifact(
    val kind: String,
    val attachmentId: String,
    val filename: String,
    val mimeType: String,
    val sizeBytes: Long,
    val downloadUrl: String,
    val thumbnailUrl: String? = null,
    val textExcerpt: String? = null,
)
```

Then:

```kotlin
data class ToolExecuted(
    val sessionId: String,
    val toolId: String,
    val name: String,
    val resultSummary: String,
    val artifact: AttachmentArtifact? = null,
) : StreamEvent()
```

- [ ] **Step 4: Add nested payload helpers**

Modify `TimelineItemDto.kt`:

```kotlin
fun payloadMap(key: String): Map<String, Any?>? {
    @Suppress("UNCHECKED_CAST")
    return payload?.get(key) as? Map<String, Any?>
}
```

Add private helpers in `TimelineMapper.kt` if cleaner:

```kotlin
private fun Map<String, Any?>.string(key: String): String? = this[key] as? String
private fun Map<String, Any?>.long(key: String): Long? = when (val value = this[key]) {
    is Long -> value
    is Int -> value.toLong()
    is Double -> value.toLong()
    is Float -> value.toLong()
    else -> null
}
```

- [ ] **Step 5: Implement artifact-to-block mapping**

In `TimelineMapper.kt`, extract a helper:

```kotlin
private fun artifactToBlock(
    sessionId: String,
    artifact: Map<String, Any?>,
    baseUrl: String,
): ContentBlock? {
    val attId = artifact.string("attachment_id") ?: return null
    val kind = artifact.string("kind") ?: return null
    val filename = artifact.string("filename") ?: ""
    val mimeType = artifact.string("mime_type") ?: ""
    val sizeBytes = artifact.long("size_bytes") ?: 0L
    fun absolute(url: String?): String {
        if (url == null) return ""
        return if (url.startsWith("http://") || url.startsWith("https://")) url else "$baseUrl$url"
    }

    return when (kind) {
        "image" -> ContentBlock.ImageBlock(
            blockId = "timeline-$sessionId-artifact-$attId",
            attachmentId = attId,
            filename = filename,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
            downloadUrl = absolute(artifact.string("download_url")),
            thumbnailUrl = artifact.string("thumbnail_url")?.let(::absolute),
        )
        "text_file" -> ContentBlock.FileBlock(
            blockId = "timeline-$sessionId-artifact-$attId",
            attachmentId = attId,
            filename = filename,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
            downloadUrl = absolute(artifact.string("download_url")),
            textExcerpt = artifact.string("text_excerpt"),
        )
        else -> null
    }
}
```

In `buildAssistantBlocks()`, before generating normal tool block:

- Build `toolCallById`
- For each `tool_call`, if matching successful `tool_result` has `artifact` and tool name is `send_file`, add artifact block and mark both call/result as consumed.
- Existing failed/no-artifact path should still produce ToolBlock.

- [ ] **Step 6: Parse SSE artifact**

Modify `SseFrameDto.kt`:

```kotlin
private fun JSONObject.toArtifactOrNull(): AttachmentArtifact? {
    val kind = optString("kind", "").takeIf { it.isNotBlank() } ?: return null
    val attachmentId = optString("attachment_id", "").takeIf { it.isNotBlank() } ?: return null
    val filename = optString("filename", "")
    val mimeType = optString("mime_type", "")
    val sizeBytes = optLong("size_bytes", 0L)
    return AttachmentArtifact(
        kind = kind,
        attachmentId = attachmentId,
        filename = filename,
        mimeType = mimeType,
        sizeBytes = sizeBytes,
        downloadUrl = optString("download_url", ""),
        thumbnailUrl = optString("thumbnail_url", "").takeIf { it.isNotBlank() },
        textExcerpt = optString("text_excerpt", "").takeIf { it.isNotBlank() },
    )
}
```

Then in `tool.executed`:

```kotlin
"tool.executed" -> StreamEvent.ToolExecuted(
    data.getString("session_id"),
    data.getString("tool_id"),
    data.getString("name"),
    data.optString("result_summary", ""),
    data.optJSONObject("artifact")?.toArtifactOrNull(),
)
```

- [ ] **Step 7: Add or update SSE parser tests**

If there is no parser test file, create `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/SseFrameParserTest.kt`.

Test:

```kotlin
@Test
fun `tool executed parses artifact`() {
    val event = SseFrameParser.parse("""{"type":"tool.executed","data":{"session_id":"s1","tool_id":"t1","name":"send_file","result_summary":"sent","artifact":{"kind":"image","attachment_id":"att-1","filename":"photo.png","mime_type":"image/png","size_bytes":1,"download_url":"/api/v1/attachments/att-1","thumbnail_url":"/api/v1/attachments/att-1/thumbnail"}}}""")
    val tool = event as StreamEvent.ToolExecuted
    assertEquals("att-1", tool.artifact?.attachmentId)
}
```

Add backward-compatible no-artifact coverage:

```kotlin
@Test
fun `tool executed without artifact remains supported`() {
    val event = SseFrameParser.parse("""{"type":"tool.executed","data":{"session_id":"s1","tool_id":"t1","name":"Read","result_summary":"ok"}}""")
    val tool = event as StreamEvent.ToolExecuted
    assertEquals("Read", tool.name)
    assertEquals("ok", tool.resultSummary)
    assertEquals(null, tool.artifact)
}
```

- [ ] **Step 8: Run Android mapper/parser tests**

Run:

```bash
cd ui/mobile-android && ./gradlew testDebugUnitTest --tests com.sebastian.android.data.remote.dto.TimelineMapperTest --tests com.sebastian.android.data.remote.dto.SseFrameParserTest
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/StreamEvent.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SseFrameDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/SseFrameParserTest.kt
git commit -m "feat(android): 渲染 send_file 附件 artifact" -m "Co-Authored-By: gpt-5 <noreply@openai.com>"
```

---

### Task 5: Android Realtime Block Replacement

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: Write failing ViewModel tests**

Add tests in `ChatViewModelTest.kt`.

First test: tool block is replaced:

```kotlin
@Test
fun `send_file tool executed with image artifact replaces tool block`() = vmTest {
    activateSession()
    emitEvent(StreamEvent.TurnReceived("s1"))
    emitEvent(StreamEvent.ToolBlockStart("s1", "block-tool", "toolu_1", "send_file"))
    emitEvent(StreamEvent.ToolExecuted(
        sessionId = "s1",
        toolId = "toolu_1",
        name = "send_file",
        resultSummary = "已向用户发送图片 photo.png",
        artifact = AttachmentArtifact(
            kind = "image",
            attachmentId = "att-1",
            filename = "photo.png",
            mimeType = "image/png",
            sizeBytes = 123L,
            downloadUrl = "/api/v1/attachments/att-1",
            thumbnailUrl = "/api/v1/attachments/att-1/thumbnail",
        ),
    ))
    dispatcher.scheduler.advanceTimeBy(200)

    val blocks = viewModel.uiState.value.messages.last().blocks
    assertTrue(blocks.none { it is ContentBlock.ToolBlock })
    val image = blocks.single() as ContentBlock.ImageBlock
    assertEquals("att-1", image.attachmentId)
}
```

Second test: no matching tool block appends once:

```kotlin
emitEvent(StreamEvent.ToolExecuted(... artifact = artifact))
emitEvent(StreamEvent.ToolExecuted(... artifact = artifact))
assertEquals(1, blocks.filterIsInstance<ContentBlock.ImageBlock>().size)
```

Third test: no artifact keeps current tool-card logic.

- [ ] **Step 2: Run ViewModel tests to verify failure**

Run:

```bash
cd ui/mobile-android && ./gradlew testDebugUnitTest --tests com.sebastian.android.viewmodel.ChatViewModelTest
```

Expected: new tests FAIL.

- [ ] **Step 3: Implement artifact block conversion in ChatViewModel**

Add helper:

```kotlin
private fun artifactToContentBlock(sessionId: String, artifact: AttachmentArtifact): ContentBlock {
    val baseUrl = serverUrl.value.trimEnd('/')
    fun absolute(url: String): String =
        if (url.startsWith("http://") || url.startsWith("https://")) url else "$baseUrl$url"

    return when (artifact.kind) {
        "image" -> ContentBlock.ImageBlock(
            blockId = "stream-$sessionId-artifact-${artifact.attachmentId}",
            attachmentId = artifact.attachmentId,
            filename = artifact.filename,
            mimeType = artifact.mimeType,
            sizeBytes = artifact.sizeBytes,
            downloadUrl = absolute(artifact.downloadUrl),
            thumbnailUrl = artifact.thumbnailUrl?.let(::absolute),
        )
        else -> ContentBlock.FileBlock(
            blockId = "stream-$sessionId-artifact-${artifact.attachmentId}",
            attachmentId = artifact.attachmentId,
            filename = artifact.filename,
            mimeType = artifact.mimeType,
            sizeBytes = artifact.sizeBytes,
            downloadUrl = absolute(artifact.downloadUrl),
            textExcerpt = artifact.textExcerpt,
        )
    }
}
```

Use the existing `ChatViewModel` `serverUrl: StateFlow<String>` field. Do not introduce a new `serverUrlFlow` symbol.

- [ ] **Step 4: Implement replacement/de-dupe helper**

Add helper:

```kotlin
private fun ContentBlock.attachmentIdOrNull(): String? = when (this) {
    is ContentBlock.ImageBlock -> attachmentId
    is ContentBlock.FileBlock -> attachmentId
    else -> null
}

private fun replaceToolBlockWithArtifact(
    toolId: String,
    artifactBlock: ContentBlock,
) {
    val artifactAttachmentId = artifactBlock.attachmentIdOrNull() ?: return
    _uiState.update { state ->
        val messages = state.messages.map { message ->
            if (message.id != currentAssistantMessageId) return@map message
            val alreadyPresent = message.blocks.any {
                it.attachmentIdOrNull() == artifactAttachmentId
            }
            if (alreadyPresent) return@map message

            var replaced = false
            val newBlocks = message.blocks.map { block ->
                if (block is ContentBlock.ToolBlock && block.toolId == toolId) {
                    replaced = true
                    artifactBlock
                } else {
                    block
                }
            }
            message.copy(blocks = if (replaced) newBlocks else newBlocks + artifactBlock)
        }
        state.copy(messages = messages)
    }
}
```

Adjust to local style and existing private helpers. Avoid creating a new assistant message if `currentAssistantMessageId` is null.

- [ ] **Step 5: Wire `ToolExecuted` handler**

Modify:

```kotlin
is StreamEvent.ToolExecuted -> {
    if (event.name == "send_file" && event.artifact != null) {
        val sessionId = _uiState.value.activeSessionId
        if (sessionId == event.sessionId && currentAssistantMessageId != null) {
            replaceToolBlockWithArtifact(
                event.toolId,
                artifactToContentBlock(event.sessionId, event.artifact),
            )
        }
    } else {
        updateToolBlockByToolId(event.toolId) { existing ->
            existing.copy(status = ToolStatus.DONE, resultSummary = event.resultSummary)
        }
    }
}
```

- [ ] **Step 6: Run ViewModel tests**

Run:

```bash
cd ui/mobile-android && ./gradlew testDebugUnitTest --tests com.sebastian.android.viewmodel.ChatViewModelTest
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android): 实时显示 send_file 附件" -m "Co-Authored-By: gpt-5 <noreply@openai.com>"
```

---

### Task 6: Documentation And Tool README Rules

**Files:**
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/capabilities/README.md`
- Modify: `sebastian/agents/README.md`
- Modify: `sebastian/agents/forge/README.md`
- Modify: `ui/mobile-android/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`

- [ ] **Step 1: Update backend tool README**

Modify `sebastian/capabilities/tools/README.md`:

- Add `todo_read/` and `send_file/` to directory tree.
- Add rows in modification navigation.
- Add to “能力工具” list.
- Add a new section near `ToolResult 规范`:

```markdown
## 失败返回规范

工具失败必须返回 `ToolResult(ok=False, error=...)`，不要用成功结果承载失败。

`error` 应包含：
- 失败原因
- 下一步建议
- 对确定性失败明确写明 `Do not retry automatically; ...`

确定性失败包括文件不存在、路径是目录、权限不足、类型不支持、大小超限、缺 session context、服务未初始化等。模型收到这类错误后应停止同输入重试，转而告知用户或请求新输入。

临时性错误可以建议稍后重试，但不得在同一 turn 内无限重试。
```

- [ ] **Step 2: Update capabilities README**

Modify `sebastian/capabilities/README.md` tree to include:

- `todo_read/`
- `send_file/`

- [ ] **Step 3: Update agent README docs**

Modify `sebastian/agents/README.md` capability-tool examples to include `todo_read` and `send_file` where it lists standard ability tools.

Modify `sebastian/agents/forge/README.md` if its manifest example still lists only `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`.

If `aide` has no README, no file is needed.

- [ ] **Step 4: Update Android READMEs**

Modify `ui/mobile-android/README.md` timeline hydration section:

```markdown
- Agent 通过 `send_file` 发送的图片/文本文件以 `tool_result.payload.artifact` 进入 timeline；`TimelineMapper` 将其显示为 assistant-side `ImageBlock` / `FileBlock`。实时 SSE 通过 `tool.executed.artifact` 原地替换工具卡，不全量刷新消息列表。
```

Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md` `StreamingMessage` table to include:

```markdown
| `ImageBlock` | `ImageAttachmentBlock` |
| `FileBlock` | `FileAttachmentBlock` |
```

And note these can come from user attachments or `send_file` artifacts.

- [ ] **Step 5: Run docs sanity checks**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 6: Commit Task 6**

```bash
git add sebastian/capabilities/tools/README.md sebastian/capabilities/README.md sebastian/agents/README.md sebastian/agents/forge/README.md ui/mobile-android/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md
git commit -m "docs(tools): 说明 send_file 与工具失败规范" -m "Co-Authored-By: gpt-5 <noreply@openai.com>"
```

---

### Task 7: Full Verification And Graphify Refresh

**Files:**
- No new source edits expected unless verification reveals failures.
- Graph output under `graphify-out/` may change; inspect before deciding whether to commit graph changes.

- [ ] **Step 1: Run backend focused test suite**

Run:

```bash
pytest tests/unit/capabilities/test_todo_read_tool.py tests/unit/capabilities/test_send_file_tool.py tests/unit/core/test_stream_helpers.py tests/unit/store/test_session_context.py tests/integration/test_gateway_attachments.py -v
```

Expected: PASS.

- [ ] **Step 2: Run backend lint/type checks for touched areas**

Run:

```bash
ruff check sebastian/capabilities/tools/todo_read sebastian/capabilities/tools/send_file sebastian/store/attachments.py sebastian/core/stream_helpers.py sebastian/store/session_timeline.py tests/unit/capabilities/test_todo_read_tool.py tests/unit/capabilities/test_send_file_tool.py
```

Expected: PASS.

If formatting needed:

```bash
ruff format sebastian/capabilities/tools/todo_read sebastian/capabilities/tools/send_file tests/unit/capabilities/test_todo_read_tool.py tests/unit/capabilities/test_send_file_tool.py
```

- [ ] **Step 3: Run Android focused tests**

Run:

```bash
cd ui/mobile-android && ./gradlew testDebugUnitTest --tests com.sebastian.android.data.remote.dto.TimelineMapperTest --tests com.sebastian.android.data.remote.dto.SseFrameParserTest --tests com.sebastian.android.viewmodel.ChatViewModelTest
```

Expected: PASS.

- [ ] **Step 4: Run Android compile check**

Run:

```bash
cd ui/mobile-android && ./gradlew testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 5: Refresh graphify code graph**

Run from repo root:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: command completes successfully.

Inspect changes:

```bash
git status --short graphify-out
```

If graphify files changed and repo normally tracks them, commit them in a separate docs/chore commit. If generated noise is excessive, ask the user before staging.

- [ ] **Step 6: Final status**

Run:

```bash
git status --short
```

Expected: clean working tree after all intended commits.

Summarize:

- Backend tests run
- Android tests run
- Graphify refresh result
- Any intentionally skipped verification

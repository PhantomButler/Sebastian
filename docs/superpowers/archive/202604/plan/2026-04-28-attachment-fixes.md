# Attachment Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复附件收发当前仍成立的 7 个问题，确保 Android 能按模型能力选择附件、sub-agent turn 正确提交附件、后端不会接受后静默丢弃附件，并补齐图片校验与预览体验。

**Architecture:** 后端保持「附件先上传、turn API 原子写 user_message + attachment timeline、AgentLoop 从 SessionStore context 投影」架构不变；补齐 session turn 附件路径和 OpenAI-format 投影。Android 保持 ViewModel 持有 pending attachment 状态，新增生产能力加载路径，并让 Composer 传出的附件参数真正进入发送入口。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite, pytest; Kotlin, Jetpack Compose, Hilt, Retrofit/Moshi, Coil.

---

## Source Context

- Spec: `docs/superpowers/specs/2026-04-27-attachments-design.md`
- Original plan: `docs/superpowers/plans/2026-04-27-attachments-implementation.md`
- Current review findings: 2026-04-28 Codex review findings 1-7

## Scope

Fix these confirmed issues:

1. `ChatViewModel.inputCapabilities` has no production loading path.
2. Sub-agent new session drops `attachmentIds`.
3. Existing sub-agent session endpoint ignores `attachment_ids`.
4. OpenAI-format provider accepts attachments but context projection skips them.
5. Image upload validates MIME but not filename extension.
6. `ChatScreen` discards the Composer attachment argument.
7. `AttachmentPreviewBar` lacks image thumbnail previews.

Do not include previously fixed or rejected review items:

- Text file MIME/extension check is already AND-gated in current code.
- `_mark_attached` is already private and documented as non-canonical.

## File Structure

| File | Responsibility |
|------|----------------|
| `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` | Load model input capabilities; send explicit attachment lists from Composer; pass sub-agent initial attachment IDs. |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` | Call capability refresh for current agent and pass Composer attachments into ViewModel. |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt` | Existing binding lookup used by ChatViewModel for sub-agent capabilities. |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt` | Add `attachmentIds` to `createAgentSession`. |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt` | Send `attachment_ids` in `CreateSessionRequest`. |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt` | Add `attachmentIds` to create session request DTO. |
| `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentPreviewBar.kt` | Render image pending attachments with local URI thumbnail using Coil. |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt` | Add/update tests for capability loading and explicit attachment sending. |
| `ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/SessionRepositoryImplTest.kt` | Verify sub-agent create request includes `attachment_ids`. |
| `sebastian/gateway/routes/sessions.py` | Accept `attachment_ids` for `/sessions/{id}/turns`; validate/write attachments and schedule run with preallocated exchange. |
| `sebastian/store/session_context.py` | Project text and image attachments for OpenAI chat-completions format instead of warning+skip. |
| `sebastian/store/attachments.py` | Add image extension allowlist and validate MIME + extension. |
| `tests/integration/test_gateway_attachments.py` | Add existing sub-agent session attachment integration test. |
| `tests/unit/store/test_session_context_attachments.py` | Add OpenAI text/image attachment projection tests. |
| `tests/unit/store/test_attachments.py` | Add image extension validation tests. |
| README files | Update affected module docs after behavior changes. |

## Important Rules

- For Python search/editing, prefer JetBrains PyCharm MCP before shell search.
- Android Studio MCP is not exposed in this Codex session; use JetBrains/PyCharm text index for Kotlin files.
- Do not use `git add .`; stage exact files.
- After code changes, run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

---

## Task 1: Android Loads Model Input Capabilities In Production

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt`

**Design:** `ChatScreen` knows whether it is showing the main conversation or a sub-agent. It should call a new `ChatViewModel.refreshInputCapabilities(agentId: String?)` from `LaunchedEffect(agentId)`. The ViewModel loads default binding for main chat via `SettingsRepository.getDefaultBinding()` and sub-agent binding via `AgentRepository.getAgentBinding(agentId)`.

- [ ] **Step 1: Write failing tests for default binding capabilities**

In `ChatViewModelAttachmentTest.kt`, add an `AgentRepository` mock field and pass it to `ChatViewModel`. Then add:

```kotlin
@Test
fun `refreshInputCapabilities loads default resolved capabilities for main chat`() = vmTest {
    whenever(settingsRepository.getDefaultBinding()).thenReturn(
        Result.success(
            AgentBinding(
                agentType = "__default__",
                accountId = "acc-1",
                modelId = "claude-opus",
                thinkingEffort = null,
                resolved = ResolvedBinding(
                    accountName = "Anthropic",
                    providerDisplayName = "Anthropic",
                    modelDisplayName = "Claude",
                    contextWindowTokens = 200000,
                    thinkingCapability = null,
                    supportsImageInput = true,
                    supportsTextFileInput = true,
                ),
            ),
        ),
    )

    viewModel.refreshInputCapabilities(agentId = null)
    dispatcher.scheduler.advanceUntilIdle()

    assertTrue(viewModel.uiState.value.inputCapabilities.supportsImageInput)
    assertTrue(viewModel.uiState.value.inputCapabilities.supportsTextFileInput)
}
```

- [ ] **Step 2: Write failing test for sub-agent binding capabilities**

In the same test file:

```kotlin
@Test
fun `refreshInputCapabilities loads agent resolved capabilities for sub agent`() = vmTest {
    whenever(agentRepository.getAgentBinding("forge")).thenReturn(
        Result.success(
            AgentBinding(
                agentType = "forge",
                accountId = "acc-1",
                modelId = "vision-model",
                thinkingEffort = null,
                resolved = ResolvedBinding(
                    accountName = "Provider",
                    providerDisplayName = "Provider",
                    modelDisplayName = "Vision",
                    contextWindowTokens = 128000,
                    thinkingCapability = null,
                    supportsImageInput = true,
                    supportsTextFileInput = false,
                ),
            ),
        ),
    )

    viewModel.refreshInputCapabilities(agentId = "forge")
    dispatcher.scheduler.advanceUntilIdle()

    assertTrue(viewModel.uiState.value.inputCapabilities.supportsImageInput)
    assertFalse(viewModel.uiState.value.inputCapabilities.supportsTextFileInput)
}
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cd ui/mobile-android
./gradlew test --tests "com.sebastian.android.viewmodel.ChatViewModelAttachmentTest.refreshInputCapabilities*" 
```

Expected: FAIL because `ChatViewModel` has no `refreshInputCapabilities` and no `AgentRepository` dependency.

- [ ] **Step 4: Implement ViewModel capability loading**

In `ChatViewModel.kt`:

1. Add import:

```kotlin
import com.sebastian.android.data.repository.AgentRepository
```

2. Add constructor dependency:

```kotlin
private val agentRepository: AgentRepository,
```

3. Add public method near other public mutation methods:

```kotlin
fun refreshInputCapabilities(agentId: String?) {
    viewModelScope.launch(dispatcher) {
        val caps = if (agentId == null) {
            settingsRepository.getDefaultBinding()
                .getOrNull()
                ?.resolved
                ?.toInputCapabilities()
        } else {
            agentRepository.getAgentBinding(agentId)
                .getOrNull()
                ?.resolved
                ?.toInputCapabilities()
        } ?: ModelInputCapabilities()

        _uiState.update { it.copy(inputCapabilities = caps) }
    }
}
```

- [ ] **Step 5: Wire ChatScreen to refresh capabilities**

In `ChatScreen.kt`, inside the existing `LaunchedEffect(agentId)` that loads sessions, call:

```kotlin
chatViewModel.refreshInputCapabilities(agentId)
```

The block should become:

```kotlin
LaunchedEffect(agentId) {
    chatViewModel.refreshInputCapabilities(agentId)
    if (agentId != null) {
        sessionViewModel.loadAgentSessions(agentId)
    } else {
        sessionViewModel.loadSessions()
    }
}
```

- [ ] **Step 6: Update all ChatViewModel test constructors**

Every `ChatViewModel(...)` test constructor call must pass the new `agentRepository` mock. Search by class name and update exact test files.

- [ ] **Step 7: Run focused tests**

Run:

```bash
cd ui/mobile-android
./gradlew test --tests "com.sebastian.android.viewmodel.ChatViewModelAttachmentTest"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt
git commit -m "fix(android): 从绑定加载附件输入能力"
```

---

## Task 2: Android Sends Attachment IDs When Creating A Sub-Agent Session

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/SessionRepositoryImplTest.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt`

- [ ] **Step 1: Write failing repository test**

In `SessionRepositoryImplTest.kt`, add or update a test that captures `CreateSessionRequest`:

```kotlin
@Test
fun `createAgentSession sends attachment ids`() = runTest {
    whenever(apiService.createAgentSession(eq("forge"), any())).thenReturn(
        TurnDto(sessionId = "s1", ts = "2026-04-28T00:00:00Z"),
    )

    repository.createAgentSession(
        agentType = "forge",
        title = "",
        sessionId = "client-session",
        attachmentIds = listOf("att-1", "att-2"),
    )

    argumentCaptor<CreateSessionRequest>().apply {
        verify(apiService).createAgentSession(eq("forge"), capture())
        assertEquals("", firstValue.content)
        assertEquals("client-session", firstValue.sessionId)
        assertEquals(listOf("att-1", "att-2"), firstValue.attachmentIds)
    }
}
```

- [ ] **Step 2: Write failing ViewModel test**

In `ChatViewModelAttachmentTest.kt`, add:

```kotlin
@Test
fun `sendAgentMessage new session passes uploaded attachment ids to createAgentSession`() = vmTest {
    val uploadedAtt = PendingAttachment(
        localId = UUID.randomUUID().toString(),
        kind = AttachmentKind.IMAGE,
        uri = makeUri(),
        filename = "photo.jpg",
        mimeType = "image/jpeg",
        sizeBytes = 1024L,
        uploadState = AttachmentUploadState.Uploaded("att_1"),
    )
    viewModel.setTestPendingAttachments(listOf(uploadedAtt))
    whenever(sessionRepository.createAgentSession(any(), any(), any(), any())).thenReturn(
        Result.success(Session(id = "s1", title = "new", agentType = "forge")),
    )

    viewModel.sendAgentMessage("forge", "")
    dispatcher.scheduler.advanceUntilIdle()

    verify(sessionRepository).createAgentSession(
        eq("forge"),
        eq(""),
        any(),
        eq(listOf("att_1")),
    )
}
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cd ui/mobile-android
./gradlew test --tests "*SessionRepositoryImplTest*" --tests "*ChatViewModelAttachmentTest*"
```

Expected: FAIL because the repository API has no `attachmentIds` parameter.

- [ ] **Step 4: Extend CreateSessionRequest**

In `SessionDto.kt`, change:

```kotlin
data class CreateSessionRequest(
    @param:Json(name ="content") val content: String,
    @param:Json(name ="thinking_effort") val thinkingEffort: String? = null,
    @param:Json(name ="session_id") val sessionId: String? = null,
)
```

to:

```kotlin
data class CreateSessionRequest(
    @param:Json(name ="content") val content: String,
    @param:Json(name ="thinking_effort") val thinkingEffort: String? = null,
    @param:Json(name ="session_id") val sessionId: String? = null,
    @param:Json(name ="attachment_ids") val attachmentIds: List<String> = emptyList(),
)
```

- [ ] **Step 5: Extend SessionRepository API and implementation**

In `SessionRepository.kt`, change:

```kotlin
suspend fun createAgentSession(agentType: String, title: String? = null, sessionId: String? = null): Result<Session>
```

to:

```kotlin
suspend fun createAgentSession(
    agentType: String,
    title: String? = null,
    sessionId: String? = null,
    attachmentIds: List<String> = emptyList(),
): Result<Session>
```

In `SessionRepositoryImpl.kt`, update the implementation and DTO:

```kotlin
override suspend fun createAgentSession(
    agentType: String,
    title: String?,
    sessionId: String?,
    attachmentIds: List<String>,
): Result<Session> = runCatching {
    val response = apiService.createAgentSession(
        agentType,
        CreateSessionRequest(
            content = title ?: "新对话",
            sessionId = sessionId,
            attachmentIds = attachmentIds,
        ),
    )
    Session(
        id = response.sessionId,
        title = title ?: "新对话",
        agentType = agentType,
    )
}
```

- [ ] **Step 6: Pass attachment IDs from ChatViewModel**

In `ChatViewModel.sendAgentMessage`, new session branch after upload succeeds, replace:

```kotlin
sessionRepository.createAgentSession(agentId, text, sessionId = clientSessionId)
```

with:

```kotlin
val attachmentIds = uploadedAttachments.mapNotNull { it.attachmentId }
sessionRepository.createAgentSession(
    agentId,
    text,
    sessionId = clientSessionId,
    attachmentIds = attachmentIds,
)
```

- [ ] **Step 7: Update mocks and call sites**

Update all test mocks for `createAgentSession` to include the fourth parameter or use `any()` for it.

- [ ] **Step 8: Run focused tests**

Run:

```bash
cd ui/mobile-android
./gradlew test --tests "*SessionRepositoryImplTest*" --tests "*ChatViewModelAttachmentTest*"
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/SessionRepositoryImplTest.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt
git commit -m "fix(android): sub-agent 首条消息携带附件 ID"
```

---

## Task 3: Backend Supports Attachments For Existing Session Turns

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `tests/integration/test_gateway_attachments.py`

**Design:** `/api/v1/sessions/{session_id}/turns` must mirror attachment behavior in `/api/v1/turns`: validate `content or attachment_ids`, write `user_message + attachment` atomically, pass `persist_user_message=False` and `preallocated_exchange` into the scheduled agent run.

- [ ] **Step 1: Write failing integration test**

In `tests/integration/test_gateway_attachments.py`, add:

```python
def test_existing_agent_session_turn_with_attachment_writes_timeline(client) -> None:
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    create = http_client.post(
        "/api/v1/agents/forge/sessions",
        json={"content": "initial"},
        headers=headers,
    )
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    upload = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
        headers=headers,
    )
    assert upload.status_code == 200
    att_id = upload.json()["attachment_id"]

    turn = http_client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"content": "", "attachment_ids": [att_id]},
        headers=headers,
    )
    assert turn.status_code == 200

    detail = http_client.get(
        f"/api/v1/sessions/{session_id}?include_archived=true",
        headers=headers,
    )
    assert detail.status_code == 200
    timeline = detail.json()["timeline_items"]
    attachment_items = [
        item for item in timeline
        if item["kind"] == "attachment" and item["payload"]["attachment_id"] == att_id
    ]
    assert len(attachment_items) == 1
```

If the fixture does not register `forge`, reuse the agent type used by existing sub-agent attachment tests in the file.

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
pytest tests/integration/test_gateway_attachments.py::test_existing_agent_session_turn_with_attachment_writes_timeline -v
```

Expected: FAIL because `SendTurnBody` ignores `attachment_ids`.

- [ ] **Step 3: Extend SendTurnBody**

In `sessions.py`, replace:

```python
class SendTurnBody(BaseModel):
    content: str
```

with:

```python
class SendTurnBody(BaseModel):
    content: str = ""
    attachment_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Extend _schedule_session_turn**

Change:

```python
async def _schedule_session_turn(
    session: Session,
    content: str,
) -> None:
```

to:

```python
async def _schedule_session_turn(
    session: Session,
    content: str,
    *,
    persist_user_message: bool = True,
    preallocated_exchange: tuple[str, int] | None = None,
) -> None:
```

Inside the function, pass these values into `run_streaming`:

```python
if session.agent_type == "sebastian":
    task = asyncio.create_task(
        state.sebastian.run_streaming(
            content,
            session.id,
            persist_user_message=persist_user_message,
            preallocated_exchange=preallocated_exchange,
        )
    )
else:
    agent = state.agent_instances.get(session.agent_type)
    if agent is None:
        raise ValueError(f"No agent instance for type: {session.agent_type}")
    task = asyncio.create_task(
        agent.run_streaming(
            content,
            session.id,
            persist_user_message=persist_user_message,
            preallocated_exchange=preallocated_exchange,
        )
    )
```

- [ ] **Step 5: Update send_turn_to_session**

Replace the body after `_ensure_llm_ready` with:

```python
session = await _resolve_session(state, session_id)
await _ensure_llm_ready(session.agent_type)
content = body.content.strip()

persist_user_message = True
preallocated_exchange: tuple[str, int] | None = None
if body.attachment_ids:
    from sebastian.gateway.routes._attachment_helpers import (
        validate_and_write_attachment_turn,
    )

    _att_records, exchange_id, exchange_index = await validate_and_write_attachment_turn(
        content=content,
        attachment_ids=body.attachment_ids,
        session_id=session.id,
        agent_type=session.agent_type,
    )
    persist_user_message = False
    preallocated_exchange = (exchange_id, exchange_index)
elif not content:
    raise HTTPException(400, "content or attachment_ids required")

now = await _touch_session(state, session)
await _schedule_session_turn(
    session,
    content,
    persist_user_message=persist_user_message,
    preallocated_exchange=preallocated_exchange,
)
```

- [ ] **Step 6: Run focused test**

Run:

```bash
pytest tests/integration/test_gateway_attachments.py::test_existing_agent_session_turn_with_attachment_writes_timeline -v
```

Expected: PASS.

- [ ] **Step 7: Run related integration tests**

Run:

```bash
pytest tests/integration/test_gateway_attachments.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/gateway/routes/sessions.py tests/integration/test_gateway_attachments.py
git commit -m "fix(gateway): existing session turns 支持附件 ID"
```

---

## Task 4: OpenAI Context Projection Handles Attachments Instead Of Skipping

**Files:**
- Modify: `sebastian/store/session_context.py`
- Modify: `tests/unit/store/test_session_context_attachments.py`

**Design:** Keep P0 simple. For OpenAI chat-completions format:

- Text files merge into the preceding user message as fenced text.
- Images merge into the preceding user message using `{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<data>"}}`.
- If an attachment appears without `attachment_store` and `require_attachments=True`, raise.
- If `require_attachments=False`, skip it.

- [ ] **Step 1: Write failing OpenAI text attachment test**

In `tests/unit/store/test_session_context_attachments.py`, add a fake attachment store helper if one does not exist:

```python
class FakeAttachmentStore:
    def __init__(self, records: dict[str, object], text: dict[str, str], blobs: dict[str, bytes], tmp_path):
        self.records = records
        self.text = text
        self.blobs = blobs
        self.tmp_path = tmp_path

    async def get(self, attachment_id: str):
        return self.records.get(attachment_id)

    def read_text_content(self, record) -> str:
        return self.text[record.id]

    def blob_absolute_path(self, record):
        path = self.tmp_path / record.id
        path.write_bytes(self.blobs[record.id])
        return path
```

Then add:

```python
@pytest.mark.asyncio
async def test_openai_projection_merges_text_attachment_into_user_message(tmp_path: Path) -> None:
    record = SimpleNamespace(id="att-1", kind="text_file", mime_type="text/markdown")
    store = FakeAttachmentStore(
        records={"att-1": record},
        text={"att-1": "# Notes"},
        blobs={},
        tmp_path=tmp_path,
    )
    items = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "read this",
            "exchange_id": "exc-1",
            "seq": 1,
        },
        {
            "kind": "attachment",
            "role": "user",
            "content": "notes.md",
            "exchange_id": "exc-1",
            "seq": 2,
            "payload": {
                "attachment_id": "att-1",
                "kind": "text_file",
                "original_filename": "notes.md",
            },
        },
    ]

    messages = await build_context_messages(
        items,
        "openai",
        attachment_store=store,
    )

    assert messages == [
        {
            "role": "user",
            "content": "read this\n\n用户上传了文本文件：notes.md\n```notes.md\n# Notes\n```",
        }
    ]
```

- [ ] **Step 2: Write failing OpenAI image attachment test**

```python
@pytest.mark.asyncio
async def test_openai_projection_merges_image_attachment_as_image_url(tmp_path: Path) -> None:
    record = SimpleNamespace(id="att-img", kind="image", mime_type="image/png")
    store = FakeAttachmentStore(
        records={"att-img": record},
        text={},
        blobs={"att-img": b"png-bytes"},
        tmp_path=tmp_path,
    )
    items = [
        {
            "kind": "user_message",
            "role": "user",
            "content": "what is this?",
            "exchange_id": "exc-1",
            "seq": 1,
        },
        {
            "kind": "attachment",
            "role": "user",
            "content": "photo.png",
            "exchange_id": "exc-1",
            "seq": 2,
            "payload": {
                "attachment_id": "att-img",
                "kind": "image",
                "original_filename": "photo.png",
            },
        },
    ]

    messages = await build_context_messages(
        items,
        "openai",
        attachment_store=store,
    )

    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0] == {"type": "text", "text": "what is this?"}
    assert messages[0]["content"][1]["type"] == "image_url"
    assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
pytest tests/unit/store/test_session_context_attachments.py::test_openai_projection_merges_text_attachment_into_user_message tests/unit/store/test_session_context_attachments.py::test_openai_projection_merges_image_attachment_as_image_url -v
```

Expected: FAIL because `_build_openai` currently skips attachment items.

- [ ] **Step 4: Make OpenAI projection async and pass attachment_store**

In `session_context.py`, change:

```python
if provider_format in ("openai", "openai_compat"):
    return _build_openai(items)
```

to:

```python
if provider_format in ("openai", "openai_compat"):
    return await _build_openai(
        items,
        attachment_store=attachment_store,
        require_attachments=require_attachments,
    )
```

Change function signature:

```python
async def _build_openai(
    items: list[dict[str, Any]],
    *,
    attachment_store: Any | None,
    require_attachments: bool,
) -> list[dict[str, Any]]:
```

- [ ] **Step 5: Implement pending user merge for OpenAI**

Use the same buffering idea as Anthropic:

```python
pending_user_exchange: str | None = None
pending_user_content: str = ""
pending_user_blocks: list[dict[str, Any]] | None = None

def flush_pending_user() -> None:
    nonlocal pending_user_exchange, pending_user_content, pending_user_blocks
    if pending_user_exchange is None:
        return
    if pending_user_blocks is not None:
        if pending_user_content:
            pending_user_blocks.insert(0, {"type": "text", "text": pending_user_content})
        messages.append({"role": "user", "content": pending_user_blocks})
    else:
        messages.append({"role": "user", "content": pending_user_content})
    pending_user_exchange = None
    pending_user_content = ""
    pending_user_blocks = None
```

Then in the group loop:

```python
if kind == "attachment":
    exchange_id = first.get("exchange_id")
    if not exchange_id or exchange_id != pending_user_exchange:
        if attachment_store is None and require_attachments:
            raise ValueError("attachment_store is required for attachment timeline items")
        flush_pending_user()
        continue

    payload = first.get("payload") or {}
    att_id = payload.get("attachment_id")
    att_kind = payload.get("kind")
    filename = payload.get("original_filename", "file")
    if attachment_store is None:
        if require_attachments:
            raise ValueError("attachment_store is required for attachment timeline items")
        continue
    record = await attachment_store.get(att_id)
    if record is None:
        continue
    if att_kind == "text_file":
        text = await asyncio.to_thread(attachment_store.read_text_content, record)
        fenced = f"用户上传了文本文件：{filename}\n```{filename}\n{text}\n```"
        pending_user_content = (
            f"{pending_user_content}\n\n{fenced}" if pending_user_content else fenced
        )
    elif att_kind == "image":
        blob_path = attachment_store.blob_absolute_path(record)
        data = await asyncio.to_thread(blob_path.read_bytes)
        encoded = base64.b64encode(data).decode()
        if pending_user_blocks is None:
            pending_user_blocks = []
        pending_user_blocks.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{record.mime_type};base64,{encoded}",
                },
            }
        )
    continue
```

For a user message group, buffer instead of immediately appending:

```python
if all(item["kind"] == "user_message" for item in group):
    flush_pending_user()
    pending_user_exchange = first.get("exchange_id") or f"seq-{first.get('seq')}"
    pending_user_content = first["content"]
    pending_user_blocks = None
    continue
```

Before processing non-attachment non-user groups, call `flush_pending_user()`.

At the end of `_build_openai`, call `flush_pending_user()` before return.

- [ ] **Step 6: Run OpenAI projection tests**

Run:

```bash
pytest tests/unit/store/test_session_context_attachments.py::test_openai_projection_merges_text_attachment_into_user_message tests/unit/store/test_session_context_attachments.py::test_openai_projection_merges_image_attachment_as_image_url -v
```

Expected: PASS.

- [ ] **Step 7: Run all session context tests**

Run:

```bash
pytest tests/unit/store/test_session_context.py tests/unit/store/test_session_context_attachments.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/store/session_context.py tests/unit/store/test_session_context_attachments.py
git commit -m "fix(store): OpenAI context projection 支持附件"
```

---

## Task 5: Image Upload Requires MIME And Extension Match

**Files:**
- Modify: `sebastian/store/attachments.py`
- Modify: `tests/unit/store/test_attachments.py`

**Design:** Add a filename extension allowlist for images. Keep validation simple: extension must be one of `.jpg/.jpeg/.png/.webp/.gif`, and MIME must remain in the existing allowlist. Do not try to sniff binary magic in this task; the spec asks for server-side MIME + extension checks.

- [ ] **Step 1: Write failing test for bad image extension**

In `tests/unit/store/test_attachments.py`, add:

```python
async def test_image_rejects_supported_mime_with_unsupported_extension(attachment_store):
    with pytest.raises(AttachmentValidationError):
        await attachment_store.upload_bytes(
            filename="payload.txt",
            content_type="image/png",
            kind="image",
            data=b"png-bytes",
        )
```

- [ ] **Step 2: Write passing test for jpg/jpeg aliases**

```python
async def test_image_accepts_jpg_and_jpeg_extensions(attachment_store):
    jpg = await attachment_store.upload_bytes(
        filename="photo.jpg",
        content_type="image/jpeg",
        kind="image",
        data=b"jpeg-bytes-1",
    )
    jpeg = await attachment_store.upload_bytes(
        filename="photo.jpeg",
        content_type="image/jpeg",
        kind="image",
        data=b"jpeg-bytes-2",
    )
    assert jpg.kind == "image"
    assert jpeg.kind == "image"
```

- [ ] **Step 3: Run tests and verify first fails**

Run:

```bash
pytest tests/unit/store/test_attachments.py::test_image_rejects_supported_mime_with_unsupported_extension tests/unit/store/test_attachments.py::test_image_accepts_jpg_and_jpeg_extensions -v
```

Expected: FAIL because `_validate_image` does not inspect filename.

- [ ] **Step 4: Implement extension validation**

In `attachments.py`, add:

```python
ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
```

Change `upload_bytes` image branch from:

```python
if kind == "image":
    self._validate_image(content_type, data)
```

to:

```python
if kind == "image":
    self._validate_image(filename, content_type, data)
```

Change `_validate_image`:

```python
def _validate_image(self, filename: str, content_type: str, data: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise AttachmentValidationError(f"Unsupported image extension: {suffix!r}")
    if content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise AttachmentValidationError(f"Unsupported image MIME: {content_type!r}")
    if len(data) > MAX_IMAGE_BYTES:
        raise AttachmentValidationError("Image exceeds 10 MB limit")
```

- [ ] **Step 5: Run attachment tests**

Run:

```bash
pytest tests/unit/store/test_attachments.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sebastian/store/attachments.py tests/unit/store/test_attachments.py
git commit -m "fix(store): 图片附件同时校验 MIME 与后缀"
```

---

## Task 6: Composer Attachment Argument Is Used By ChatScreen And ViewModel

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt`

**Design:** Keep pending attachments in `ChatUiState`, but make the send functions accept the explicit list emitted by Composer. This removes the hidden dependency on reading the state at send time and preserves compatibility by defaulting to current state when tests or old call sites omit the parameter.

- [ ] **Step 1: Write failing ViewModel test**

In `ChatViewModelAttachmentTest.kt`, add:

```kotlin
@Test
fun `sendMessage uses explicit attachments argument`() = vmTest {
    val explicit = PendingAttachment(
        localId = UUID.randomUUID().toString(),
        kind = AttachmentKind.TEXT_FILE,
        uri = makeUri(),
        filename = "notes.md",
        mimeType = "text/markdown",
        sizeBytes = 12L,
        uploadState = AttachmentUploadState.Uploaded("att-explicit"),
    )

    viewModel.sendMessage("", attachments = listOf(explicit))
    dispatcher.scheduler.advanceUntilIdle()

    verify(chatRepository).sendTurn(anyOrNull(), eq(""), eq(listOf("att-explicit")))
}
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd ui/mobile-android
./gradlew test --tests "com.sebastian.android.viewmodel.ChatViewModelAttachmentTest.sendMessage uses explicit attachments argument"
```

Expected: FAIL because `sendMessage` has no `attachments` parameter.

- [ ] **Step 3: Update ViewModel send signatures**

In `ChatViewModel.kt`, change:

```kotlin
fun sendMessage(text: String) {
    val attachments = _uiState.value.pendingAttachments
```

to:

```kotlin
fun sendMessage(
    text: String,
    attachments: List<PendingAttachment> = _uiState.value.pendingAttachments,
) {
```

Change:

```kotlin
fun sendAgentMessage(agentId: String, text: String) {
    val attachments = _uiState.value.pendingAttachments
```

to:

```kotlin
fun sendAgentMessage(
    agentId: String,
    text: String,
    attachments: List<PendingAttachment> = _uiState.value.pendingAttachments,
) {
```

- [ ] **Step 4: Update ChatScreen to pass attachments**

In `ChatScreen.kt`, replace:

```kotlin
onSend = { text, _ ->
    if (agentId != null) {
        chatViewModel.sendAgentMessage(agentId, text)
    } else {
        chatViewModel.sendMessage(text)
    }
},
```

with:

```kotlin
onSend = { text, attachments ->
    if (agentId != null) {
        chatViewModel.sendAgentMessage(agentId, text, attachments)
    } else {
        chatViewModel.sendMessage(text, attachments)
    }
},
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd ui/mobile-android
./gradlew test --tests "com.sebastian.android.viewmodel.ChatViewModelAttachmentTest"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelAttachmentTest.kt
git commit -m "fix(android): 使用 Composer 传出的附件列表发送消息"
```

---

## Task 7: Pending Image Attachments Show Local Thumbnails

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentPreviewBar.kt`

**Design:** Keep the current chip for text files and upload/error actions. For image attachments, render a compact thumbnail using the local `PendingAttachment.uri`, with filename and remove/retry controls. Use Coil `AsyncImage`, which is already used in `ui/chat/AttachmentBlocks.kt`.

- [ ] **Step 1: Implement image preview branch**

In `AttachmentPreviewBar.kt`, add imports:

```kotlin
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import coil.compose.AsyncImage
import com.sebastian.android.data.model.AttachmentKind
```

Change the loop:

```kotlin
attachments.forEach { att ->
    AttachmentChip(...)
}
```

to:

```kotlin
attachments.forEach { att ->
    if (att.kind == AttachmentKind.IMAGE) {
        ImageAttachmentPreview(
            att = att,
            onRemove = { onRemove(att.localId) },
            onRetry = { onRetry(att.localId) },
        )
    } else {
        AttachmentChip(
            att = att,
            onRemove = { onRemove(att.localId) },
            onRetry = { onRetry(att.localId) },
        )
    }
}
```

Add:

```kotlin
@Composable
private fun ImageAttachmentPreview(
    att: PendingAttachment,
    onRemove: () -> Unit,
    onRetry: () -> Unit,
) {
    val state = att.uploadState
    val shape = RoundedCornerShape(8.dp)
    Column(
        modifier = Modifier.width(104.dp),
    ) {
        Box(
            modifier = Modifier
                .size(width = 104.dp, height = 78.dp)
                .clip(shape)
                .background(MaterialTheme.colorScheme.surfaceVariant),
        ) {
            AsyncImage(
                model = att.uri,
                contentDescription = att.filename,
                contentScale = ContentScale.Crop,
                modifier = Modifier.matchParentSize(),
            )
            Row(
                modifier = Modifier.align(Alignment.TopEnd),
            ) {
                if (state is AttachmentUploadState.Failed) {
                    IconButton(
                        onClick = onRetry,
                        modifier = Modifier.size(32.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "重试",
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
                IconButton(
                    onClick = onRemove,
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(
                        imageVector = Icons.Default.Close,
                        contentDescription = "移除",
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
            if (state is AttachmentUploadState.Uploading) {
                CircularProgressIndicator(
                    modifier = Modifier
                        .size(20.dp)
                        .align(Alignment.Center),
                    strokeWidth = 2.dp,
                )
            }
            if (state is AttachmentUploadState.Failed) {
                Icon(
                    Icons.Default.Warning,
                    contentDescription = "上传失败",
                    modifier = Modifier
                        .size(20.dp)
                        .align(Alignment.BottomStart)
                        .padding(2.dp),
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
        Text(
            text = att.filename,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
```

- [ ] **Step 2: Compile**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: PASS.

- [ ] **Step 3: Run Android tests**

Run:

```bash
cd ui/mobile-android
./gradlew test
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/AttachmentPreviewBar.kt
git commit -m "fix(android): 附件预览条显示图片缩略图"
```

---

## Task 8: README And Verification

**Files:**
- Modify: `sebastian/gateway/README.md`
- Modify: `sebastian/store/README.md`
- Modify: `ui/mobile-android/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/README.md`

- [ ] **Step 1: Update backend READMEs**

In `sebastian/gateway/README.md`, ensure session turn docs mention:

```markdown
`POST /sessions/{id}/turns` accepts `attachment_ids` and uses the same validation/write path as `POST /turns`.
```

In `sebastian/store/README.md`, update `session_context.py` description:

```markdown
supports Anthropic and OpenAI-format attachment projection; OpenAI text files are injected as fenced text and images as chat-completions `image_url` content blocks.
```

- [ ] **Step 2: Update Android READMEs**

In `ui/mobile-android/README.md` and `viewmodel/README.md`, document that `ChatViewModel.refreshInputCapabilities(agentId)` loads model input capabilities from binding DTOs.

In `ui/composer/README.md`, document that `AttachmentPreviewBar` renders local thumbnails for pending image attachments.

- [ ] **Step 3: Run graphify rebuild**

Run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: command exits 0.

- [ ] **Step 4: Backend focused verification**

Run:

```bash
pytest tests/unit/store/test_attachments.py tests/unit/store/test_session_context_attachments.py tests/integration/test_gateway_attachments.py -v
```

Expected: PASS.

- [ ] **Step 5: Backend lint**

Run:

```bash
ruff check sebastian/ tests/
```

Expected: PASS.

- [ ] **Step 6: Android verification**

Run:

```bash
cd ui/mobile-android
./gradlew test
./gradlew :app:compileDebugKotlin
```

Expected: PASS.

- [ ] **Step 7: Manual smoke test**

Run gateway:

```bash
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8823 --reload
```

Then in Android app:

1. Bind main/default model to a vision-capable model and confirm image picker opens.
2. Bind to a non-vision model and confirm image click shows unsupported toast.
3. Send image-only main chat turn and confirm timeline has `user_message + attachment`.
4. Send file-only sub-agent first message and confirm backend timeline has `attachment`.
5. Send file-only message in an existing sub-agent session and confirm backend timeline has `attachment`.
6. With an OpenAI-format model, send `.md` and confirm the LLM response reflects file content.
7. Confirm pending image attachment shows a local thumbnail before sending.

- [ ] **Step 8: Commit docs and graph**

```bash
git add sebastian/gateway/README.md sebastian/store/README.md ui/mobile-android/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/ui/composer/README.md graphify-out
git commit -m "docs: 更新附件修复后的模块说明"
```

---

## Final Full Verification

Run before opening PR:

```bash
pytest tests/unit/store/test_attachments.py tests/unit/store/test_session_context_attachments.py tests/integration/test_gateway_attachments.py -v
ruff check sebastian/ tests/
cd ui/mobile-android && ./gradlew test && ./gradlew :app:compileDebugKotlin
```

Expected: all commands pass.

## Execution Notes

- Use @superpowers:test-driven-development for each bugfix task.
- Use @superpowers:systematic-debugging if any test fails unexpectedly.
- Use @superpowers:verification-before-completion before claiming completion.
- Use @superpowers:requesting-code-review after implementation and verification.

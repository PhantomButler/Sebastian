# Mobile Timeline Hydration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Android Chat page hydrate from backend `timeline_items` as the complete audit timeline, while using client-generated session ids to reduce new-session REST/SSE races.

**Architecture:** Backend keeps two explicit timeline views: audit timeline for App history (`seq ASC`) and context timeline for LLM input (`effective_seq, seq`). Android adds a dedicated timeline DTO/mapper that projects persisted timeline rows into stable `Message + ContentBlock` UI models, then ChatViewModel uses that history plus SSE event ids for short-term replay. Summary rendering is represented as its own `SummaryBlock`, not as thinking or text.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest, ruff; Kotlin, Jetpack Compose, Moshi, OkHttp SSE-style streaming, Kotlin coroutines/Flow, Gradle unit tests.

---

## Scope

Implement the accepted design in `docs/superpowers/specs/2026-04-22-mobile-timeline-hydration-design.md`.

In scope:

- Backend `GET /api/v1/sessions/{id}?include_archived=true` returns audit `timeline_items` ordered by real `seq ASC`.
- Backend SubAgent session creation accepts optional client-provided `session_id`.
- Android REST hydration prefers `timeline_items` over legacy `messages`.
- Android renders `context_summary` as collapsed `Compressed summary`.
- Android new-session send path generates a session id before opening SSE.
- Android stores and uses delivered SSE event ids as the short-term replay cursor.
- README updates for the new contracts and frontend compression entry points.

Out of scope:

- WebSocket.
- Delta offset or snapshot replay protocol.
- Pagination/virtualized audit history.
- Extra archived-content labeling or dimming.

---

## File Structure

### Backend

- Modify `sebastian/store/session_timeline.py`
  - Make `SessionTimelineStore.get_items()` order by `SessionItemRecord.seq.asc()` only.
- Modify `sebastian/store/session_store.py`
  - Update `get_timeline_items()` docstring to say audit timeline / UI history / `seq ASC`.
  - Keep `get_context_timeline_items()` as the LLM context view.
- Modify `sebastian/gateway/routes/sessions.py`
  - Add a typed `CreateAgentSessionBody`.
  - Add optional `session_id` handling for `POST /agents/{agent_type}/sessions`.
  - Return `409 Conflict` for client id reuse with mismatched agent or goal.
- Test `tests/unit/store/test_session_timeline.py`
  - Replace the old effective-order assertion for `get_timeline_items()`.
  - Keep context-order assertions under `get_context_timeline_items()`.
- Test `tests/integration/gateway/test_sessions_timeline.py` or the existing nearest gateway sessions test file
  - Assert `include_archived=true` returns `timeline_items` by `seq ASC`.
- Test `tests/integration/gateway/test_agent_sessions.py` or the existing nearest gateway sessions test file
  - Assert optional SubAgent `session_id` create/idempotency/conflict behavior.
- Modify `sebastian/store/README.md`
  - Document audit timeline vs context timeline method selection.
- Modify `sebastian/gateway/README.md`
  - Document `include_archived=true` and SubAgent client `session_id`.

### Android Data

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`
  - Add `SummaryBlock`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt`
  - Add `timelineItems` to `SessionDetailResponse`.
- Create `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt`
  - Define timeline row DTO and payload helpers.
- Create `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
  - Convert `List<TimelineItemDto>` to `List<Message>`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
  - Add `include_archived=true` query for `getSession`.
  - Add optional `session_id` to SubAgent create request DTO.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`
  - Prefer timeline mapper, fallback to legacy messages.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt`
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt`
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`
  - Pass optional client ids for new SubAgent sessions.
- Test `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`
  - Cover user/text/thinking/tool summary mapping, ordering, and fallback.
- Test relevant repository tests
  - Cover `include_archived=true`, timeline priority, and legacy fallback.

### Android SSE / ViewModel

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/SseClient.kt`
  - Expose `SseEnvelope(eventId: String?, event: StreamEvent)`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt`
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`
  - Return `Flow<SseEnvelope>` from session stream APIs.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
  - Track per-session `lastDeliveredSseEventId`.
  - Hydrate before reconnect, then connect using saved cursor.
  - Generate client ids for new main/SubAgent sessions.
  - Roll back local user bubble and restore composer text on send failure.
  - Keep block/tool-level idempotency.
- Test `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt`
  - Cover event id exposure and Last-Event-ID reconnect.
- Test `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`
  - Cover provisional session success/failure, existing-session failure, SubAgent provisional flow, hydrate reconnect cursor, duplicate block start.

### Android UI / Docs

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt`
  - Add `SummaryCard` and route `SummaryBlock`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt` if it owns block toggle callbacks.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
  - Add summary toggle method if UI state update lives there.
- Test `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`
  - Cover summary expanded toggle.
- Update `ui/mobile-android/README.md`.
- Update `ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md`.
- Update `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`.
- Update `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md` if it documents chat send/SSE flow.

---

## Task 1: Lock Backend Audit Timeline Ordering

**Files:**
- Modify: `sebastian/store/session_timeline.py`
- Modify: `sebastian/store/session_store.py`
- Modify: `tests/unit/store/test_session_timeline.py`
- Modify: `sebastian/store/README.md`

- [ ] **Step 1: Write/replace the failing store ordering test**

In `tests/unit/store/test_session_timeline.py`, replace the old `test_get_timeline_items_orders_by_effective_seq_then_seq` with a test that proves audit history uses real `seq`, while context history still uses `effective_seq`.

```python
async def test_get_timeline_items_orders_by_seq_for_audit_history(store, session_in_db):
    """get_timeline_items 返回真实写入顺序；context view 才按 effective_seq。"""
    first = await store.append_timeline_items(
        session_in_db.id,
        "sebastian",
        [{"kind": "assistant_message", "content": "old", "role": "assistant"}],
    )
    second = await store.append_timeline_items(
        session_in_db.id,
        "sebastian",
        [{"kind": "assistant_message", "content": "new", "role": "assistant"}],
    )
    summary = await store.append_timeline_items(
        session_in_db.id,
        "sebastian",
        [
            {
                "kind": "context_summary",
                "content": "summary",
                "role": "assistant",
                "effective_seq": first[0]["seq"],
            }
        ],
    )

    audit = await store.get_timeline_items(session_in_db.id, "sebastian")
    context = await store.get_context_timeline_items(session_in_db.id, "sebastian")

    assert [item["id"] for item in audit[-3:]] == [
        first[0]["id"],
        second[0]["id"],
        summary[0]["id"],
    ]
    assert [item["id"] for item in context[:3]] == [
        first[0]["id"],
        summary[0]["id"],
        second[0]["id"],
    ]
```

If the file already has stronger setup helpers, use them, but keep the assertion meaning: `get_timeline_items()` is `seq ASC`; `get_context_timeline_items()` remains context ordering.

- [ ] **Step 2: Run the focused failing test**

Run:

```bash
pytest tests/unit/store/test_session_timeline.py::test_get_timeline_items_orders_by_seq_for_audit_history -q
```

Expected: FAIL before implementation because `SessionTimelineStore.get_items()` still orders by `(effective_seq, seq)`.

- [ ] **Step 3: Implement audit ordering**

In `sebastian/store/session_timeline.py`, change:

```python
q = q.order_by(
    SessionItemRecord.effective_seq.asc(),
    SessionItemRecord.seq.asc(),
)
```

to:

```python
q = q.order_by(SessionItemRecord.seq.asc())
```

- [ ] **Step 4: Update store facade docs**

In `sebastian/store/session_store.py`, update docstrings:

```python
async def get_context_timeline_items(...):
    """Return non-archived items ordered for the LLM context window.

    This view sorts by logical context position and excludes archived source
    items. UI audit history should use get_timeline_items().
    """

async def get_timeline_items(...):
    """Return audit timeline items ordered by real seq ASC.

    This is the UI/history view. Set include_archived=True for the complete
    persisted session history, including compressed source items.
    """
```

- [ ] **Step 5: Update `sebastian/store/README.md`**

Add a short method-selection note near the timeline example:

```markdown
- `get_timeline_items(..., include_archived=True)` is the audit/UI history view and returns real `seq ASC`.
- `get_context_timeline_items(...)` is the LLM context view and returns non-archived items in logical context order.
```

- [ ] **Step 6: Run store tests**

Run:

```bash
pytest tests/unit/store/test_session_timeline.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sebastian/store/session_timeline.py sebastian/store/session_store.py tests/unit/store/test_session_timeline.py sebastian/store/README.md
git commit -m "fix(store): 明确 session audit timeline 顺序" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 2: Add Backend Client IDs for SubAgent Sessions

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Test: `tests/integration/gateway/test_agent_sessions.py` or nearest existing gateway sessions test file
- Modify: `sebastian/gateway/README.md`

- [ ] **Step 1: Locate the existing gateway sessions tests**

Run:

```bash
rg "agents/.*/sessions|create_agent_session|include_archived" tests/integration tests/unit/gateway -n
```

Use the existing file if one already covers `sebastian.gateway.routes.sessions`; otherwise create `tests/integration/gateway/test_agent_sessions.py`.

- [ ] **Step 2: Write failing tests for SubAgent client session id**

Add tests for all required branches. The exact fixture names may differ; adapt to the existing gateway integration fixtures.

Required assertions:

```python
async def test_create_agent_session_accepts_client_session_id(client, auth_headers, configured_llm):
    response = await client.post(
        "/api/v1/agents/research/sessions",
        json={"content": "Find sources", "session_id": "app-session-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "app-session-1"


async def test_create_agent_session_is_idempotent_for_same_client_id(client, auth_headers, configured_llm):
    body = {"content": "Find sources", "session_id": "app-session-2"}

    first = await client.post("/api/v1/agents/research/sessions", json=body, headers=auth_headers)
    second = await client.post("/api/v1/agents/research/sessions", json=body, headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["session_id"] == "app-session-2"
    # If the test harness exposes runner invocations, assert only one initial turn was started.


async def test_create_agent_session_conflicts_when_client_id_matches_different_goal(
    client,
    auth_headers,
    configured_llm,
):
    await client.post(
        "/api/v1/agents/research/sessions",
        json={"content": "First goal", "session_id": "app-session-3"},
        headers=auth_headers,
    )

    response = await client.post(
        "/api/v1/agents/research/sessions",
        json={"content": "Different goal", "session_id": "app-session-3"},
        headers=auth_headers,
    )

    assert response.status_code == 409
```

If the test app only has `sebastian` agent registered, use that registered test agent instead of `research`.

- [ ] **Step 3: Run the failing tests**

Run:

```bash
pytest tests/integration/gateway/test_agent_sessions.py -q
```

Expected: FAIL because the route currently ignores `session_id` and always creates a new `Session()`.

- [ ] **Step 4: Add typed request body**

In `sebastian/gateway/routes/sessions.py`, replace `body: dict[str, Any]` with a Pydantic model:

```python
class CreateAgentSessionBody(BaseModel):
    content: str
    session_id: str | None = None
```

Update validation to use `body.content` and `body.session_id`.

- [ ] **Step 5: Implement idempotent client id handling**

Before creating a new `Session`, add:

```python
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "content is required")

    if body.session_id is not None:
        existing_entry = next(
            (entry for entry in await state.session_store.list_sessions() if entry["id"] == body.session_id),
            None,
        )
        if existing_entry is not None:
            if existing_entry["agent_type"] != agent_type:
                raise HTTPException(409, "session_id already exists with different agent or goal")
            existing = await state.session_store.get_session(body.session_id, agent_type)
            if existing is None:
                raise HTTPException(409, "session_id already exists with different agent or goal")
            if existing.goal == content:
                return {
                    "session_id": existing.id,
                    "ts": existing.created_at.isoformat(),
                }
            raise HTTPException(409, "session_id already exists with different agent or goal")
```

When creating the new session, pass the id:

```python
    session = Session(
        id=body.session_id,
        agent_type=agent_type,
        title=content[:40],
        goal=content,
        depth=2,
    )
```

Use `Session(id=...)` only if the `Session` model accepts `id=None`; otherwise branch so the no-id path calls `Session(...)` without `id`.

- [ ] **Step 6: Confirm no stream existence check is added**

Run:

```bash
rg "stream.*Session not found|/sessions/\\{session_id\\}/stream|get_session\\(" sebastian/gateway -n
```

Expected: no new existence check in `/sessions/{session_id}/stream`.

- [ ] **Step 7: Update `sebastian/gateway/README.md`**

Document:

```markdown
- `POST /agents/{agent_type}/sessions` accepts optional `session_id` for App-created provisional sessions.
- Reusing the same `session_id` with the same `agent_type` and `content` is idempotent and does not start a second initial turn.
- Reusing it with a different agent or content returns `409`.
```

- [ ] **Step 8: Run gateway tests**

Run:

```bash
pytest tests/integration/gateway/test_agent_sessions.py -q
pytest tests/integration/gateway -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add sebastian/gateway/routes/sessions.py tests/integration/gateway/test_agent_sessions.py sebastian/gateway/README.md
git commit -m "feat(gateway): 支持 subagent client session id" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 3: Expose Timeline Items in Android Data Models

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt`
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineItemDtoTest.kt`

- [ ] **Step 1: Write failing DTO/domain tests**

Create `TimelineItemDtoTest.kt`:

```kotlin
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.squareup.moshi.Moshi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TimelineItemDtoTest {
    private val moshi = Moshi.Builder().build()

    @Test
    fun sessionDetailParsesTimelineItems() {
        val json = """
            {
              "session": {
                "id": "s1",
                "agent_type": "sebastian",
                "title": "Hello",
                "goal": "Hello",
                "status": "active",
                "created_at": "2026-04-22T00:00:00Z",
                "updated_at": "2026-04-22T00:00:00Z"
              },
              "messages": [],
              "timeline_items": [
                {
                  "id": "i1",
                  "session_id": "s1",
                  "agent_type": "sebastian",
                  "seq": 1,
                  "kind": "thinking",
                  "role": "assistant",
                  "content": "thinking text",
                  "payload": {"duration_ms": 1234},
                  "archived": false,
                  "turn_id": "t1",
                  "provider_call_index": 0,
                  "block_index": 0,
                  "created_at": "2026-04-22T00:00:01Z"
                }
              ]
            }
        """.trimIndent()

        val adapter = moshi.adapter(SessionDetailResponse::class.java)
        val parsed = adapter.fromJson(json)!!

        assertEquals(1, parsed.timelineItems.size)
        assertEquals("thinking", parsed.timelineItems.first().kind)
        assertEquals(1234L, parsed.timelineItems.first().payloadLong("duration_ms"))
    }

    @Test
    fun summaryBlockIsAlwaysDone() {
        val block = ContentBlock.SummaryBlock(blockId = "summary-1", text = "summary")

        assertTrue(block.isDone)
    }
}
```

Adjust `SessionDto` required fields in the JSON to match the current DTO if names differ.

- [ ] **Step 2: Run the failing DTO test**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.dto.TimelineItemDtoTest"
```

Expected: FAIL because `timelineItems`, `TimelineItemDto`, and `SummaryBlock` do not exist.

- [ ] **Step 3: Add `SummaryBlock`**

In `ContentBlock.kt`, add:

```kotlin
data class SummaryBlock(
    override val blockId: String,
    val text: String,
    val expanded: Boolean = false,
    val sourceSeqStart: Long? = null,
    val sourceSeqEnd: Long? = null,
) : ContentBlock()
```

Update `isDone`:

```kotlin
is SummaryBlock -> true
```

- [ ] **Step 4: Add `TimelineItemDto`**

Create `TimelineItemDto.kt`:

```kotlin
package com.sebastian.android.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class TimelineItemDto(
    @Json(name = "id") val id: String,
    @Json(name = "session_id") val sessionId: String,
    @Json(name = "agent_type") val agentType: String? = null,
    @Json(name = "seq") val seq: Long,
    @Json(name = "kind") val kind: String,
    @Json(name = "role") val role: String? = null,
    @Json(name = "content") val content: String? = null,
    @Json(name = "payload") val payload: Map<String, Any?>? = null,
    @Json(name = "archived") val archived: Boolean = false,
    @Json(name = "turn_id") val turnId: String? = null,
    @Json(name = "provider_call_index") val providerCallIndex: Int? = null,
    @Json(name = "block_index") val blockIndex: Int? = null,
    @Json(name = "created_at") val createdAt: String? = null,
) {
    fun payloadString(key: String): String? = payload?.get(key) as? String

    fun payloadBoolean(key: String): Boolean? = payload?.get(key) as? Boolean

    fun payloadLong(key: String): Long? {
        val value = payload?.get(key) ?: return null
        return when (value) {
            is Long -> value
            is Int -> value.toLong()
            is Double -> value.toLong()
            is Float -> value.toLong()
            else -> null
        }
    }
}
```

- [ ] **Step 5: Add timeline field to session detail**

In `SessionDto.kt`, update `SessionDetailResponse`:

```kotlin
@Json(name = "timeline_items")
val timelineItems: List<TimelineItemDto> = emptyList()
```

- [ ] **Step 6: Run DTO tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.dto.TimelineItemDtoTest"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/ContentBlock.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/SessionDto.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineItemDto.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineItemDtoTest.kt
git commit -m "feat(android): 添加 timeline item 数据模型" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 4: Build Android Timeline Mapper

**Files:**
- Create: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`

- [ ] **Step 1: Write mapper tests**

Create tests that lock the spec behavior:

```kotlin
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.MessageRole
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TimelineMapperTest {
    @Test
    fun mapsTimelineInSeqOrderIgnoringEffectiveSeq() {
        val items = listOf(
            item(seq = 3, kind = "context_summary", content = "summary"),
            item(seq = 1, kind = "user_message", role = "user", content = "hello"),
            item(seq = 2, kind = "assistant_message", role = "assistant", content = "hi", turnId = "t1"),
        )

        val messages = items.toMessagesFromTimeline()

        assertEquals(MessageRole.USER, messages[0].role)
        assertEquals("hello", messages[0].text)
        assertEquals("hi", (messages[1].blocks.single() as ContentBlock.TextBlock).text)
        assertTrue(messages[2].blocks.single() is ContentBlock.SummaryBlock)
    }

    @Test
    fun mapsThinkingWithDurationAndStableBlockId() {
        val messages = listOf(
            item(
                seq = 1,
                kind = "thinking",
                content = "considering",
                turnId = "t1",
                providerCallIndex = 0,
                blockIndex = 2,
                payload = mapOf("duration_ms" to 1500.0),
            )
        ).toMessagesFromTimeline()

        val block = messages.single().blocks.single() as ContentBlock.ThinkingBlock
        assertEquals("considering", block.text)
        assertEquals(1500L, block.durationMs)
        assertEquals("timeline-s1-t1-0-2", block.blockId)
    }

    @Test
    fun mergesToolCallAndResultByToolCallId() {
        val messages = listOf(
            item(
                seq = 1,
                kind = "tool_call",
                content = "search",
                turnId = "t1",
                blockIndex = 0,
                payload = mapOf("tool_call_id" to "tool-1", "name" to "web_search"),
            ),
            item(
                seq = 2,
                kind = "tool_result",
                content = "done",
                turnId = "t1",
                payload = mapOf("tool_call_id" to "tool-1", "ok" to true),
            ),
        ).toMessagesFromTimeline()

        val block = messages.single().blocks.single() as ContentBlock.ToolBlock
        assertEquals("web_search", block.toolName)
        assertEquals("done", block.result)
        assertEquals(ContentBlock.ToolStatus.DONE, block.status)
    }

    @Test
    fun hidesSystemAndRawItems() {
        val messages = listOf(
            item(seq = 1, kind = "system_event", content = "hidden"),
            item(seq = 2, kind = "raw_block", content = "hidden"),
        ).toMessagesFromTimeline()

        assertTrue(messages.isEmpty())
    }

    private fun item(
        seq: Long,
        kind: String,
        role: String? = "assistant",
        content: String? = null,
        turnId: String? = null,
        providerCallIndex: Int? = 0,
        blockIndex: Int? = null,
        payload: Map<String, Any?>? = null,
    ) = TimelineItemDto(
        id = "item-$seq",
        sessionId = "s1",
        agentType = "sebastian",
        seq = seq,
        kind = kind,
        role = role,
        content = content,
        payload = payload,
        turnId = turnId,
        providerCallIndex = providerCallIndex,
        blockIndex = blockIndex,
        createdAt = "2026-04-22T00:00:0${seq}Z",
    )
}
```

Adjust `ToolBlock` property/status names to the actual `ContentBlock.kt` API before committing.

- [ ] **Step 2: Run failing mapper tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.dto.TimelineMapperTest"
```

Expected: FAIL because `toMessagesFromTimeline()` does not exist.

- [ ] **Step 3: Implement mapper skeleton**

Create `TimelineMapper.kt`:

```kotlin
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.ContentBlock
import com.sebastian.android.data.model.Message
import com.sebastian.android.data.model.MessageRole

fun List<TimelineItemDto>.toMessagesFromTimeline(): List<Message> {
    val output = mutableListOf<Message>()
    var currentAssistantKey: AssistantGroupKey? = null
    var currentAssistantItems = mutableListOf<TimelineItemDto>()

    fun flushAssistantGroup() {
        if (currentAssistantItems.isNotEmpty()) {
            currentAssistantItems.toAssistantMessage()?.let(output::add)
            currentAssistantItems = mutableListOf()
            currentAssistantKey = null
        }
    }

    sortedBy { it.seq }.forEach { item ->
        when (item.kind) {
            "user_message" -> {
                flushAssistantGroup()
                output += item.toUserMessage()
            }
            "context_summary" -> {
                flushAssistantGroup()
                output += item.toSummaryMessage()
            }
            "assistant_message", "thinking", "tool_call", "tool_result" -> {
                val key = item.assistantGroupKey()
                if (currentAssistantKey != null && currentAssistantKey != key) {
                    flushAssistantGroup()
                }
                currentAssistantKey = key
                currentAssistantItems += item
            }
            "system_event", "raw_block" -> Unit
        }
    }
    flushAssistantGroup()
    return output
}
```

Then complete helpers. The final implementation must preserve output order by first item `seq`; do not collect all assistant groups and append them after user/summary messages.

- [ ] **Step 4: Implement stable ids and block mapping**

Required helper behavior:

```kotlin
private fun TimelineItemDto.stableBlockId(): String =
    if (turnId != null && providerCallIndex != null && blockIndex != null) {
        "timeline-$sessionId-$turnId-$providerCallIndex-$blockIndex"
    } else {
        "timeline-$sessionId-block-$seq"
    }
```

For assistant groups:

- `thinking` -> done `ThinkingBlock`.
- `assistant_message` -> done `TextBlock`.
- `tool_call` + `tool_result` merge by `payloadString("tool_call_id")`.
- `context_summary` remains separate message with one `SummaryBlock`.
- `system_event` and `raw_block` are skipped.

- [ ] **Step 5: Run mapper tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.dto.TimelineMapperTest"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt
git commit -m "feat(android): 映射 session timeline 历史" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 5: Wire REST Hydration Through Android Repository

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`
- Test: nearest existing repository test, or create `ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/ChatRepositoryImplTest.kt`

- [ ] **Step 1: Write repository tests**

Cover:

- `getMessages(sessionId)` calls `GET /sessions/{id}` with `include_archived=true`.
- If `timeline_items` is non-empty, repository returns timeline-mapped messages.
- If `timeline_items` is empty, repository falls back to legacy `messages`.

Use the existing test style in repository tests. If using MockWebServer, assert:

```kotlin
assertEquals("/api/v1/sessions/s1?include_archived=true", recordedRequest.path)
```

- [ ] **Step 2: Run failing repository tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.repository.ChatRepositoryImplTest"
```

Expected: FAIL because the query parameter and timeline mapping are not wired.

- [ ] **Step 3: Update API service**

Change `getSession` to accept include archived:

```kotlin
@GET("api/v1/sessions/{sessionId}")
suspend fun getSession(
    @Path("sessionId") sessionId: String,
    @Query("include_archived") includeArchived: Boolean = true,
): SessionDetailResponse
```

Use the exact base path style already present in `ApiService.kt`.

- [ ] **Step 4: Prefer timeline in repository**

In `ChatRepositoryImpl.getMessages(sessionId)`:

```kotlin
val response = apiService.getSession(sessionId, includeArchived = true)
return if (response.timelineItems.isNotEmpty()) {
    response.timelineItems.toMessagesFromTimeline()
} else {
    response.messages.map { it.toDomain(sessionId) }
}
```

Keep the current error handling and dispatcher usage.

- [ ] **Step 5: Run repository tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.repository.ChatRepositoryImplTest"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/ChatRepositoryImplTest.kt
git commit -m "feat(android): 使用 timeline hydrate chat history" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 6: Expose SSE Event IDs to ViewModel

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/SseClient.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt`

- [ ] **Step 1: Write failing SSE tests**

Add tests proving public stream output includes event id and reconnect sends the saved cursor.

```kotlin
@Test
fun resilientSseFlowEmitsEnvelopeWithEventId() = runTest {
    // Arrange fake SSE response with:
    // id: 42
    // event: turn.delta
    // data: {...}
    //
    // Act collect first envelope.
    //
    // Assert envelope.eventId == "42" and envelope.event is expected StreamEvent.
}
```

Use existing helpers in `SseClientTest.kt`; do not invent a second SSE parser path.

- [ ] **Step 2: Run failing SSE tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.SseClientTest"
```

Expected: FAIL because public APIs emit only `StreamEvent`.

- [ ] **Step 3: Add envelope model**

In `SseClient.kt`, add near existing stream event types:

```kotlin
data class SseEnvelope(
    val eventId: String?,
    val event: StreamEvent,
)
```

Change public flow return types from `Flow<StreamEvent>` to `Flow<SseEnvelope>`. The existing internal `Pair<String?, StreamEvent>` can be replaced with `SseEnvelope`.

- [ ] **Step 4: Preserve Last-Event-ID behavior**

When reconnecting internally, continue to track latest emitted id. The caller-provided `lastEventId` remains the initial cursor:

```kotlin
var currentLastEventId = lastEventId
...
emit(envelope)
if (envelope.eventId != null) currentLastEventId = envelope.eventId
```

Keep the header name consistent with the current client unless tests show backend compatibility requires changing it.

- [ ] **Step 5: Update repository interfaces**

Update session stream method signatures in `ChatRepository.kt` and `ChatRepositoryImpl.kt` to return `Flow<SseEnvelope>`.

- [ ] **Step 6: Run SSE tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.remote.SseClientTest"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/SseClient.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/SseClientTest.kt
git commit -m "feat(android): 暴露 sse replay cursor" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 7: Implement ViewModel Replay Cursor and Provisional Main Sessions

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: Write failing tests for new main conversation success**

Add/modify a test:

```kotlin
@Test
fun newMainConversationGeneratesSessionIdBeforeStartingSseAndPostingTurn() = runTest {
    // Arrange activeSessionId is null and repository captures sessionStream + sendTurn inputs.
    // Act viewModel.sendMessage("hello").
    // Assert sessionStream was called with the same non-null session id used by sendTurn.
    // Assert first stream call uses lastEventId = "0".
}
```

Inject a deterministic id generator into `ChatViewModel` if no current seam exists:

```kotlin
private val sessionIdProvider: () -> String = { UUID.randomUUID().toString() }
```

Use the existing constructor default so production callers do not change.

- [ ] **Step 2: Write failing tests for new main conversation failure**

Required assertions:

- Local user bubble is removed.
- `activeSessionId` becomes `null`.
- Composer restore effect emits the original text.
- Toast/effect emits `发送失败，请重试`.

- [ ] **Step 3: Write failing tests for existing session failure**

Required assertions:

- Local user bubble is removed.
- `activeSessionId` remains the existing id.
- Composer restore effect emits the original text.
- Toast/effect emits `发送失败，请重试`.

- [ ] **Step 4: Write failing test for hydrate reconnect cursor**

Required behavior:

- ViewModel processes an envelope with `eventId = "7"`.
- After foreground/switch reconnect for that session, REST hydrate runs first.
- SSE reconnect uses `lastEventId = "7"`.
- If no event id was ever delivered for an existing session, reconnect uses `null`, not `"0"`.

- [ ] **Step 5: Run failing ViewModel tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest"
```

Expected: FAIL because ViewModel still waits for backend-created ids and stream events lack envelope handling.

- [ ] **Step 6: Add UI effect stream**

In `ChatViewModel.kt`, add:

```kotlin
sealed interface ChatUiEffect {
    data class RestoreComposerText(val text: String) : ChatUiEffect
    data class ShowToast(val message: String) : ChatUiEffect
}

private val _uiEffects = MutableSharedFlow<ChatUiEffect>()
val uiEffects: SharedFlow<ChatUiEffect> = _uiEffects.asSharedFlow()
```

If existing `toastEvents` is still consumed by UI tests, bridge it during migration:

```kotlin
private suspend fun emitSendFailed(text: String) {
    _uiEffects.emit(ChatUiEffect.RestoreComposerText(text))
    _uiEffects.emit(ChatUiEffect.ShowToast("发送失败，请重试"))
    _toastEvents.emit("发送失败，请重试")
}
```

- [ ] **Step 7: Track SSE cursors**

Add:

```kotlin
private val lastDeliveredSseEventIds = mutableMapOf<String, String>()
```

When collecting:

```kotlin
chatRepository.sessionStream(baseUrl, sessionId, lastEventId)
    .collect { envelope ->
        handleStreamEvent(envelope.event)
        envelope.eventId?.let { lastDeliveredSseEventIds[sessionId] = it }
    }
```

- [ ] **Step 8: Update SSE start logic**

Make `startSseCollection` take an explicit cursor:

```kotlin
private fun startSseCollection(
    sessionId: String = requireNotNull(activeSessionId),
    lastEventId: String? = lastDeliveredSseEventIds[sessionId],
)
```

Use `lastEventId = "0"` only for first connection of a new provisional session.

- [ ] **Step 9: Generate client id for new main send**

For `activeSessionId == null`:

```kotlin
val clientSessionId = sessionIdProvider()
activeSessionId = clientSessionId
provisionalSessionId = clientSessionId
appendLocalUserBubble(clientSessionId, text)
startSseCollection(sessionId = clientSessionId, lastEventId = "0")
chatRepository.sendTurn(text, sessionId = clientSessionId)
provisionalSessionId = null
```

On send failure:

```kotlin
stopSseCollection()
removeLocalUserBubble(localUserMessageId)
activeSessionId = null
provisionalSessionId = null
emitSendFailed(text)
```

- [ ] **Step 10: Preserve existing-session rollback**

For existing sessions, keep `activeSessionId`, remove only the just-added local user bubble, and emit restore/toast effects.

- [ ] **Step 11: Run ViewModel tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest"
```

Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android): 用 client session id 启动主对话" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 8: Implement Provisional SubAgent Session Flow

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/AgentRepositoryImplTest.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: Write failing repository test for SubAgent client id**

Assert request body contains both `content` and `session_id`:

```json
{"content":"plan trip","session_id":"client-subagent-1"}
```

Also assert omitting client id preserves the old body shape except for nullable field behavior accepted by backend.

- [ ] **Step 2: Write failing ViewModel tests for SubAgent provisional flow**

Cover:

- New SubAgent session generates a client id.
- SSE starts before `createAgentSession`.
- Repository create call receives the same id.
- Failure rolls back local user bubble, clears provisional id, restores composer text, and emits toast.

- [ ] **Step 3: Run failing tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.repository.AgentRepositoryImplTest" --tests "com.sebastian.android.viewmodel.ChatViewModelTest"
```

Expected: FAIL.

- [ ] **Step 4: Add optional id to create request DTO**

In `ApiService.kt`, update the SubAgent create request:

```kotlin
@JsonClass(generateAdapter = true)
data class CreateSessionRequest(
    val content: String,
    @Json(name = "session_id") val sessionId: String? = null,
    ...
)
```

Keep existing fields such as thinking effort if present.

- [ ] **Step 5: Thread optional id through repositories**

Update repository APIs to accept `sessionId: String? = null`, preserving old call sites:

```kotlin
suspend fun createAgentSession(
    agentType: String,
    content: String,
    sessionId: String? = null,
): String
```

- [ ] **Step 6: Implement SubAgent provisional send in ViewModel**

Mirror the main conversation flow:

```kotlin
val clientSessionId = sessionIdProvider()
activeSessionId = clientSessionId
provisionalSessionId = clientSessionId
appendLocalUserBubble(clientSessionId, text)
startSseCollection(sessionId = clientSessionId, lastEventId = "0")
agentRepository.createAgentSession(agentType, text, sessionId = clientSessionId)
provisionalSessionId = null
```

On failure, stop SSE and roll back like Task 7.

- [ ] **Step 7: Run tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.data.repository.AgentRepositoryImplTest" --tests "com.sebastian.android.viewmodel.ChatViewModelTest"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/ApiService.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/AgentRepositoryImpl.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepository.kt ui/mobile-android/app/src/main/java/com/sebastian/android/data/repository/SessionRepositoryImpl.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/repository/AgentRepositoryImplTest.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android): 用 client session id 启动 subagent 对话" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 9: Render Compressed Summary Blocks

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt` if block toggle callbacks pass through this file
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`

- [ ] **Step 1: Write failing summary toggle test**

In `ChatViewModelTest.kt`, create a message containing `SummaryBlock(expanded=false)`, call the new toggle method, and assert it becomes expanded.

```kotlin
@Test
fun toggleSummaryBlockFlipsExpandedState() = runTest {
    // Seed state with assistant message containing SummaryBlock(blockId = "summary-1").
    viewModel.toggleSummaryBlock("message-1", "summary-1")

    val block = viewModel.uiState.value.messages
        .single { it.id == "message-1" }
        .blocks.single() as ContentBlock.SummaryBlock
    assertTrue(block.expanded)
}
```

- [ ] **Step 2: Run failing summary toggle test**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest.toggleSummaryBlockFlipsExpandedState"
```

Expected: FAIL because no toggle exists.

- [ ] **Step 3: Add ViewModel toggle**

Implement the same pattern as thinking toggle:

```kotlin
fun toggleSummaryBlock(messageId: String, blockId: String) {
    updateBlock(messageId, blockId) { block ->
        if (block is ContentBlock.SummaryBlock) {
            block.copy(expanded = !block.expanded)
        } else {
            block
        }
    }
}
```

Use the actual block-update helper names in `ChatViewModel.kt`.

- [ ] **Step 4: Add `SummaryCard`**

In `StreamingMessage.kt`, add a composable close to `ThinkingCard`:

```kotlin
@Composable
private fun SummaryCard(
    block: ContentBlock.SummaryBlock,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Title must be exactly "Compressed summary".
    // Default collapsed; expanded body renders block.text with the existing Markdown renderer.
}
```

Reuse local theme tokens and markdown renderer already used for assistant text. Do not reuse `ThinkingBlock` as the data type.

- [ ] **Step 5: Route summary blocks in assistant rendering**

In the existing `AssistantMessageBlocks` branch:

```kotlin
is ContentBlock.SummaryBlock -> SummaryCard(
    block = block,
    onToggle = { onSummaryToggle(message.id, block.blockId) },
)
```

Thread `onSummaryToggle` through `MessageList.kt` only if the current component boundary requires it.

- [ ] **Step 6: Run ViewModel tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.viewmodel.ChatViewModelTest"
```

Expected: PASS.

- [ ] **Step 7: Compile Android**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL.

- [ ] **Step 8: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/StreamingMessage.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/MessageList.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt
git commit -m "feat(android): 渲染 compressed summary block" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 10: Update READMEs for Frontend Compression Integration

**Files:**
- Modify: `ui/mobile-android/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md` if it documents ChatViewModel/session streaming

- [ ] **Step 1: Update Android root README**

In `ui/mobile-android/README.md`, document:

```markdown
Chat history now hydrates from `GET /api/v1/sessions/{id}?include_archived=true`.
The App treats `timeline_items` as canonical and keeps `messages` only as a legacy fallback.
```

- [ ] **Step 2: Update data README**

In `ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md`, add:

```markdown
- `TimelineItemDto` mirrors backend session timeline rows.
- `TimelineMapper` is the only place that converts persisted timeline rows into `Message + ContentBlock`.
- `context_summary` maps to `ContentBlock.SummaryBlock`; archived source rows are displayed normally.
```

- [ ] **Step 3: Update chat UI README**

In `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`, add:

```markdown
- `SummaryBlock` renders as a collapsed card titled `Compressed summary`.
- Summary cards are the visual marker that preceding content was compressed; archived original blocks are not dimmed or hidden.
```

- [ ] **Step 4: Update ViewModel README if relevant**

If `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md` covers ChatViewModel streaming, add:

```markdown
- New sessions use client-generated ids: the App starts SSE first, then posts the turn with the same `session_id`.
- `lastDeliveredSseEventId` is the short-term replay cursor; REST timeline remains the source of truth.
```

- [ ] **Step 5: Run README link sanity search**

Run:

```bash
rg "TimelineMapper|SummaryBlock|include_archived|Compressed summary|lastDeliveredSseEventId" ui/mobile-android/README.md ui/mobile-android/app/src/main/java/com/sebastian/android
```

Expected: The new terms are documented in the relevant README files and code references exist.

- [ ] **Step 6: Commit**

```bash
git add ui/mobile-android/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/data/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/README.md
git commit -m "docs(android): 记录 timeline hydration 接入点" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Task 11: Full Verification and Cleanup

**Files:**
- No required source changes unless verification exposes failures.

- [ ] **Step 1: Run backend focused verification**

Run:

```bash
pytest tests/unit/store tests/integration/gateway -q
```

Expected: PASS.

- [ ] **Step 2: Run backend lint**

Run:

```bash
ruff check sebastian/ tests/
```

Expected: PASS.

- [ ] **Step 3: Run Android unit tests**

Run:

```bash
cd ui/mobile-android
./gradlew :app:testDebugUnitTest
```

Expected: PASS.

- [ ] **Step 4: Run Android compile**

Run:

```bash
cd ui/mobile-android
./gradlew :app:compileDebugKotlin
```

Expected: BUILD SUCCESSFUL.

- [ ] **Step 5: Inspect changed files**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: No unexpected unrelated files. If verification fixes produced changes, commit them atomically with the relevant task scope.

- [ ] **Step 6: Final commit if cleanup changes exist**

Only if Step 5 shows legitimate cleanup changes:

```bash
git add <specific-files>
git commit -m "chore: 收口 timeline hydration 验证修复" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Implementation Notes

- Do not hide archived rows in Android. Archived original content should look like normal history.
- Do not use `effective_seq` for App UI ordering.
- Do not add a backend existence check to `/sessions/{id}/stream`; pre-subscribe to a not-yet-created client id is part of the design.
- Do not make `SummaryBlock` a subtype or presentation of thinking. It is a separate content block.
- Keep `messages` fallback until all supported clients are moved to timeline.
- If any touched Android file is already much larger than 800 lines, pause and call it out before adding large new logic. Prefer new focused mapper files over growing ViewModel where possible.

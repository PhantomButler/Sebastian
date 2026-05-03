# Sebastian Browser Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Sebastian's first-party Playwright-backed browser tools with persistent headless browsing, safe observation, screenshots, and downloadable artifacts.

**Architecture:** Implement the browser as a Sebastian-only Native Tool package under `sebastian/capabilities/tools/browser/`. The work is split into platform foundations first: runtime config, attachment/artifact support, permission preflight, network safety, browser lifecycle, then the public tools and docs. Browser observation and high-impact actions are constrained by PolicyGate and tool-level hard guards.

**Tech Stack:** Python 3.12+, Playwright Chromium, FastAPI/SSE, SQLAlchemy async + SQLite, Typer deployment docs, Kotlin/Jetpack Compose Android artifact rendering, pytest/pytest-asyncio, Gradle unit tests.

---

## Reference Documents

- Spec: `docs/superpowers/specs/2026-05-03-sebastian-browser-tool-design.md`
- Capability docs: `sebastian/capabilities/README.md`, `sebastian/capabilities/tools/README.md`
- Gateway docs: `sebastian/gateway/README.md`, `sebastian/gateway/routes/README.md`
- Android docs: `ui/mobile-android/README.md`, `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`

## Scope Notes

This is a large feature. Do not implement it as one PR unless the owner explicitly wants a single large PR. The safest delivery is 6 PRs in this order:

1. Generic binary/download artifacts, backend plus Android rendering.
2. Permission preflight/enricher support.
3. Browser config and lifecycle skeleton.
4. Hard egress proxy and safety guard.
5. Playwright manager plus observe/action/capture/download tools.
6. Deployment docs, CHANGELOG, graphify, and full verification.

Each task below is written so it can be implemented and committed independently.

PR grouping: PR 1 contains Tasks 1-2, PR 2 contains Task 3, PR 3 contains Task 4, PR 4 contains Task 5, PR 5 contains Tasks 6-7, and PR 6 contains Task 8 plus final verification.

## File Structure

### Backend Browser Package

- Create `sebastian/capabilities/tools/browser/__init__.py`
  Registers five Native Tools: `browser_open`, `browser_observe`, `browser_act`, `browser_capture`, `browser_downloads`.
- Create `sebastian/capabilities/tools/browser/manager.py`
  Owns Playwright lifecycle, persistent context, current page, downloads/screenshots dirs, async lock, and shutdown.
- Create `sebastian/capabilities/tools/browser/safety.py`
  URL parsing, protocol checks, forbidden address classification, and action validation.
- Create `sebastian/capabilities/tools/browser/network.py`
  DNS resolver plus the concrete hard egress boundary. v1 uses a local filtering proxy by default; do not stop at resolver/config-only checks.
- Create `sebastian/capabilities/tools/browser/proxy.py`
  HTTP/HTTPS CONNECT filtering proxy implementation. This is a standalone PR/task before Playwright tools are enabled.
- Create `sebastian/capabilities/tools/browser/observe.py`
  Sanitized page observation helpers. Must avoid password values, hidden input values, and long raw form values.
- Create `sebastian/capabilities/tools/browser/downloads.py`
  Download path resolution and send/list helpers constrained to browser downloads dir.
- Create `sebastian/capabilities/tools/browser/artifacts.py`
  Screenshot and download artifact creation helpers, reusing AttachmentStore where possible.

### Permission Layer

- Modify `sebastian/permissions/gate.py`
  Add tool-specific review input preflight/enricher support before `PermissionReviewer.review()`.
- Modify `sebastian/capabilities/registry.py`
  Expose optional preflight metadata hooks for native tools.
- Modify `sebastian/core/tool.py`
  Add optional tool metadata for review preflight if needed, while preserving existing decorator behavior.
- Modify `sebastian/permissions/types.py`
  Add a small dataclass for preflight results if that keeps the interface clean.

### Runtime Config And Lifecycle

- Modify `pyproject.toml`
  Add `playwright` to default dependencies.
- Modify `sebastian/config/__init__.py`
  Add browser settings and browser directory helpers.
- Modify `.env.example`
  Document browser settings.
- Modify `sebastian/config/README.md`
  Document settings and directory layout.
- Modify `sebastian/gateway/state.py`
  Add `browser_manager: BrowserSessionManager | None`.
- Modify `sebastian/gateway/app.py`
  Initialize browser runtime lazily or assign manager, and close it in lifespan shutdown before DB dispose.

### Browser Tool Exposure

- Modify `sebastian/orchestrator/sebas.py`
  Add browser tool names only after the tools exist, in Task 7.
- Modify `sebastian/core/tool.py`, `sebastian/core/protocols.py`, `sebastian/core/agent_loop.py`, and `sebastian/permissions/gate.py` as needed
  Add explicit Sebastian-only visibility/execution guards for browser tools. Do not rely only on "not listed in sub-agent manifests", because extension sub-agents with no `allowed_tools` currently mean unrestricted.

### Generic Binary Artifacts

- Modify `sebastian/store/attachments.py`
  Add generic download/binary validation and max size.
- Modify `sebastian/store/models.py`
  No new column should be necessary if `kind` remains string, but confirm invariants.
- Modify `sebastian/store/database.py`
  Add schema verification/migration only if model changes require it.
- Modify `sebastian/gateway/routes/attachments.py`
  Accept and serve the new generic binary/download kind.
- Modify `sebastian/capabilities/tools/send_file/__init__.py`
  Either support generic binary or keep send_file unchanged and implement a browser-specific artifact sender.
- Inspect/Test `sebastian/core/stream_helpers.py`
  No behavior change is expected. Add regression coverage for download artifact pass-through and modify this file only if that regression proves the current pass-through contract is broken.
- Test: `tests/unit/core/test_stream_helpers.py`
  Prove generic download artifact payload survives live `TOOL_EXECUTED` event emission.
- Test: `tests/unit/store/test_session_store.py` or nearest timeline persistence test
  Prove generic download artifact payload is persisted and mapped back from timeline unchanged.

### Android Artifact Rendering

- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
  Map the new generic download artifact kind to `ContentBlock.FileBlock`.
- Modify `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
  Render new generic download artifact kind from live SSE.
- Modify `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`
  Add timeline mapping test.
- Modify `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`
  Add SSE artifact rendering test.

### Docs

- Modify `sebastian/capabilities/tools/README.md`
- Modify `sebastian/capabilities/README.md`
- Modify `sebastian/gateway/README.md`
- Modify `sebastian/gateway/routes/README.md`
- Modify `ui/mobile-android/README.md` or narrower module READMEs touched by the Android change.
- Modify `docs/AGENTIC_DEPLOYMENT.md`
- Modify `CHANGELOG.md`

---

## Task 1: Add Generic Binary Download Artifacts

**Files:**
- Modify: `sebastian/store/attachments.py`
- Modify: `sebastian/gateway/routes/attachments.py`
- Modify: `sebastian/capabilities/tools/send_file/__init__.py` only if choosing to generalize `send_file_path`
- Test-only unless regression fails: `sebastian/core/stream_helpers.py`
- Test: `tests/unit/store/test_attachments.py`
- Test: `tests/integration/test_gateway_attachments.py`
- Test: `tests/unit/core/test_stream_helpers.py`
- Test: `tests/unit/store/test_session_store.py` or nearest timeline artifact persistence test

- [ ] **Step 1: Inspect existing attachment tests**

Run:

```bash
pytest --collect-only tests/unit -q | grep attachment
```

Expected: identify the exact existing attachment test files. If `grep` is not available or no tests exist, use PyCharm search and create focused tests under `tests/unit/store/` and the existing gateway attachment test location.

- [ ] **Step 2: Write failing store tests for generic binary**

Add tests that express the intended behavior:

```python
async def test_upload_generic_download_accepts_pdf(tmp_path, db_factory):
    store = AttachmentStore(tmp_path / "attachments", db_factory)
    uploaded = await store.upload_bytes(
        filename="report.pdf",
        content_type="application/pdf",
        kind="download",
        data=b"%PDF-1.4\n...",
    )
    assert uploaded.kind == "download"
    assert uploaded.mime_type == "application/pdf"
    assert uploaded.text_excerpt is None
    assert store.blob_absolute_path(await store.get(uploaded.id)).read_bytes().startswith(b"%PDF")
```

Also add a max-size rejection test:

```python
async def test_upload_generic_download_rejects_oversized_blob(tmp_path, db_factory):
    store = AttachmentStore(tmp_path / "attachments", db_factory)
    with pytest.raises(AttachmentValidationError, match="too large"):
        await store.upload_bytes(
            filename="large.zip",
            content_type="application/zip",
            kind="download",
            data=b"x" * (MAX_DOWNLOAD_BYTES + 1),
        )
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
pytest tests/unit/store/test_attachments.py -q
```

Expected: FAIL because `kind="download"` is unknown.

- [ ] **Step 4: Implement generic download validation**

In `sebastian/store/attachments.py`:

```python
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_DOWNLOAD_MIME_TYPES = frozenset({
    "application/pdf",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
})

def _validate_download(self, filename: str, content_type: str, data: bytes) -> None:
    if not filename:
        raise AttachmentValidationError("Download filename is required")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise AttachmentValidationError("Download file is too large")
    if not data:
        raise AttachmentValidationError("Download file is empty")
```

Wire it into `upload_bytes()`:

```python
if kind == "image":
    self._validate_image(filename, content_type, data)
elif kind == "text_file":
    self._validate_text_file(filename, content_type, data)
elif kind == "download":
    self._validate_download(filename, content_type, data)
else:
    raise AttachmentValidationError(f"Unknown kind: {kind!r}")
```

Keep `text_excerpt = None` for download artifacts.

- [ ] **Step 5: Update attachment routes**

In `sebastian/gateway/routes/attachments.py`, widen the accepted kind:

```python
AttachmentKind = Literal["image", "text_file", "download"]

async def upload_attachment(
    kind: AttachmentKind = Form(...),
    ...
) -> JSONDict:
    ...
```

No change should be required to `GET /attachments/{id}` because it already streams stored bytes using `record.mime_type`.

- [ ] **Step 6: Add route tests**

Add or update a test that posts `kind=download` with `application/pdf` and verifies:

- `kind == "download"`
- `mime_type == "application/pdf"`
- `GET /attachments/{id}` returns the exact bytes and content type

- [ ] **Step 7: Add SSE/timeline artifact pass-through tests**

Add a `stream_helpers` test that executes the existing tool-result-to-event path with:

```python
artifact = {
    "kind": "download",
    "attachment_id": "att-download",
    "filename": "report.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 1234,
    "download_url": "/api/v1/attachments/att-download",
}
```

Expected live event payload contains the exact artifact fields:

```python
assert event_data["artifact"] == artifact
```

`ToolResult` must keep using the existing contract: artifact payloads live under `ToolResult.output["artifact"]`. Do not add a top-level `ToolResult.artifact` field. Prefer no `stream_helpers.py` behavior change; the test exists to prove the current SSE/timeline conversion passes unknown artifact kinds through unchanged.

Add a timeline persistence/mapping test using the nearest existing `SessionStore` or timeline mapper test. Persist a tool result with the same artifact and verify the fetched timeline item still contains:

- `kind == "download"`
- `download_url`
- `filename`
- `mime_type`
- `size_bytes`

Do not rely only on Android tests; the backend must prove the artifact survives SSE and stored timeline payloads before mobile parses it.

- [ ] **Step 8: Run focused backend tests**

Run:

```bash
pytest tests/unit/store/test_attachments.py tests/integration/test_gateway_attachments.py tests/unit/core/test_stream_helpers.py tests/unit/store/test_session_store.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add sebastian/store/attachments.py sebastian/gateway/routes/attachments.py tests/unit/store/test_attachments.py tests/integration/test_gateway_attachments.py tests/unit/core/test_stream_helpers.py tests/unit/store/test_session_store.py
git commit -m "feat(attachments): 支持通用下载文件 artifact"
```

---

## Task 2: Render Generic Download Artifacts On Android

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt`
- Test: `ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt`
- Docs: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md`

Both Android paths are required: `TimelineMapper.kt` covers hydrated/persisted timeline items, and `ChatViewModel.kt` covers live SSE artifact events. Do not rely on the live-path unknown-kind fallback for `download`; make it an explicit supported artifact kind in both places.

- [ ] **Step 1: Write failing timeline mapper test**

Add a test with artifact kind `download`:

```kotlin
@Test
fun `download artifact produces assistant FileBlock`() {
    val block = artifactMapToBlock(
        sessionId = "s1",
        artifact = mapOf(
            "kind" to "download",
            "attachment_id" to "att-1",
            "filename" to "report.pdf",
            "mime_type" to "application/pdf",
            "size_bytes" to 1234,
            "download_url" to "/api/v1/attachments/att-1",
        ),
        baseUrl = "http://127.0.0.1:8823",
    )
    assertThat(block).isInstanceOf(ContentBlock.FileBlock::class.java)
}
```

If `artifactMapToBlock` is private, follow the existing test style in `TimelineMapperTest.kt` and feed a full timeline item.

- [ ] **Step 2: Write failing ChatViewModel SSE test**

Add a test similar to existing `send_file text_file artifact` tests, but with `kind = "download"`. Expected: it appends/replaces with `ContentBlock.FileBlock`.

- [ ] **Step 3: Run failing Android tests**

Run:

```bash
./gradlew :app:testDebugUnitTest --tests "*TimelineMapperTest*" --tests "*ChatViewModelTest*"
```

Expected: timeline mapper likely fails because unknown kind returns null; ChatViewModel may already fall back to file block, but keep the explicit regression test.

- [ ] **Step 4: Implement Android mapping**

In `TimelineMapper.kt`, map both `text_file` and `download` to `FileBlock`:

```kotlin
"text_file", "download" -> ContentBlock.FileBlock(...)
```

In `ChatViewModel.kt`, make the same explicit branch:

```kotlin
"text_file", "download" -> ContentBlock.FileBlock(...)
```

Keep unknown-kind fallback, but do not rely on it for `download`.

- [ ] **Step 5: Update chat README**

Update `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md` to say file blocks render `text_file` and `download` artifacts.

- [ ] **Step 6: Run Android tests**

Run:

```bash
./gradlew :app:testDebugUnitTest --tests "*TimelineMapperTest*" --tests "*ChatViewModelTest*"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/TimelineMapper.kt ui/mobile-android/app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt ui/mobile-android/app/src/test/java/com/sebastian/android/data/remote/dto/TimelineMapperTest.kt ui/mobile-android/app/src/test/java/com/sebastian/android/viewmodel/ChatViewModelTest.kt ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/README.md
git commit -m "feat(android): 渲染浏览器下载 artifact"
```

---

## Task 3: Add PolicyGate Review Preflight/Enricher

**Files:**
- Modify: `sebastian/core/tool.py`
- Modify: `sebastian/core/protocols.py` if `get_callable_specs()` needs `agent_type`
- Modify: `sebastian/core/agent_loop.py` if tool visibility needs the current agent type during spec generation
- Modify: `sebastian/capabilities/registry.py`
- Modify: `sebastian/permissions/types.py`
- Modify: `sebastian/permissions/gate.py`
- Test: `tests/unit/identity/test_policy_gate.py`
- Test: `tests/unit/core/test_agent_loop.py` or nearest spec-provider test if the visibility signature changes

- [ ] **Step 1: Write failing preflight tests**

Add these cases to the existing `tests/unit/identity/test_policy_gate.py`.

Test one: MODEL_DECIDES review receives enriched input:

```python
async def test_model_decides_review_uses_tool_preflight_metadata():
    async def fake_preflight(inputs, context):
        return ToolReviewPreflight(
            ok=True,
            review_input={**inputs, "current_url": "https://example.com", "title": "Example"},
        )

    # Register a fake MODEL_DECIDES tool with preflight.
    # Fake reviewer records tool_input and returns proceed.
    result = await gate.call("browser_observe", {"max_chars": 4000, "reason": "inspect page"}, ctx)
    assert reviewer.seen_tool_input["current_url"] == "https://example.com"
    assert result.ok is True
```

Test two: preflight can block before reviewer:

```python
async def test_preflight_block_stops_before_reviewer():
    async def fake_preflight(inputs, context):
        return ToolReviewPreflight(ok=False, error="No active browser page. Do not retry automatically.")

    result = await gate.call("browser_observe", {"max_chars": 4000, "reason": "inspect page"}, ctx)
    assert result.ok is False
    assert reviewer.calls == []
```

Test three: preflight metadata never reaches the real tool call:

```python
async def test_preflight_review_input_does_not_pollute_tool_inputs():
    async def fake_preflight(inputs, context):
        return ToolReviewPreflight(
            ok=True,
            review_input={**inputs, "current_url": "https://example.com", "title": "Example"},
        )

    result = await gate.call("browser_observe", {"max_chars": 4000, "reason": "inspect page"}, ctx)
    assert result.ok is True
    assert registry.seen_call_inputs == {"max_chars": 4000}
    assert "current_url" not in registry.seen_call_inputs
    assert "title" not in registry.seen_call_inputs
```

- [ ] **Step 2: Run failing preflight tests**

Run:

```bash
pytest tests/unit/identity/test_policy_gate.py -q
```

Expected: FAIL because no preflight interface exists.

- [ ] **Step 3: Add preflight types**

In `sebastian/permissions/types.py`:

```python
@dataclass
class ToolReviewPreflight:
    ok: bool
    review_input: dict[str, Any] | None = None
    error: str | None = None
```

- [ ] **Step 4: Extend tool registration metadata**

In `sebastian/core/tool.py`, add optional metadata without breaking existing decorators:

```python
ToolReviewPreflightFn = Callable[[dict[str, Any], ToolCallContext], Awaitable[ToolReviewPreflight]]
```

If importing `ToolCallContext` would create a runtime cycle, use `TYPE_CHECKING` and `Any`.

Add a field to `ToolSpec`:

```python
review_preflight: ToolReviewPreflightFn | None
```

`ToolSpec` currently uses `__slots__`; add `review_preflight` to `__slots__` at the same time or runtime assignment will fail.

Extend decorator signature:

```python
def tool(..., review_preflight: ToolReviewPreflightFn | None = None) -> Callable[[ToolFn], ToolFn]:
```

Existing tool registrations must continue to work.

- [ ] **Step 4.5: Add Sebastian-only tool visibility metadata**

Browser tools must be hidden from and denied to all non-Sebastian agents, including extension sub-agents whose manifest omits `allowed_tools` and therefore currently gets `allowed_tools=None`.

Add a small metadata field such as:

```python
visible_to_agent_types: frozenset[str] | None = None
```

or a narrower boolean such as:

```python
sebastian_only: bool = False
```

If this metadata lives on `ToolSpec`, update `ToolSpec.__slots__`, constructor, and `@tool(...)` decorator arguments together.

Visibility requirements:

- Spec generation must not expose browser tools when `agent_type != "sebastian"`, even if `allowed_tools is None`.
- `PolicyGate.call()` must also reject browser tool execution when `context.agent_type != "sebastian"`, as a defense against direct/hallucinated calls.
- Sebastian remains the only agent that may see and call browser tools after Task 7 adds them to `Sebastian.allowed_tools`.

Implementation may thread `agent_type` through `ToolSpecProvider.get_callable_specs()` / `PolicyGate.get_callable_specs()` / `AgentLoop`, or use an equivalent explicit deny/visibility hook. Do not implement this as only an Aide/Forge manifest change.

Add tests:

```python
def test_subagent_with_unrestricted_allowed_tools_cannot_see_browser_tools():
    specs = gate.get_callable_specs(allowed_tools=None, allowed_skills=None, agent_type="custom_subagent")
    assert "browser_open" not in {s["name"] for s in specs}

async def test_non_sebastian_context_cannot_call_browser_tool_even_when_allowed_tools_none():
    ctx = ToolCallContext(agent_type="custom_subagent", allowed_tools=None, ...)
    result = await gate.call("browser_open", {"url": "https://example.com", "reason": "browse"}, ctx)
    assert result.ok is False
```

- [ ] **Step 5: Expose preflight through registry**

In `sebastian/capabilities/registry.py`, add:

```python
async def review_preflight(
    self,
    tool_name: str,
    inputs: dict[str, Any],
    context: ToolCallContext,
) -> ToolReviewPreflight | None:
    native = get_tool(tool_name)
    if native is None:
        return None
    spec, _ = native
    if spec.review_preflight is None:
        return None
    return await spec.review_preflight(inputs, context)
```

- [ ] **Step 6: Use preflight in PolicyGate**

In `PolicyGate._handle_model_decides()`:

```python
execution_inputs = dict(inputs)
reason = execution_inputs.pop("reason", None)

preflight = await self._registry.review_preflight(tool_name, execution_inputs, context)
review_input = dict(execution_inputs)
if preflight is not None:
    if not preflight.ok:
        return ToolResult(ok=False, error=preflight.error or "Tool preflight blocked.")
    if preflight.review_input is not None:
        review_input = preflight.review_input

decision = await self._reviewer.review(
    tool_name=tool_name,
    tool_input=review_input,
    reason=reason,
    task_goal=context.task_goal,
)
```

When calling the actual tool after approval, pass only `execution_inputs`, not `review_input`. `PolicyGate.call()` currently mutates `inputs` for `reason` removal and path normalization; keep reviewer enrichment on a separate copy so dynamic metadata such as `current_url` and `title` cannot become unexpected tool parameters.

- [ ] **Step 7: Run permission tests**

Run:

```bash
pytest tests/unit/identity/test_policy_gate.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add sebastian/core/tool.py sebastian/capabilities/registry.py sebastian/permissions/types.py sebastian/permissions/gate.py tests/unit/identity/test_policy_gate.py
git commit -m "feat(permissions): 支持工具审查 preflight 元数据"
```

---

## Task 4: Add Browser Config, Data Directories, And Runtime Lifecycle

**Files:**
- Modify: `pyproject.toml`
- Modify: `sebastian/config/__init__.py`
- Modify: `.env.example`
- Modify: `sebastian/config/README.md`
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`
- Create: `sebastian/capabilities/tools/browser/manager.py`
- Test: `tests/unit/runtime/test_config.py`
- Test: `tests/unit/capabilities/browser/test_browser_manager.py`
- Test: `tests/unit/gateway/test_browser_lifecycle.py` if gateway lifespan tests exist; otherwise use manager unit tests and a lightweight app test.

- [ ] **Step 1: Write failing config tests**

Add tests for browser defaults and directories:

```python
def test_browser_settings_defaults(monkeypatch):
    settings = Settings()
    assert settings.sebastian_browser_headless is True
    assert settings.sebastian_browser_timeout_ms == 30000
    assert settings.browser_profile_dir == settings.user_data_dir / "browser" / "profile"
```

- [ ] **Step 2: Run failing config tests**

Run:

```bash
pytest tests/unit/runtime/test_config.py -q
```

Expected: FAIL because settings do not exist.

- [ ] **Step 3: Add Playwright dependency**

In `pyproject.toml` dependencies:

```toml
"playwright>=1.45",
```

Do not install Chromium in Python package install hooks. Deployment docs handle `python -m playwright install chromium`.

- [ ] **Step 4: Add Settings fields and dirs**

In `sebastian/config/__init__.py`:

```python
sebastian_browser_headless: bool = True
sebastian_browser_viewport: str = "1280x900"
sebastian_browser_timeout_ms: int = 30000

@property
def browser_dir(self) -> Path:
    return self.user_data_dir / "browser"

@property
def browser_profile_dir(self) -> Path:
    return self.browser_dir / "profile"

@property
def browser_downloads_dir(self) -> Path:
    return self.browser_dir / "downloads"

@property
def browser_screenshots_dir(self) -> Path:
    return self.browser_dir / "screenshots"
```

Add these dirs to `ensure_data_dir()`.

- [ ] **Step 5: Create BrowserSessionManager skeleton**

In `sebastian/capabilities/tools/browser/manager.py`, implement a small skeleton first:

```python
class BrowserSessionManager:
    def __init__(self, *, settings: Settings = settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._playwright = None
        self._context = None
        self._page = None

    async def aclose(self) -> None:
        ...

    async def current_page_metadata(self) -> BrowserPageMetadata | None:
        ...
```

Do not wire Playwright page operations yet; this task is lifecycle only.

- [ ] **Step 6: Wire gateway state and shutdown**

In `sebastian/gateway/state.py`:

```python
if TYPE_CHECKING:
    from sebastian.capabilities.tools.browser.manager import BrowserSessionManager

browser_manager: BrowserSessionManager | None = None
```

In `sebastian/gateway/app.py` lifespan:

```python
from sebastian.capabilities.tools.browser.manager import BrowserSessionManager
state.browser_manager = BrowserSessionManager()
...
if state.browser_manager is not None:
    await state.browser_manager.aclose()
    state.browser_manager = None
```

Ensure this happens before DB disposal.

- [ ] **Step 7: Update env/docs**

Update `.env.example`:

```env
SEBASTIAN_BROWSER_HEADLESS=true
SEBASTIAN_BROWSER_VIEWPORT=1280x900
SEBASTIAN_BROWSER_TIMEOUT_MS=30000
```

Update `sebastian/config/README.md`.

- [ ] **Step 8: Run focused tests**

Run:

```bash
pytest tests/unit/runtime/test_config.py tests/unit/capabilities/browser/test_browser_manager.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml sebastian/config/__init__.py .env.example sebastian/config/README.md sebastian/gateway/state.py sebastian/gateway/app.py sebastian/capabilities/tools/browser/manager.py tests/unit/capabilities/browser/test_browser_manager.py
git commit -m "feat(browser): 添加运行配置与生命周期管理"
```

---

## Task 5: Implement Browser Safety And Hard Egress Guard

**Files:**
- Create: `sebastian/capabilities/tools/browser/safety.py`
- Create: `sebastian/capabilities/tools/browser/network.py`
- Create: `sebastian/capabilities/tools/browser/proxy.py`
- Test: `tests/unit/capabilities/browser/test_browser_safety.py`
- Test: `tests/unit/capabilities/browser/test_browser_network.py`
- Test: `tests/integration/test_browser_proxy_egress.py`

**Important implementation choice:** This task is a standalone PR before any public browser tool ships. This plan chooses the local filtering proxy path. Do not ship app-layer DNS checks alone. If the proxy becomes too large for v1, stop and ask the owner whether to replace it with an OS/container firewall or explicitly downgrade the DNS rebinding acceptance criterion.

- [ ] **Step 0: Choose the concrete proxy implementation**

Before writing proxy code, decide and document whether v1 uses a small in-repo asyncio proxy or a mature dependency.

Selection criteria:

- Supports HTTP absolute-form proxy requests.
- Supports HTTPS `CONNECT` tunneling.
- Supports WebSocket traffic: `ws://` via HTTP Upgrade and `wss://` via `CONNECT`.
- Allows connection-time DNS resolution and blocking before opening upstream sockets.
- Can be forced as Chromium's only HTTP/HTTPS proxy with no bypass list.
- Has a small enough dependency and security-maintenance surface for Sebastian's self-hosted install story.
- Is testable without real Chromium for the hard egress tests.

If a dependency is chosen, add it to `pyproject.toml` in this task and explain why in the PR body. If neither option can satisfy the hard boundary within v1 scope, stop and ask the owner; do not merge browser tools with only resolver checks.

- [ ] **Step 1: Write URL safety tests**

Test blocked protocols and addresses:

```python
@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "chrome://settings",
    "about:blank",
    "data:text/html,hi",
    "javascript:alert(1)",
    "http://127.0.0.1:8000",
    "http://[::1]:8000",
    "http://169.254.169.254/latest/meta-data",
    "http://192.168.1.10",
])
def test_url_guard_blocks_high_risk_targets(url):
    with pytest.raises(BrowserSafetyError):
        validate_public_http_url(url)
```

Test allowed public URL:

```python
def test_url_guard_allows_public_https_url():
    parsed = validate_public_http_url("https://example.com/path")
    assert parsed.hostname == "example.com"
```

- [ ] **Step 2: Write DNS resolver tests**

Use a fake resolver returning A/AAAA answers:

```python
async def test_resolver_rejects_private_answer():
    resolver = BrowserDNSResolver(resolve=lambda host: ["10.0.0.5"])
    with pytest.raises(BrowserSafetyError):
        await resolver.resolve_public("safe-looking.example")
```

Include IPv6, CNAME-to-private, NXDOMAIN/error blocks, and empty answer blocks.

- [ ] **Step 3: Write hard egress unit tests**

Write tests against the proxy's connection decision function:

```python
async def test_proxy_blocks_rebinding_at_connect_time():
    proxy = FilteringProxy(resolver=FakeResolver({"evil.test": ["127.0.0.1"]}))
    decision = await proxy.check_connect("evil.test", 80)
    assert decision.allowed is False
```

Also test subresource blocking by calling the same decision path with a URL from a routed request.

Also test redirect/final URL blocking:

```python
async def test_browser_open_blocks_redirect_to_forbidden_final_url(fake_page):
    fake_page.goto_result_url = "http://127.0.0.1:8823/private"
    result = await manager.open("https://public.example/redirects-to-localhost")
    assert result.ok is False
    assert "blocked" in result.error.lower()
```

This can be implemented as a manager-level fake page test in Task 6 if the browser manager owns navigation. The required behavior is still part of the safety contract: validate before navigation, validate resolved destinations through the proxy, and validate the final URL after redirects.

- [ ] **Step 4: Write proxy integration test**

Create `tests/integration/test_browser_proxy_egress.py`. This should run by default if it does not require real Chromium; if it does require Chromium, gate it behind `SEBASTIAN_RUN_PLAYWRIGHT_TESTS=1`.

Test with the concrete local proxy implementation:

1. Start a local HTTP server on `127.0.0.1` that records whether it received a request.
2. Configure fake DNS/resolver so `evil.test` resolves to `127.0.0.1` at proxy connection time.
3. Send a proxied browser/proxy request for `http://evil.test:<port>/secret`.
4. Assert the proxy returns/raises a blocked result.
5. Assert the local HTTP server recorded no upstream request.

Add a subresource variant:

1. Serve a public-looking page that includes an image/script URL pointing at `evil.test`.
2. Route that subresource request through the proxy decision path.
3. Assert the forbidden upstream is blocked before connection.

Add a redirect variant:

1. Serve a public-looking URL that returns `302 Location: http://127.0.0.1:<port>/secret` or the metadata address.
2. Run the navigation path through the manager/browser proxy.
3. Assert the navigation is blocked and the forbidden upstream server recorded no request.

Add a WebSocket/CONNECT variant:

1. Start a local server that would record a `CONNECT` tunnel or WebSocket upgrade if reached.
2. Configure `evil.test` to resolve to loopback at connection time.
3. Send both an HTTPS `CONNECT evil.test:<port>` request and a `ws://evil.test:<port>` proxy request through the proxy.
4. Assert both are blocked and the upstream server recorded no connection/request.

This test is what proves the hard egress boundary. Resolver-only tests are not enough.

- [ ] **Step 5: Run failing tests**

Run:

```bash
pytest tests/unit/capabilities/browser/test_browser_safety.py tests/unit/capabilities/browser/test_browser_network.py tests/integration/test_browser_proxy_egress.py -q
```

Expected: FAIL because modules do not exist.

- [ ] **Step 6: Implement safety module**

Implement:

```python
class BrowserSafetyError(ValueError):
    pass

def validate_public_http_url(url: str) -> ParsedURL:
    ...

def is_forbidden_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
        or addr in ipaddress.ip_network("169.254.169.254/32")
    )
```

Use `urllib.parse.urlparse` plus IDNA normalization. Reject URLs with username/password in authority.

- [ ] **Step 7: Implement concrete local filtering proxy**

Implement resolver and hard-boundary interfaces in `network.py`, and implement a concrete local filtering proxy in `proxy.py`.

Minimum proxy requirements:

- Accept HTTP absolute-form proxy requests.
- Accept HTTPS `CONNECT` tunnel requests and apply the guard before dialing upstream.
- Accept or explicitly block WebSocket proxy traffic; `ws://` and `wss://` must not bypass the guard.
- Resolve the upstream host at connection time.
- Block forbidden destination IPs before opening an upstream socket.
- Prevent normal browser traffic from bypassing the proxy when launched by `BrowserSessionManager`; configure Playwright/Chromium with the proxy server, an empty bypass list, and any required launch flags so direct HTTP/HTTPS fallback is not possible.
- Return deterministic blocked errors for forbidden destinations.
- Include integration coverage that proves a forbidden upstream service receives zero requests/connections for top-level navigation, subresources, HTTPS `CONNECT`, and WebSocket paths.
- Expose enough lifecycle API for manager startup/shutdown:

```python
class FilteringProxy:
    async def start(self) -> ProxyConfig: ...
    async def aclose(self) -> None: ...
    async def check_connect(self, host: str, port: int) -> ProxyDecision: ...
```

- [ ] **Step 8: Run tests**

Run:

```bash
pytest tests/unit/capabilities/browser/test_browser_safety.py tests/unit/capabilities/browser/test_browser_network.py tests/integration/test_browser_proxy_egress.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add sebastian/capabilities/tools/browser/safety.py sebastian/capabilities/tools/browser/network.py sebastian/capabilities/tools/browser/proxy.py tests/unit/capabilities/browser/test_browser_safety.py tests/unit/capabilities/browser/test_browser_network.py tests/integration/test_browser_proxy_egress.py
git commit -m "feat(browser): 添加 URL 与出站网络安全边界"
```

---

## Task 6: Implement Browser Manager With Playwright

**Files:**
- Modify: `sebastian/capabilities/tools/browser/manager.py`
- Modify: `sebastian/capabilities/tools/browser/network.py`
- Test: `tests/unit/capabilities/browser/test_browser_manager.py`
- Optional integration: `tests/integration/test_browser_playwright.py`

- [ ] **Step 1: Write failing manager tests using fakes**

Test lazy launch:

```python
async def test_manager_launches_persistent_context_with_profile_dir(fake_playwright, tmp_settings):
    manager = BrowserSessionManager(settings=tmp_settings, playwright_factory=fake_playwright)
    await manager.open("https://example.com")
    assert fake_playwright.chromium.launch_persistent_context_called_with.user_data_dir == tmp_settings.browser_profile_dir
```

Test shutdown closes resources in order:

```python
async def test_manager_aclose_closes_context_and_playwright(fake_playwright):
    manager = ...
    await manager.open("https://example.com")
    await manager.aclose()
    assert fake_context.closed
    assert fake_playwright.stopped
```

Test redirect/final URL validation if not already covered in Task 5 with manager fakes:

```python
async def test_open_rejects_forbidden_final_url_after_redirect(fake_playwright, tmp_settings):
    fake_page.goto_final_url = "http://169.254.169.254/latest/meta-data"
    manager = BrowserSessionManager(settings=tmp_settings, playwright_factory=fake_playwright)
    result = await manager.open("https://public.example/redirect")
    assert result.ok is False
    assert "blocked" in result.error.lower()
```

- [ ] **Step 2: Run failing manager tests**

Run:

```bash
pytest tests/unit/capabilities/browser/test_browser_manager.py -q
```

Expected: FAIL for missing methods.

- [ ] **Step 3: Implement lazy Playwright launch**

Use async Playwright:

```python
from playwright.async_api import async_playwright, BrowserContext, Page

async def _ensure_context(self) -> BrowserContext:
    if self._context is not None:
        return self._context
    self._settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    self._settings.browser_downloads_dir.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    self._playwright = pw
    self._context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(self._settings.browser_profile_dir),
        headless=self._settings.sebastian_browser_headless,
        viewport=self._parse_viewport(),
        accept_downloads=True,
        downloads_path=str(self._settings.browser_downloads_dir),
        timeout=self._settings.sebastian_browser_timeout_ms,
        proxy=self._filtering_proxy.playwright_proxy_config(),
    )
    return self._context
```

Start the filtering proxy before launching Chromium. Browser launch args/config must prevent proxy bypass for normal HTTP/HTTPS traffic. If the filtering proxy cannot start, or if the manager cannot prove the proxy config is active, browser tools must fail closed. Do not add a temporary "direct network" mode for v1.

- [ ] **Step 4: Implement current page operations**

Methods:

```python
async def open(self, url: str) -> BrowserOpenResult
async def current_page_metadata(self) -> BrowserPageMetadata | None
async def page(self) -> Page
async def aclose(self) -> None
```

Track whether the page was opened by browser tools:

```python
self._current_page_owned_by_browser_tool = True
```

`open()` must validate the requested URL before navigation and validate the final `page.url` after `goto()`/redirects before marking the page as owned/current. If the final URL is forbidden, clear owned/current state for that page and return a blocked result.

- [ ] **Step 5: Add deterministic Playwright install errors**

Catch common Playwright errors for missing browser executable and missing Linux deps. Return later via tool wrappers as:

- `Ask the user to run: python -m playwright install chromium`
- `Ask the user to run: python -m playwright install-deps chromium`

- [ ] **Step 6: Add optional integration test**

Create `tests/integration/test_browser_playwright.py`, skipped unless `SEBASTIAN_RUN_PLAYWRIGHT_TESTS=1`.

Use a temporary HTTP server and mark it test-authorized. Verify open/title/screenshot non-empty. Do not require this in normal CI.

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/unit/capabilities/browser/test_browser_manager.py -q
```

Optional local:

```bash
SEBASTIAN_RUN_PLAYWRIGHT_TESTS=1 pytest tests/integration/test_browser_playwright.py tests/integration/test_browser_proxy_egress.py -q
```

- [ ] **Step 8: Commit**

```bash
git add sebastian/capabilities/tools/browser/manager.py sebastian/capabilities/tools/browser/network.py tests/unit/capabilities/browser/test_browser_manager.py tests/integration/test_browser_playwright.py
git commit -m "feat(browser): 接入 Playwright 持久浏览器会话"
```

---

## Task 7: Implement Browser Observation, Actions, Screenshots, And Downloads

**Files:**
- Create: `sebastian/capabilities/tools/browser/__init__.py`
- Create: `sebastian/capabilities/tools/browser/observe.py`
- Create: `sebastian/capabilities/tools/browser/downloads.py`
- Create: `sebastian/capabilities/tools/browser/artifacts.py`
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/capabilities/README.md`
- Test: `tests/unit/capabilities/browser/test_browser_tools.py`
- Test: `tests/unit/capabilities/browser/test_browser_observe.py`
- Test: `tests/unit/capabilities/browser/test_browser_downloads.py`

- [ ] **Step 1: Write failing tool visibility test**

Assert Sebastian includes browser tools and Forge/Aide manifests do not:

```python
def test_sebastian_allows_browser_tools():
    assert "browser_open" in Sebastian.allowed_tools
    assert "browser_observe" in Sebastian.allowed_tools
```

- [ ] **Step 2: Write failing observe privacy tests**

Use fake page HTML/accessibility data:

```python
async def test_observe_omits_password_and_hidden_values(fake_page):
    fake_page.set_content("""
        <input type="password" value="secret">
        <input type="hidden" value="csrf">
        <button>Submit</button>
    """)
    observed = await observe_page(fake_page)
    assert "secret" not in observed.text
    assert "csrf" not in observed.text
    assert "Submit" in observed.interactive_summary
```

- [ ] **Step 3: Write failing action validation tests**

Test unknown action and missing params:

```python
async def test_browser_act_rejects_unknown_action():
    result = await browser_act("drag", target="#x")
    assert result.ok is False
    assert "Unknown browser action" in result.error
```

Test high-impact block:

```python
async def test_browser_act_blocks_password_type(fake_manager):
    fake_manager.target_metadata = TargetMetadata(input_type="password")
    result = await browser_act("type", target="#password", value="secret")
    assert result.ok is False
    assert "blocked" in result.error.lower()
```

- [ ] **Step 4: Write failing download tests**

Test traversal block:

```python
def test_download_send_rejects_path_escape(tmp_path):
    with pytest.raises(BrowserSafetyError):
        resolve_download_path("../secret.txt", downloads_dir=tmp_path)
```

Test generic artifact send calls AttachmentStore with `kind="download"`.

Test Playwright download recording:

```python
async def test_manager_records_download_with_sanitized_unique_filename(fake_download, tmp_settings):
    fake_download.suggested_filename = "../report\x00.pdf"
    record = await manager.save_download(fake_download)
    assert record.filename == "report.pdf"
    assert record.path.parent == tmp_settings.browser_downloads_dir
    assert (tmp_settings.browser_downloads_dir / "downloads.jsonl").exists()
```

Also test duplicate names produce `report-1.pdf` or an equivalent deterministic suffix and never overwrite an existing file.

Test browser artifact helpers use the active tool context:

```python
async def test_download_send_binds_attachment_to_session(fake_tool_context, fake_attachment_store):
    await send_browser_download("report.pdf")
    assert fake_attachment_store.mark_agent_sent_called_with == (
        fake_tool_context.session_id,
        fake_tool_context.agent_type,
    )
```

- [ ] **Step 5: Run failing tests**

Run:

```bash
pytest tests/unit/capabilities/browser -q
```

Expected: FAIL until tools are implemented.

- [ ] **Step 6: Implement browser tools**

In `__init__.py`, register:

```python
@tool(name="browser_open", description=..., permission_tier=PermissionTier.MODEL_DECIDES, sebastian_only=True)
async def browser_open(url: str) -> ToolResult: ...

@tool(
    name="browser_observe",
    description=...,
    permission_tier=PermissionTier.MODEL_DECIDES,
    review_preflight=browser_observe_review_preflight,
    sebastian_only=True,
)
async def browser_observe(max_chars: int = 4000) -> ToolResult: ...
```

Also implement `browser_act`, `browser_capture`, and `browser_downloads` with the same Sebastian-only metadata.

Use `sebastian.gateway.state.browser_manager` as the runtime manager. If missing:

```python
return ToolResult(ok=False, error="Browser service is unavailable. Do not retry automatically; tell the user browser tools are unavailable.")
```

- [ ] **Step 7: Implement observe preflight**

The preflight must only return sanitized metadata:

```python
async def browser_observe_review_preflight(inputs, context):
    manager = _get_manager()
    metadata = await manager.current_page_metadata()
    if metadata is None or not metadata.opened_by_browser_tool:
        return ToolReviewPreflight(
            ok=False,
            error="No active browser page opened by browser tools. Do not retry automatically; open a page first.",
        )
    return ToolReviewPreflight(
        ok=True,
        review_input={
            **inputs,
            "current_url": metadata.url,
            "title": metadata.title,
            "opened_by_browser_tool": True,
        },
    )
```

- [ ] **Step 8: Implement `browser_capture` artifact**

Capture to `settings.browser_screenshots_dir`, upload as image artifact, then delete temp file or TTL-clean it. The helper must use `get_tool_context()` the same way `send_file_path` does, so the AttachmentStore can call `mark_agent_sent(session_id, agent_type)` and the artifact is correctly attached to session/timeline state.

Model-facing output:

```python
ToolResult(
    ok=True,
    display=f"已发送浏览器截图 {filename}",
    output={"artifact": artifact, "url": metadata.url, "filename": filename},
)
```

Do not include image bytes.

- [ ] **Step 9: Implement Playwright download saving**

Hook Playwright downloads before exposing `browser_downloads`:

- Configure the context with `accept_downloads=True` and `downloads_path=settings.browser_downloads_dir`.
- Attach `page.on("download", ...)` for every managed page; if using `context.on("page", ...)`, register the page-level download handler as pages are created. The handler calls a manager method such as `save_download(download)`.
- For click/press actions that may trigger a download, record any download completed during or immediately after the action and include a concise note in the tool result.
- Use `download.suggested_filename` only after sanitization:
  - Keep only `Path(name).name`.
  - Strip control characters, NUL, path separators, leading dots, and shell-hostile whitespace.
  - Normalize to a safe fallback such as `download-YYYYMMDD-HHMMSS.bin` when the name becomes empty.
  - Preserve a safe extension when possible.
  - Avoid overwrite by adding a deterministic suffix such as `-1`, `-2`.
- Save with `download.save_as(final_path)`.
- Maintain a small manifest such as `downloads.jsonl` in the browser downloads directory with filename, path, MIME guess, size, mtime, original suggested filename, source URL if available, and created time. `browser_downloads(list)` should use this manifest and may reconcile missing files.

- [ ] **Step 10: Implement `browser_downloads`**

Actions:

- `list`: return filenames, sizes, mtime, MIME guess.
- `send`: upload selected file as `kind="download"` and emit artifact.

No path traversal. No arbitrary absolute paths. `send` must use the browser artifact helper, `get_tool_context()`, and the same `ToolResult.output["artifact"]` contract as `send_file_path`; it must not read or send arbitrary files outside `settings.browser_downloads_dir`.

- [ ] **Step 11: Update Sebastian allowed tools**

In `sebastian/orchestrator/sebas.py`, add:

```python
"browser_open",
"browser_observe",
"browser_act",
"browser_capture",
"browser_downloads",
```

Do not add them to sub-agent manifests.

Add focused visibility tests at this point with the real browser tool specs registered:

- Sebastian sees `browser_open` when `Sebastian.allowed_tools` includes it.
- A custom/extension sub-agent with `allowed_tools=None` does not see any `browser_*` specs.
- A non-Sebastian `ToolCallContext` cannot execute `browser_open` even if it calls the tool name directly.

- [ ] **Step 12: Update capabilities docs**

Update:

- `sebastian/capabilities/README.md`
- `sebastian/capabilities/tools/README.md`

Mention the new `browser/` tool package and Sebastian-only availability.

- [ ] **Step 13: Run focused tests**

Run:

```bash
pytest tests/unit/capabilities/browser tests/unit/identity/test_policy_gate.py -q
```

Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add sebastian/capabilities/tools/browser/__init__.py sebastian/capabilities/tools/browser/observe.py sebastian/capabilities/tools/browser/downloads.py sebastian/capabilities/tools/browser/artifacts.py sebastian/orchestrator/sebas.py sebastian/capabilities/README.md sebastian/capabilities/tools/README.md tests/unit/capabilities/browser/test_browser_tools.py tests/unit/capabilities/browser/test_browser_observe.py tests/unit/capabilities/browser/test_browser_downloads.py
git commit -m "feat(browser): 添加 Sebastian 内置浏览器工具"
```

---

## Task 8: Deployment Docs, CHANGELOG, And Full Verification

**Files:**
- Modify: `docs/AGENTIC_DEPLOYMENT.md`
- Modify: `README.md`
- Modify: `sebastian/gateway/README.md`
- Modify: `sebastian/gateway/routes/README.md`
- Modify: `ui/mobile-android/README.md`
- Modify: `CHANGELOG.md`
- Test/verify: backend + Android focused checks

- [ ] **Step 1: Update deployment docs**

In `docs/AGENTIC_DEPLOYMENT.md`, add Playwright browser setup:

```bash
python -m playwright install chromium
```

For Ubuntu system dependencies:

```bash
python -m playwright install-deps chromium
```

State clearly: `install-deps` may require sudo, so local Agents should hand it to the user for approval/execution.

Add failure guidance for Chromium download issues, especially mainland China network conditions.

- [ ] **Step 2: Update root README quick start if needed**

If browser tools affect Quick Start or Agent prompt, add a short note that Sebastian now installs Playwright as a runtime dependency but Chromium runtime still needs the Playwright install command.

- [ ] **Step 3: Update gateway/routes docs**

Document new `download` artifact kind under attachments and timeline/SSE artifact payloads.

- [ ] **Step 4: Update CHANGELOG**

Under `[Unreleased]`:

```markdown
### Added
- 新增 Sebastian 内置浏览器工具设计与运行依赖，支持 Playwright Chromium 的网页打开、观察、操作、截图和下载 artifact。

### Changed
- 附件 artifact 支持通用下载文件，Android 可渲染浏览器下载结果。
```

Adjust wording to match the actual implementation PR scope if splitting PRs.

- [ ] **Step 5: Run backend focused tests**

Run:

```bash
pytest tests/unit/capabilities/browser tests/unit/identity/test_policy_gate.py tests/unit/store/test_attachments.py -q
```

Expected: PASS.

- [ ] **Step 6: Run backend lint/type checks**

Run:

```bash
ruff check sebastian/ tests/
mypy sebastian/
```

Expected: PASS.

- [ ] **Step 7: Run Android focused tests**

Run:

```bash
./gradlew :app:testDebugUnitTest --tests "*TimelineMapperTest*" --tests "*ChatViewModelTest*"
```

Expected: PASS.

- [ ] **Step 8: Optional Playwright integration**

On a machine with Chromium installed:

```bash
python -m playwright install chromium
SEBASTIAN_RUN_PLAYWRIGHT_TESTS=1 pytest tests/integration/test_browser_playwright.py -q
```

Expected: PASS. If Chromium/system deps are unavailable in CI, this test remains skipped by default.

- [ ] **Step 9: Rebuild graphify after code changes**

Run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: graph rebuild completes without errors.

- [ ] **Step 10: Commit**

```bash
git add docs/AGENTIC_DEPLOYMENT.md README.md sebastian/gateway/README.md sebastian/gateway/routes/README.md ui/mobile-android/README.md CHANGELOG.md graphify-out
git commit -m "docs(browser): 补充浏览器工具部署与验证说明"
```

---

## Final Verification Before PR

- [ ] Run backend targeted tests:

```bash
pytest tests/unit/capabilities/browser tests/unit/identity/test_policy_gate.py tests/unit/store/test_attachments.py tests/unit/core/test_stream_helpers.py -q
```

- [ ] Run backend lint:

```bash
ruff check sebastian/ tests/
```

- [ ] Run type check:

```bash
mypy sebastian/
```

- [ ] Run Android artifact tests:

```bash
./gradlew :app:testDebugUnitTest --tests "*TimelineMapperTest*" --tests "*ChatViewModelTest*"
```

- [ ] Confirm browser tools are only in Sebastian's `allowed_tools`, not Aide/Forge.

- [ ] Confirm hard egress tests prove a forbidden upstream server receives no request when DNS resolves to loopback/private/link-local/metadata destinations.

- [ ] Confirm generic binary artifact payload survives backend live SSE and persisted timeline before Android rendering.

- [ ] Confirm no tool result returns screenshot bytes, password field values, hidden input values, or arbitrary downloaded file paths.

- [ ] Confirm `git status --short` only shows intentional generated graph/doc changes before final commit.

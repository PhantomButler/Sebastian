# Screenshot And Send Tool Design

## 1. Goal

Add a native tool that captures a screenshot on the machine running the Sebastian backend and sends it to the current conversation as an image attachment.

This tool is for the backend host screen. It does not capture the Android device screen. Mobile device screenshots require a separate Android-side permission and capture flow.

## 2. Scope

P0 supports:

- Full-screen screenshot only.
- macOS and Linux backend hosts.
- Sending the captured PNG through the existing `send_file` attachment pipeline.
- Exposing the tool only to the Sebastian top-level orchestrator.
- Clear deterministic failures when the current host cannot capture the screen.

P0 does not support:

- Region capture.
- Window selection.
- Multi-monitor selection.
- Android device screen capture.
- Browser-only screenshot capture.
- Sub-agent access.

## 3. Tool Shape

Add a new native tool:

- Path: `sebastian/capabilities/tools/screenshot_send/__init__.py`
- Tool name: `capture_screenshot_and_send`
- Permission tier: `PermissionTier.HIGH_RISK`
- Exposure: Sebastian only. Add it to `sebastian/orchestrator/sebas.py` and do not add it to sub-agent `manifest.toml` files.

Suggested signature:

```python
async def capture_screenshot_and_send(
    display_name: str | None = None,
) -> ToolResult:
    ...
```

The default filename should be timestamped, for example:

```text
screenshot-20260429-153012.png
```

If `display_name` is provided without a suffix, the tool appends `.png`.

## 4. Permission Model

Screenshots can expose credentials, private messages, API keys, browser tabs, and local files. Unlike sending an existing user-specified file, this tool actively reads the visible desktop state.

Therefore `capture_screenshot_and_send` should use `PermissionTier.HIGH_RISK`, forcing explicit user approval for every call.

The approval copy should make it clear that the screenshot is captured from the backend host screen, not from the phone.

## 5. Temporary File Location

Screenshots are intermediate runtime artifacts. Store them under the Sebastian data directory:

```text
<SEBASTIAN_DATA_DIR>/tmp/screenshots/
```

With the default layout this is:

```text
~/.sebastian/data/tmp/screenshots/
```

The tool must not write screenshots into:

- The repository workspace.
- The system `/tmp` as the primary location.
- The attachment blob directory directly.

Rationale:

- The workspace should not receive private runtime screenshots or git-visible files.
- `/tmp` behavior differs across service managers and can be cleaned unexpectedly.
- The attachment store should own the durable user-visible copy; the screenshot file is only an upload source.

Lifecycle:

```text
create data/tmp/screenshots/
  -> optionally delete old screenshot temp files owned by this tool
  -> capture PNG into data/tmp/screenshots/
  -> upload/send through send_file helper
  -> delete the temp PNG in finally
```

Normal operation should leave the directory empty. A conservative cleanup of files older than 24 hours is acceptable before each capture.

## 6. Reusing `send_file`

The screenshot tool should not duplicate attachment upload, artifact shaping, thumbnail URLs, session binding, or SSE behavior.

Refactor `send_file` into an internal helper:

```python
async def send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
    ...
```

Then keep the public tool as a thin wrapper:

```python
@tool(name="send_file", ...)
async def send_file(file_path: str, display_name: str | None = None) -> ToolResult:
    return await send_file_path(file_path, display_name)
```

`capture_screenshot_and_send` should call this helper after writing the PNG:

```python
return await send_file_path(str(screenshot_path), display_name=filename)
```

The returned result remains the existing image artifact shape:

```json
{
  "artifact": {
    "kind": "image",
    "attachment_id": "att-123",
    "filename": "screenshot-20260429-153012.png",
    "mime_type": "image/png",
    "size_bytes": 12345,
    "download_url": "/api/v1/attachments/att-123",
    "thumbnail_url": "/api/v1/attachments/att-123/thumbnail"
  }
}
```

Android rendering, SSE realtime replacement, and timeline hydration should require no new UI behavior because this is still a normal image artifact.

## 7. Platform Backends

### 7.1 macOS

Use the system `screencapture` command:

```bash
/usr/sbin/screencapture -x <output.png>
```

Behavior:

- `-x` suppresses the camera sound.
- The command writes PNG directly.
- If macOS Screen Recording permission is missing, return a deterministic failure explaining that the user must grant Screen Recording permission to the process running Sebastian.

Do not attempt to bypass macOS privacy controls.

### 7.2 Linux

Linux support must detect the graphical session and available backend explicitly.

If neither `DISPLAY` nor `WAYLAND_DISPLAY` is present, fail with a clear headless-session error.

For X11:

1. Prefer `gnome-screenshot -f <output.png>` when available.
2. Fall back to `scrot <output.png>` when available.
3. If neither exists, fail and suggest installing one of them.

For Wayland:

1. Prefer `grim <output.png>` when available.
2. If unavailable, fail with a clear message that the current Wayland desktop has no supported screenshot backend.

P0 should not implement DBus portal capture. Portal support can be added later if GNOME/KDE Wayland support becomes a priority.

## 8. Error Handling

All deterministic failures must return `ToolResult(ok=False, error=...)`, not successful output.

Errors should include the reason and a next step, and should tell the model not to retry automatically with the same input.

Examples:

- `Screen capture permission is not granted on macOS. Do not retry automatically; ask the user to grant Screen Recording permission to the process running Sebastian.`
- `Linux screenshot requires a graphical session; DISPLAY/WAYLAND_DISPLAY is missing. Do not retry automatically; tell the user screenshots are unavailable in this headless session.`
- `No supported Linux screenshot backend found. Do not retry automatically; ask the user to install gnome-screenshot, scrot, or grim for their desktop session.`
- `Screenshot command failed: <stderr>. Do not retry automatically; tell the user the screen could not be captured.`
- `Screenshot was captured but could not be sent: <send_file error>. Do not retry automatically; tell the user the screenshot could not be attached.`

Temporary file deletion failures should be logged but should not change the result after a successful upload.

## 9. Implementation Notes

Use `asyncio.to_thread(subprocess.run, ...)` for screenshot commands so the event loop is not blocked.

Do not use `asyncio.create_subprocess_exec` in async tests because the project guidelines call out Linux event-loop cleanup hangs with subprocess watchers.

Command execution should avoid shell parsing. Use argument lists:

```python
subprocess.run(
    ["/usr/sbin/screencapture", "-x", str(output_path)],
    check=False,
    capture_output=True,
    text=True,
)
```

Use `shutil.which()` for Linux backend discovery.

## 10. Tests

Backend unit tests should cover:

- macOS backend builds the expected `screencapture` command.
- Linux X11 prefers `gnome-screenshot`.
- Linux X11 falls back to `scrot`.
- Linux Wayland uses `grim`.
- Headless Linux returns a deterministic error.
- Missing Linux backends return a deterministic error.
- Successful capture calls the shared `send_file_path` helper.
- Temp PNG is deleted after success.
- Temp PNG is deleted after send failure.
- `display_name` without suffix becomes `.png`.
- The tool uses `PermissionTier.HIGH_RISK`.

No Android changes are required for P0 if the returned artifact matches the existing image artifact contract.

## 11. Documentation Updates

When implementing, update:

- `sebastian/capabilities/tools/README.md`
- `sebastian/capabilities/README.md`
- `sebastian/orchestrator/sebas.py` so Sebastian can call `capture_screenshot_and_send`

Do not add `capture_screenshot_and_send` to sub-agent manifests such as `sebastian/agents/forge/manifest.toml` or `sebastian/agents/aide/manifest.toml`. P0 intentionally keeps screenshot capture at the top-level Sebastian boundary only.

## 12. Acceptance Criteria

- On macOS with Screen Recording permission granted, the tool captures the backend host screen and sends it as an image block in the current chat.
- On supported Linux desktop sessions, the tool captures the backend host screen and sends it as an image block in the current chat.
- In headless or unsupported Linux sessions, the tool fails clearly and does not retry automatically.
- Sub-agents cannot call the screenshot tool.
- The temporary screenshot does not remain in the repository workspace.
- Normal successful operation leaves no screenshot temp file behind.
- The LLM-facing tool result remains lightweight and does not include image bytes or local blob paths.

# Screenshot Send Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Sebastian-only tool that captures a full-screen screenshot from the backend host and sends it to the current chat as an image attachment.

**Architecture:** Reuse the existing `send_file` artifact/upload path by extracting an internal `send_file_path()` helper. Add a focused `screenshot_send` native tool that handles platform detection, screenshot command execution, temp-file lifecycle, and then delegates the PNG to `send_file_path()`. Expose the tool only through `Sebastian.allowed_tools`; do not add it to sub-agent manifests.

**Tech Stack:** Python 3.12, native `@tool` registry, `ToolResult`, `PermissionTier.HIGH_RISK`, `subprocess.run` via `asyncio.to_thread`, pytest/pytest-asyncio.

---

## File Map

- Modify `sebastian/capabilities/tools/send_file/__init__.py`
  - Extract `send_file_path(file_path, display_name)` from the existing `send_file` body.
  - Keep public `send_file()` as a thin `@tool` wrapper.
  - Preserve current behavior, errors, display text, artifact shape, and context dependency.
- Create `sebastian/capabilities/tools/screenshot_send/__init__.py`
  - Register `capture_screenshot_and_send`.
  - Implement platform backend selection and capture command execution.
  - Manage `settings.user_data_dir / "tmp" / "screenshots"` temp files.
  - Call `send_file_path()` for the final upload.
- Modify `sebastian/orchestrator/sebas.py`
  - Add `capture_screenshot_and_send` to `Sebastian.allowed_tools`.
- Modify `sebastian/capabilities/tools/README.md`
  - Add `screenshot_send/` to the capability tool tree and navigation.
  - Document Sebastian-only exposure.
- Modify `sebastian/capabilities/README.md`
  - Add `screenshot_send/` to the top-level capability tree.
- Test in `tests/unit/capabilities/test_send_file_tool.py`
  - Add helper regression tests for `send_file_path`.
- Create `tests/unit/capabilities/test_screenshot_send_tool.py`
  - Unit-test platform command selection, failure handling, temp cleanup, permission tier, description, and Sebastian-only exposure.

---

### Task 1: Extract `send_file_path()` Without Behavior Change

**Files:**
- Modify: `sebastian/capabilities/tools/send_file/__init__.py`
- Test: `tests/unit/capabilities/test_send_file_tool.py`

- [ ] **Step 1: Add a failing helper regression test**

Append this test near the existing send_file tests in `tests/unit/capabilities/test_send_file_tool.py`:

```python
@pytest.mark.asyncio
async def test_send_file_path_helper_uploads_image_and_returns_artifact(
    patched_state, set_ctx, tmp_path: Path
) -> None:
    set_ctx("s1", "sebastian")

    file_path = tmp_path / "photo.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)

    from sebastian.capabilities.tools.send_file import send_file_path

    result = await send_file_path(str(file_path), display_name="screen")

    assert result.ok is True
    artifact = result.output["artifact"]
    assert artifact["kind"] == "image"
    assert artifact["filename"] == "screen.png"
    assert artifact["mime_type"] == "image/png"
    assert "thumbnail_url" in artifact
    assert result.display == "已向用户发送图片 screen.png"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py::test_send_file_path_helper_uploads_image_and_returns_artifact -q
```

Expected: fail with `ImportError` or similar because `send_file_path` does not exist yet.

- [ ] **Step 3: Extract the helper**

In `sebastian/capabilities/tools/send_file/__init__.py`, move the current `send_file()` body into:

```python
async def send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
    ctx = get_tool_context()
    if ctx is None or not ctx.session_id:
        return ToolResult(
            ok=False,
            error=(
                "send_file requires session context. Do not retry automatically; "
                "tell the user the file could not be sent in this conversation."
            ),
        )

    # Keep the rest of the current implementation unchanged.
```

Then make the decorated public function a wrapper:

```python
@tool(
    name="send_file",
    description=(
        "Send a file from the server filesystem to the user in this conversation. "
        "Supported types: images (jpg/jpeg/png/webp/gif) and text files (txt/md/csv/json/log). "
        "The file will appear in the chat for the user to view or download. "
        "Use display_name to override the filename shown to the user."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def send_file(file_path: str, display_name: str | None = None) -> ToolResult:
    return await send_file_path(file_path, display_name)
```

Do not change `_resolve_display_name()`, `_detect_kind()`, artifact fields, display strings, or deterministic error wording.

- [ ] **Step 4: Run focused send_file tests**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py -q
```

Expected: all tests in this file pass.

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/send_file/__init__.py tests/unit/capabilities/test_send_file_tool.py
git commit -m "refactor(tools): 提取 send_file 内部发送 helper" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 2: Add Screenshot Backend Selection Tests

**Files:**
- Create: `tests/unit/capabilities/test_screenshot_send_tool.py`
- Create: `sebastian/capabilities/tools/screenshot_send/__init__.py`

- [ ] **Step 1: Create failing tests for platform command selection**

Create `tests/unit/capabilities/test_screenshot_send_tool.py` with these initial tests:

```python
from __future__ import annotations

from pathlib import Path

import pytest


def test_macos_backend_builds_screencapture_command(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    output = tmp_path / "shot.png"

    command = _select_capture_command(
        system="Darwin",
        env={},
        which=lambda name: f"/usr/bin/{name}" if name == "screencapture" else None,
        output_path=output,
    )

    assert command == ["/usr/sbin/screencapture", "-x", str(output)]


def test_linux_x11_prefers_gnome_screenshot(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    output = tmp_path / "shot.png"

    command = _select_capture_command(
        system="Linux",
        env={"DISPLAY": ":0"},
        which=lambda name: f"/usr/bin/{name}" if name in {"gnome-screenshot", "scrot"} else None,
        output_path=output,
    )

    assert command == ["/usr/bin/gnome-screenshot", "-f", str(output)]


def test_linux_x11_falls_back_to_scrot(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    output = tmp_path / "shot.png"

    command = _select_capture_command(
        system="Linux",
        env={"DISPLAY": ":0"},
        which=lambda name: "/usr/bin/scrot" if name == "scrot" else None,
        output_path=output,
    )

    assert command == ["/usr/bin/scrot", str(output)]


def test_linux_wayland_uses_grim(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    output = tmp_path / "shot.png"

    command = _select_capture_command(
        system="Linux",
        env={"WAYLAND_DISPLAY": "wayland-0"},
        which=lambda name: "/usr/bin/grim" if name == "grim" else None,
        output_path=output,
    )

    assert command == ["/usr/bin/grim", str(output)]


def test_linux_wayland_and_x11_prefers_wayland(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    output = tmp_path / "shot.png"

    def which(name: str) -> str | None:
        return {
            "grim": "/usr/bin/grim",
            "gnome-screenshot": "/usr/bin/gnome-screenshot",
            "scrot": "/usr/bin/scrot",
        }.get(name)

    command = _select_capture_command(
        system="Linux",
        env={"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"},
        which=which,
        output_path=output,
    )

    assert command == ["/usr/bin/grim", str(output)]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py -q
```

Expected: fail because `screenshot_send` does not exist yet.

- [ ] **Step 3: Add minimal backend selection implementation**

Create `sebastian/capabilities/tools/screenshot_send/__init__.py` with:

```python
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier


DESCRIPTION = (
    "Capture a screenshot of the backend host machine's screen and send it to the "
    "current conversation. This captures the server desktop, not the Android device screen."
)


def _select_capture_command(
    *,
    system: str,
    env: Mapping[str, str],
    which: Callable[[str], str | None],
    output_path: Path,
) -> list[str]:
    if system == "Darwin":
        return ["/usr/sbin/screencapture", "-x", str(output_path)]

    if system != "Linux":
        raise RuntimeError(
            f"Unsupported screenshot platform: {system}. Do not retry automatically; "
            "tell the user screenshots are only supported on macOS and Linux backend hosts."
        )

    if env.get("WAYLAND_DISPLAY"):
        grim = which("grim")
        if grim:
            return [grim, str(output_path)]
        raise RuntimeError(
            "No supported Linux screenshot backend found for Wayland. Do not retry automatically; "
            "ask the user to install grim or use a supported desktop session."
        )

    if env.get("DISPLAY"):
        gnome_screenshot = which("gnome-screenshot")
        if gnome_screenshot:
            return [gnome_screenshot, "-f", str(output_path)]
        scrot = which("scrot")
        if scrot:
            return [scrot, str(output_path)]
        raise RuntimeError(
            "No supported Linux screenshot backend found. Do not retry automatically; "
            "ask the user to install gnome-screenshot, scrot, or grim for their desktop session."
        )

    raise RuntimeError(
        "Linux screenshot requires a graphical session; DISPLAY/WAYLAND_DISPLAY is missing. "
        "Do not retry automatically; tell the user screenshots are unavailable in this headless session."
    )
```

Do not implement the public tool body yet beyond a placeholder if needed for import stability.

- [ ] **Step 4: Run backend selection tests**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py -q
```

Expected: the five command-selection tests pass.

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/screenshot_send/__init__.py tests/unit/capabilities/test_screenshot_send_tool.py
git commit -m "test(tools): 覆盖截图后端选择规则" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 3: Add Capture Execution, Validation, and Error Tests

**Files:**
- Modify: `tests/unit/capabilities/test_screenshot_send_tool.py`
- Modify: `sebastian/capabilities/tools/screenshot_send/__init__.py`

- [ ] **Step 1: Add failing tests for command execution validation**

Append:

```python
@pytest.mark.asyncio
async def test_capture_command_success_requires_non_empty_output(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _run_capture_command

    output = tmp_path / "shot.png"

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        output.write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = await _run_capture_command(["capture", str(output)], output, run=fake_run)

    assert result is None


@pytest.mark.asyncio
async def test_capture_command_zero_byte_output_is_failure(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _run_capture_command

    output = tmp_path / "shot.png"

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        output.write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = await _run_capture_command(["capture", str(output)], output, run=fake_run)

    assert result is not None
    assert result.ok is False
    assert "zero-byte" in result.error.lower() or "empty" in result.error.lower()
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_capture_command_nonzero_exit_is_failure(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _run_capture_command

    output = tmp_path / "shot.png"

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "permission denied")

    result = await _run_capture_command(["capture", str(output)], output, run=fake_run)

    assert result is not None
    assert result.ok is False
    assert "permission denied" in result.error
    assert "Do not retry automatically" in result.error
```

Add `import subprocess` at the top of the test file.

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py::test_capture_command_zero_byte_output_is_failure tests/unit/capabilities/test_screenshot_send_tool.py::test_capture_command_nonzero_exit_is_failure -q
```

Expected: fail because `_run_capture_command` does not exist.

- [ ] **Step 3: Implement `_run_capture_command()`**

Add:

```python
async def _run_capture_command(
    command: list[str],
    output_path: Path,
    *,
    run: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> ToolResult | None:
    def default_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )

    runner = run or default_run
    completed = await asyncio.to_thread(runner, command)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        return ToolResult(
            ok=False,
            error=(
                f"Screenshot command failed: {detail}. Do not retry automatically; "
                "tell the user the screen could not be captured."
            ),
        )

    try:
        size_bytes = output_path.stat().st_size
    except OSError as exc:
        return ToolResult(
            ok=False,
            error=(
                f"Screenshot command did not create an output file: {exc}. Do not retry automatically; "
                "tell the user the screen could not be captured."
            ),
        )

    if size_bytes <= 0:
        return ToolResult(
            ok=False,
            error=(
                "Screenshot command created an empty zero-byte output file. Do not retry automatically; "
                "ask the user to grant screen capture permission or check the desktop session."
            ),
        )

    return None
```

Also import `asyncio`.

- [ ] **Step 4: Run screenshot tests**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py -q
```

Expected: all current screenshot tests pass.

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/screenshot_send/__init__.py tests/unit/capabilities/test_screenshot_send_tool.py
git commit -m "feat(tools): 增加截图命令执行校验" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 4: Implement Public Screenshot Tool and Temp Lifecycle

**Files:**
- Modify: `tests/unit/capabilities/test_screenshot_send_tool.py`
- Modify: `sebastian/capabilities/tools/screenshot_send/__init__.py`

- [ ] **Step 1: Add failing tests for public tool behavior**

Append:

```python
@pytest.mark.asyncio
async def test_capture_screenshot_and_send_uploads_then_deletes_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sebastian.capabilities.tools import screenshot_send
    from sebastian.core.types import ToolResult

    monkeypatch.setattr(screenshot_send.settings, "sebastian_data_dir", str(tmp_path / "sebastian"))
    sent_paths: list[Path] = []

    async def fake_send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
        path = Path(file_path)
        assert path.exists()
        sent_paths.append(path)
        assert display_name is not None
        return ToolResult(ok=True, output={"artifact": {"kind": "image", "filename": display_name}})

    async def fake_run_capture(command: list[str], output_path: Path, **kwargs) -> ToolResult | None:
        output_path.write_bytes(b"png")
        return None

    monkeypatch.setattr(screenshot_send, "send_file_path", fake_send_file_path)
    monkeypatch.setattr(screenshot_send, "_run_capture_command", fake_run_capture)
    monkeypatch.setattr(
        screenshot_send,
        "_select_capture_command",
        lambda **kwargs: ["capture", str(kwargs["output_path"])],
    )

    result = await screenshot_send.capture_screenshot_and_send(display_name="screen")

    assert result.ok is True
    assert sent_paths
    assert sent_paths[0].name == "screen.png"
    assert sent_paths[0].exists() is False


@pytest.mark.asyncio
async def test_capture_screenshot_and_send_deletes_temp_file_after_send_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sebastian.capabilities.tools import screenshot_send
    from sebastian.core.types import ToolResult

    monkeypatch.setattr(screenshot_send.settings, "sebastian_data_dir", str(tmp_path / "sebastian"))
    temp_paths: list[Path] = []

    async def fake_send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
        temp_paths.append(Path(file_path))
        return ToolResult(ok=False, error="send failed. Do not retry automatically; tell the user.")

    async def fake_run_capture(command: list[str], output_path: Path, **kwargs) -> ToolResult | None:
        output_path.write_bytes(b"png")
        return None

    monkeypatch.setattr(screenshot_send, "send_file_path", fake_send_file_path)
    monkeypatch.setattr(screenshot_send, "_run_capture_command", fake_run_capture)
    monkeypatch.setattr(
        screenshot_send,
        "_select_capture_command",
        lambda **kwargs: ["capture", str(kwargs["output_path"])],
    )

    result = await screenshot_send.capture_screenshot_and_send()

    assert result.ok is False
    assert temp_paths
    assert temp_paths[0].exists() is False


def test_display_name_without_suffix_becomes_png() -> None:
    from sebastian.capabilities.tools.screenshot_send import _resolve_screenshot_filename

    assert _resolve_screenshot_filename("screen").endswith(".png")
    assert _resolve_screenshot_filename("screen.png") == "screen.png"
```

- [ ] **Step 2: Run the public tool tests and confirm they fail**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py::test_capture_screenshot_and_send_uploads_then_deletes_temp_file tests/unit/capabilities/test_screenshot_send_tool.py::test_display_name_without_suffix_becomes_png -q
```

Expected: fail because the public tool and filename helper are not complete.

- [ ] **Step 3: Implement filename and temp helpers**

Add:

```python
from datetime import datetime
from contextlib import suppress
import logging
import time

from sebastian.capabilities.tools.send_file import send_file_path
from sebastian.config import settings

logger = logging.getLogger(__name__)
_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60


def _resolve_screenshot_filename(display_name: str | None = None) -> str:
    if display_name is None:
        return datetime.now().strftime("screenshot-%Y%m%d-%H%M%S.png")
    path = Path(display_name)
    if path.suffix:
        return display_name
    return f"{display_name}.png"


def _screenshot_tmp_dir() -> Path:
    return settings.user_data_dir / "tmp" / "screenshots"


def _cleanup_old_temp_files(directory: Path, *, now: float | None = None) -> None:
    current = time.time() if now is None else now
    if not directory.exists():
        return
    for path in directory.glob("*.png"):
        with suppress(OSError):
            if current - path.stat().st_mtime > _TEMP_MAX_AGE_SECONDS:
                path.unlink()
```

- [ ] **Step 4: Implement `capture_screenshot_and_send()`**

Add the decorated tool:

```python
@tool(
    name="capture_screenshot_and_send",
    description=DESCRIPTION,
    permission_tier=PermissionTier.HIGH_RISK,
)
async def capture_screenshot_and_send(display_name: str | None = None) -> ToolResult:
    filename = _resolve_screenshot_filename(display_name)
    directory = _screenshot_tmp_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup_old_temp_files(directory)
    output_path = directory / filename

    try:
        command = _select_capture_command(
            system=platform.system(),
            env=os.environ,
            which=shutil.which,
            output_path=output_path,
        )
    except RuntimeError as exc:
        return ToolResult(ok=False, error=str(exc))

    try:
        capture_error = await _run_capture_command(command, output_path)
        if capture_error is not None:
            return capture_error

        result = await send_file_path(str(output_path), display_name=filename)
        if not result.ok:
            return ToolResult(
                ok=False,
                error=(
                    f"Screenshot was captured but could not be sent: {result.error}. "
                    "Do not retry automatically; tell the user the screenshot could not be attached."
                ),
            )
        return result
    finally:
        with suppress(OSError):
            output_path.unlink()
```

Keep temp deletion errors logged only if adding logging is natural; they must not override a successful upload result.

- [ ] **Step 5: Run screenshot tests**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py -q
```

Expected: all screenshot tests pass.

- [ ] **Step 6: Commit**

```bash
git add sebastian/capabilities/tools/screenshot_send/__init__.py tests/unit/capabilities/test_screenshot_send_tool.py
git commit -m "feat(tools): 新增截图并发送工具" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 5: Verify Tool Metadata and Sebastian-Only Exposure

**Files:**
- Modify: `tests/unit/capabilities/test_screenshot_send_tool.py`
- Modify: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: Add failing metadata and exposure tests**

Append:

```python
def test_screenshot_tool_metadata_is_high_risk_and_precise() -> None:
    import sebastian.capabilities.tools.screenshot_send  # noqa: F401
    from sebastian.core.tool import get_tool
    from sebastian.permissions.types import PermissionTier

    registered = get_tool("capture_screenshot_and_send")
    assert registered is not None
    spec, _ = registered

    assert spec.name == "capture_screenshot_and_send"
    assert spec.permission_tier == PermissionTier.HIGH_RISK
    assert "backend host" in spec.description
    assert "not the Android device screen" in spec.description


def test_screenshot_tool_is_allowed_only_for_sebastian() -> None:
    from sebastian.orchestrator.sebas import Sebastian

    assert "capture_screenshot_and_send" in Sebastian.allowed_tools
```

Also add a shell-backed check in the manual verification step below to ensure sub-agent manifests do not contain the tool.

- [ ] **Step 2: Run tests and confirm exposure test fails**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py::test_screenshot_tool_is_allowed_only_for_sebastian -q
```

Expected: fail because `Sebastian.allowed_tools` has not been updated yet.

- [ ] **Step 3: Add the tool to Sebastian**

Modify `sebastian/orchestrator/sebas.py` and insert:

```python
"capture_screenshot_and_send",
```

near `"send_file"` in `Sebastian.allowed_tools`.

Do not modify:

- `sebastian/agents/forge/manifest.toml`
- `sebastian/agents/aide/manifest.toml`
- `sebastian/agents/*/manifest.toml`

- [ ] **Step 4: Run metadata and exposure tests**

Run:

```bash
pytest tests/unit/capabilities/test_screenshot_send_tool.py::test_screenshot_tool_metadata_is_high_risk_and_precise tests/unit/capabilities/test_screenshot_send_tool.py::test_screenshot_tool_is_allowed_only_for_sebastian -q
```

Expected: pass.

- [ ] **Step 5: Confirm sub-agent manifests do not expose the tool**

Run:

```bash
python - <<'PY'
from pathlib import Path
matches = [
    p for p in Path("sebastian/agents").glob("*/manifest.toml")
    if "capture_screenshot_and_send" in p.read_text(encoding="utf-8")
]
assert not matches, matches
print("ok")
PY
```

Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add sebastian/orchestrator/sebas.py tests/unit/capabilities/test_screenshot_send_tool.py
git commit -m "feat(orchestrator): 仅向 Sebastian 开放截图工具" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 6: Update Capability Documentation

**Files:**
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `sebastian/capabilities/README.md`

- [ ] **Step 1: Update `capabilities/tools/README.md` tree**

Add `screenshot_send/` after `send_file/` in the capability tools section:

```markdown
├── screenshot_send/          # Sebastian 截取后端主机屏幕并发送图片（permission_tier: HIGH_RISK，Sebastian-only）
│   └── __init__.py          # @tool: capture_screenshot_and_send
```

- [ ] **Step 2: Update `capabilities/tools/README.md` navigation**

Add a row:

```markdown
| Sebastian 截图并发送 | [screenshot_send/\_\_init\_\_.py](screenshot_send/__init__.py) |
```

- [ ] **Step 3: Update capability classification note**

In the capability tools row that currently lists `send_file`, include `capture_screenshot_and_send` but clarify it is controlled by `Sebastian.allowed_tools`, not sub-agent manifests:

```markdown
| **能力工具** | Read / Write / Edit / Bash / Glob / Grep / todo_write / todo_read / send_file / capture_screenshot_and_send 等 | manifest `allowed_tools` 或 Sebastian.allowed_tools 白名单 | 决定 Agent 的领域执行范围 |
```

Add a short note:

```markdown
`capture_screenshot_and_send` 当前只加入 `Sebastian.allowed_tools`，不要加入 sub-agent manifest。
```

- [ ] **Step 4: Update `capabilities/README.md` tree**

Add:

```markdown
│   ├── screenshot_send/  # Sebastian 截图并发送工具（Sebastian-only）
```

- [ ] **Step 5: Run README grep sanity check**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in [
    Path("sebastian/capabilities/tools/README.md"),
    Path("sebastian/capabilities/README.md"),
]:
    text = path.read_text(encoding="utf-8")
    assert "screenshot_send" in text, path
print("ok")
PY
```

Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add sebastian/capabilities/tools/README.md sebastian/capabilities/README.md
git commit -m "docs(capabilities): 记录 Sebastian 截图发送工具" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

### Task 7: Full Verification and Graph Refresh

**Files:**
- No new files unless verification exposes issues.

- [ ] **Step 1: Run focused capability tests**

Run:

```bash
pytest tests/unit/capabilities/test_send_file_tool.py tests/unit/capabilities/test_screenshot_send_tool.py -q
```

Expected: pass.

- [ ] **Step 2: Run tool/decorator smoke tests**

Run:

```bash
pytest tests/unit/capabilities/test_tool_decorator.py tests/unit/identity/test_policy_gate.py -q
```

Expected: pass.

- [ ] **Step 3: Run lint on touched Python files**

Run:

```bash
ruff check sebastian/capabilities/tools/send_file/__init__.py sebastian/capabilities/tools/screenshot_send/__init__.py tests/unit/capabilities/test_send_file_tool.py tests/unit/capabilities/test_screenshot_send_tool.py sebastian/orchestrator/sebas.py
```

Expected: pass.

- [ ] **Step 4: Format touched Python files**

Run:

```bash
ruff format sebastian/capabilities/tools/send_file/__init__.py sebastian/capabilities/tools/screenshot_send/__init__.py tests/unit/capabilities/test_send_file_tool.py tests/unit/capabilities/test_screenshot_send_tool.py sebastian/orchestrator/sebas.py
```

Expected: files are either unchanged or formatted.

- [ ] **Step 5: Refresh graphify code graph**

Because code files were modified, run:

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: completes successfully. If it modifies `graphify-out/`, inspect and include only relevant graph updates if the repository convention expects them tracked.

- [ ] **Step 6: Inspect final diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intentional files are modified.

- [ ] **Step 7: Final commit for verification fixes if needed**

Only if formatting, graph refresh, or small verification fixes changed files:

```bash
git add <specific files>
git commit -m "style(tools): 收口截图工具格式与图谱" -m "Co-Authored-By: gpt 5.5 <noreply@openai.com>"
```

---

## Notes for Implementers

- Use PyCharm MCP for Python symbol/text lookup before falling back to shell search.
- Do not add `capture_screenshot_and_send` to any sub-agent manifest.
- Do not implement DBus portal support in P0.
- Do not put screenshots under the repository, `/tmp`, or the attachment blob directory.
- The screenshot tool returns normal `send_file` image artifacts; Android UI should not need changes.
- `send_file_path()` is intentionally not a pure upload helper. It still requires active tool context.

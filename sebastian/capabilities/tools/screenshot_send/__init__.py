from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from sebastian.capabilities.tools.send_file import send_file_path
from sebastian.config import settings
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)
_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60


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

from __future__ import annotations

import subprocess
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


def test_linux_headless_raises_error(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    with pytest.raises(RuntimeError, match="DISPLAY/WAYLAND_DISPLAY is missing"):
        _select_capture_command(
            system="Linux",
            env={},
            which=lambda name: None,
            output_path=tmp_path / "shot.png",
        )


def test_linux_missing_backends_raises_error(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.screenshot_send import _select_capture_command

    with pytest.raises(RuntimeError, match="No supported Linux screenshot backend found"):
        _select_capture_command(
            system="Linux",
            env={"DISPLAY": ":0"},
            which=lambda name: None,
            output_path=tmp_path / "shot.png",
        )


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


@pytest.mark.asyncio
async def test_capture_screenshot_and_send_uploads_then_deletes_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sebastian.capabilities.tools import screenshot_send
    from sebastian.core.types import ToolResult

    monkeypatch.setattr(
        screenshot_send,
        "_screenshot_tmp_dir",
        lambda: tmp_path / "sebastian" / "data" / "tmp" / "screenshots",
    )
    sent_paths: list[Path] = []

    async def fake_send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
        path = Path(file_path)
        assert path.exists()
        sent_paths.append(path)
        assert display_name is not None
        return ToolResult(ok=True, output={"artifact": {"kind": "image", "filename": display_name}})

    async def fake_run_capture(
        command: list[str], output_path: Path, **kwargs
    ) -> ToolResult | None:
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

    monkeypatch.setattr(
        screenshot_send,
        "_screenshot_tmp_dir",
        lambda: tmp_path / "sebastian" / "data" / "tmp" / "screenshots",
    )
    temp_paths: list[Path] = []

    async def fake_send_file_path(file_path: str, display_name: str | None = None) -> ToolResult:
        temp_paths.append(Path(file_path))
        return ToolResult(ok=False, error="send failed. Do not retry automatically; tell the user.")

    async def fake_run_capture(
        command: list[str], output_path: Path, **kwargs
    ) -> ToolResult | None:
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
    import re

    from sebastian.capabilities.tools.screenshot_send import _resolve_screenshot_filename

    default_name = _resolve_screenshot_filename(None)
    assert re.fullmatch(r"screenshot-\d{8}-\d{6}\.png", default_name)
    assert _resolve_screenshot_filename("screen").endswith(".png")
    assert _resolve_screenshot_filename("screen.png") == "screen.png"


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

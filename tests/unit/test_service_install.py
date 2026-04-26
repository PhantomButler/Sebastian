from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebastian.cli.service_templates import (
    render_launchd_plist,
    render_systemd_unit,
)


def test_systemd_unit_contains_exec_start(tmp_path: Path) -> None:
    install_bin = tmp_path / ".venv" / "bin" / "sebastian"
    logs_dir = tmp_path / "logs"
    unit = render_systemd_unit(install_bin=install_bin, logs_dir=logs_dir)
    assert f"ExecStart={install_bin} serve" in unit
    assert "Restart=on-failure" in unit
    assert f"StandardOutput=append:{logs_dir / 'service.out.log'}" in unit
    assert f"StandardError=append:{logs_dir / 'service.err.log'}" in unit
    assert "WantedBy=default.target" in unit


def test_launchd_plist_renders_paths(tmp_path: Path) -> None:
    install_bin = Path("/Users/eric/.sebastian/app/.venv/bin/sebastian")
    logs_dir = Path("/Users/eric/.sebastian/logs")
    plist = render_launchd_plist(install_bin=install_bin, logs_dir=logs_dir)
    assert "<key>Label</key><string>com.sebastian</string>" in plist
    assert f"<string>{install_bin}</string>" in plist
    assert f"<string>{logs_dir / 'service.out.log'}</string>" in plist
    assert "<key>RunAtLoad</key><true/>" in plist
    assert "<key>KeepAlive</key>" in plist
    assert "<key>SuccessfulExit</key><false/>" in plist


@pytest.fixture
def linux_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sebastian.cli.service.sys.platform", "linux")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


@pytest.fixture
def macos_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sebastian.cli.service.sys.platform", "darwin")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


def _fake_install_dir(tmp_path: Path) -> Path:
    """Return a fake install dir that satisfies resolve_install_dir validation."""
    d = tmp_path / "app"
    (d / ".venv" / "bin").mkdir(parents=True)
    (d / ".venv" / "bin" / "sebastian").touch()
    return d


def test_install_writes_systemd_unit_on_linux(linux_env: Path, tmp_path: Path) -> None:
    from sebastian.cli import service

    fake_dir = _fake_install_dir(tmp_path)
    with (
        patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)) as run,
        patch("sebastian.cli.updater.resolve_install_dir", return_value=fake_dir),
    ):
        service.install()

    unit = linux_env / ".config/systemd/user/sebastian.service"
    assert unit.is_file()
    content = unit.read_text()
    assert "Sebastian personal AI butler" in content
    assert str(fake_dir / ".venv" / "bin" / "sebastian") in content
    cmds = [call.args[0] for call in run.call_args_list]
    assert ["systemctl", "--user", "daemon-reload"] in cmds
    assert ["systemctl", "--user", "enable", "--now", "sebastian.service"] in cmds


def test_install_writes_plist_on_macos(macos_env: Path, tmp_path: Path) -> None:
    from sebastian.cli import service

    fake_dir = _fake_install_dir(tmp_path)
    with (
        patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)) as run,
        patch("sebastian.cli.updater.resolve_install_dir", return_value=fake_dir),
    ):
        service.install()

    plist = macos_env / "Library/LaunchAgents/com.sebastian.plist"
    assert plist.is_file()
    content = plist.read_text()
    assert "com.sebastian" in content
    assert str(fake_dir / ".venv" / "bin" / "sebastian") in content
    cmds = [call.args[0] for call in run.call_args_list]
    assert ["launchctl", "load", "-w", str(plist)] in cmds


def test_install_refuses_when_unit_exists(linux_env: Path) -> None:
    from sebastian.cli import service

    unit = linux_env / ".config/systemd/user/sebastian.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[stale]")

    with pytest.raises(service.ServiceError, match="已存在"):
        service.install()


def test_uninstall_removes_unit_on_linux(linux_env: Path) -> None:
    from sebastian.cli import service

    unit = linux_env / ".config/systemd/user/sebastian.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[old]")

    with patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)):
        service.uninstall()

    assert not unit.exists()

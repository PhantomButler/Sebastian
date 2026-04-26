from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sebastian.cli.service_templates import (
    render_launchd_plist,
    render_systemd_unit,
)


def test_systemd_unit_contains_exec_start() -> None:
    unit = render_systemd_unit()
    assert "ExecStart=%h/.sebastian/app/.venv/bin/sebastian serve" in unit
    assert "Restart=on-failure" in unit
    assert "StandardOutput=append:%h/.sebastian/logs/service.out.log" in unit
    assert "StandardError=append:%h/.sebastian/logs/service.err.log" in unit
    assert "WantedBy=default.target" in unit


def test_launchd_plist_renders_home(tmp_path: Path) -> None:
    home = Path("/Users/eric")
    plist = render_launchd_plist(home=home)
    assert "<key>Label</key><string>com.sebastian</string>" in plist
    assert "<string>/Users/eric/.sebastian/app/.venv/bin/sebastian</string>" in plist
    assert "<string>/Users/eric/.sebastian/logs/service.out.log</string>" in plist
    assert "<key>RunAtLoad</key><true/>" in plist
    assert "<key>KeepAlive</key><true/>" in plist


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


def test_install_writes_systemd_unit_on_linux(linux_env: Path) -> None:
    from sebastian.cli import service

    with patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
        service.install()

    unit = linux_env / ".config/systemd/user/sebastian.service"
    assert unit.is_file()
    assert "Sebastian personal AI butler" in unit.read_text()
    cmds = [call.args[0] for call in run.call_args_list]
    assert ["systemctl", "--user", "daemon-reload"] in cmds
    assert ["systemctl", "--user", "enable", "--now", "sebastian.service"] in cmds


def test_install_writes_plist_on_macos(macos_env: Path) -> None:
    from sebastian.cli import service

    with patch.object(service.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
        service.install()

    plist = macos_env / "Library/LaunchAgents/com.sebastian.plist"
    assert plist.is_file()
    assert "com.sebastian" in plist.read_text()
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

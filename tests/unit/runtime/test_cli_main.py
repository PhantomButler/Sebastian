from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sebastian.cli.service import ServiceState
from sebastian.main import app


runner = CliRunner()


def test_status_reports_active_service(monkeypatch) -> None:
    monkeypatch.setattr(
        "sebastian.cli.service.get_service_state",
        lambda: ServiceState(
            kind="systemd",
            installed=True,
            active=True,
            status_text="systemd user service: active",
        ),
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "systemd user service: active" in result.output


def test_status_falls_back_to_legacy_daemon_when_service_is_not_installed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sebastian.cli.service.get_service_state",
        lambda: ServiceState(
            kind="systemd",
            installed=False,
            active=False,
            status_text="systemd user service: not installed",
        ),
    )
    monkeypatch.setattr("sebastian.cli.daemon.pid_path", lambda _run_dir: tmp_path)
    monkeypatch.setattr("sebastian.cli.daemon.read_pid", lambda _path: 456)
    monkeypatch.setattr("sebastian.cli.daemon.is_running", lambda _pid: True)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "PID 456" in result.output


def test_status_reports_inactive_service_then_checks_legacy_daemon(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sebastian.cli.service.get_service_state",
        lambda: ServiceState(
            kind="systemd",
            installed=True,
            active=False,
            status_text="systemd user service: inactive",
        ),
    )
    monkeypatch.setattr("sebastian.cli.daemon.pid_path", lambda _run_dir: tmp_path)
    monkeypatch.setattr("sebastian.cli.daemon.read_pid", lambda _path: 456)
    monkeypatch.setattr("sebastian.cli.daemon.is_running", lambda _pid: True)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "systemd user service: inactive" in result.output
    assert "PID 456" in result.output

from __future__ import annotations

from pathlib import Path

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

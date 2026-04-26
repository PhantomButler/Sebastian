"""Service unit / plist template rendering.

Both systemd and launchd templates are rendered with explicit absolute paths
so that a custom SEBASTIAN_DATA_DIR is respected correctly.
"""

from __future__ import annotations

from pathlib import Path

_SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=Sebastian personal AI butler
After=network-online.target

[Service]
Type=simple
ExecStart={install_bin} serve
Restart=on-failure
RestartSec=5
StandardOutput=append:{out_log}
StandardError=append:{err_log}

[Install]
WantedBy=default.target
"""

_LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sebastian</string>
  <key>ProgramArguments</key>
  <array>
    <string>{install_bin}</string>
    <string>serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
  </dict>
  <key>StandardOutPath</key><string>{out_log}</string>
  <key>StandardErrorPath</key><string>{err_log}</string>
</dict>
</plist>
"""


def render_systemd_unit(*, install_bin: Path, logs_dir: Path) -> str:
    return (
        _SYSTEMD_UNIT_TEMPLATE.replace("{install_bin}", str(install_bin))
        .replace("{out_log}", str(logs_dir / "service.out.log"))
        .replace("{err_log}", str(logs_dir / "service.err.log"))
    )


def render_launchd_plist(*, install_bin: Path, logs_dir: Path) -> str:
    return (
        _LAUNCHD_PLIST_TEMPLATE.replace("{install_bin}", str(install_bin))
        .replace("{out_log}", str(logs_dir / "service.out.log"))
        .replace("{err_log}", str(logs_dir / "service.err.log"))
    )

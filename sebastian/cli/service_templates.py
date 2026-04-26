"""Service unit / plist template rendering.

systemd uses %h for $HOME at runtime; launchd plists do not support
variable expansion, so HOME is rendered into the plist content directly.
"""

from __future__ import annotations

from pathlib import Path

_SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=Sebastian personal AI butler
After=network-online.target

[Service]
Type=simple
ExecStart=%h/.sebastian/app/.venv/bin/sebastian serve
Restart=on-failure
RestartSec=5
StandardOutput=append:%h/.sebastian/logs/service.out.log
StandardError=append:%h/.sebastian/logs/service.err.log

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
    <string>{home}/.sebastian/app/.venv/bin/sebastian</string>
    <string>serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{home}/.sebastian/logs/service.out.log</string>
  <key>StandardErrorPath</key><string>{home}/.sebastian/logs/service.err.log</string>
</dict>
</plist>
"""


def render_systemd_unit() -> str:
    return _SYSTEMD_UNIT_TEMPLATE


def render_launchd_plist(*, home: Path) -> str:
    return _LAUNCHD_PLIST_TEMPLATE.replace("{home}", str(home))

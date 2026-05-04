"""``sebastian service`` subcommands — install/uninstall/start/stop/restart/status.

User-level systemd units (Linux) and launchd LaunchAgents (macOS). No sudo.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer

from sebastian.cli.service_templates import render_launchd_plist, render_systemd_unit

app = typer.Typer(name="service", help="作为后台系统服务管理 Sebastian")


class ServiceError(RuntimeError):
    """Raised when a service operation fails."""


@dataclass(frozen=True)
class ServiceState:
    kind: str
    installed: bool
    active: bool
    status_text: str


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "sebastian.service"


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.sebastian.plist"


def _platform_unsupported() -> ServiceError:
    return ServiceError(f"unsupported platform: {sys.platform}")


# ---------------------------------------------------------------------------
# core operations (no Typer)
# ---------------------------------------------------------------------------


def install() -> None:
    if sys.platform.startswith("linux"):
        _install_systemd()
    elif sys.platform == "darwin":
        _install_launchd()
    else:
        raise _platform_unsupported()


def uninstall() -> None:
    if sys.platform.startswith("linux"):
        _uninstall_systemd()
    elif sys.platform == "darwin":
        _uninstall_launchd()
    else:
        raise _platform_unsupported()


def start() -> None:
    if sys.platform.startswith("linux"):
        _run(["systemctl", "--user", "start", "sebastian.service"])
    elif sys.platform == "darwin":
        _run(["launchctl", "start", "com.sebastian"])
    else:
        raise _platform_unsupported()


def stop() -> None:
    if sys.platform.startswith("linux"):
        _run(["systemctl", "--user", "stop", "sebastian.service"])
    elif sys.platform == "darwin":
        _run(["launchctl", "stop", "com.sebastian"])
    else:
        raise _platform_unsupported()


def restart() -> None:
    if sys.platform.startswith("linux"):
        _run(["systemctl", "--user", "restart", "sebastian.service"])
    elif sys.platform == "darwin":
        subprocess.run(["launchctl", "stop", "com.sebastian"], check=False)
        _run(["launchctl", "start", "com.sebastian"])
    else:
        raise _platform_unsupported()


def status() -> str:
    return get_service_state().status_text


def get_service_state() -> ServiceState:
    if sys.platform.startswith("linux"):
        return _systemd_state()
    if sys.platform == "darwin":
        return _launchd_state()
    raise _platform_unsupported()


def is_service_installed() -> bool:
    try:
        return get_service_state().installed
    except ServiceError:
        return False


def is_service_active() -> bool:
    try:
        state = get_service_state()
    except ServiceError:
        return False
    return state.installed and state.active


# ---------------------------------------------------------------------------
# systemd
# ---------------------------------------------------------------------------


def _install_systemd() -> None:
    unit = _systemd_unit_path()
    if unit.exists():
        raise ServiceError(f"{unit} 已存在，请先 sebastian service uninstall")

    from sebastian.cli.updater import resolve_install_dir
    from sebastian.config import settings

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    unit.parent.mkdir(parents=True, exist_ok=True)
    install_bin = resolve_install_dir() / ".venv" / "bin" / "sebastian"
    env_file = settings.data_dir / ".env"
    unit.write_text(
        render_systemd_unit(
            install_bin=install_bin,
            logs_dir=settings.logs_dir,
            env_file=env_file,
        )
    )
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", "sebastian.service"])
    _check_linger()


def _uninstall_systemd() -> None:
    unit = _systemd_unit_path()
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "sebastian.service"],
        check=False,
    )
    if unit.exists():
        unit.unlink()
        _run(["systemctl", "--user", "daemon-reload"])


def _systemd_state() -> ServiceState:
    unit = _systemd_unit_path()
    if not unit.exists():
        return ServiceState(
            kind="systemd",
            installed=False,
            active=False,
            status_text="systemd user service: not installed",
        )

    proc = subprocess.run(
        ["systemctl", "--user", "is-active", "sebastian.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    state = proc.stdout.strip()
    if not state:
        state = proc.stderr.strip()
    if not state:
        state = "unknown"
    return ServiceState(
        kind="systemd",
        installed=True,
        active=state == "active",
        status_text=(
            f"systemd user service: {state}\n"
            "  status:  systemctl --user status sebastian\n"
            "  restart: sebastian service restart"
        ),
    )


def _check_linger() -> None:
    """Warn user if user-level linger is disabled (service won't survive logout)."""
    user = os.environ.get("USER") or ""
    if not user:
        return
    proc = subprocess.run(
        ["loginctl", "show-user", user, "-P", "Linger"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout.strip().lower() != "yes":
        typer.echo(
            "\n⚠ 当前用户未开启 linger，重启后服务不会自动拉起。如需开机自启请执行：\n"
            f"    sudo loginctl enable-linger {user}\n"
        )


# ---------------------------------------------------------------------------
# launchd
# ---------------------------------------------------------------------------


def _install_launchd() -> None:
    plist = _launchd_plist_path()
    if plist.exists():
        raise ServiceError(f"{plist} 已存在，请先 sebastian service uninstall")

    from sebastian.cli.updater import resolve_install_dir
    from sebastian.config import settings

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    install_bin = resolve_install_dir() / ".venv" / "bin" / "sebastian"
    env_file = settings.data_dir / ".env"
    plist.write_text(
        render_launchd_plist(
            install_bin=install_bin,
            logs_dir=settings.logs_dir,
            env_file=env_file,
        )
    )
    _run(["launchctl", "load", "-w", str(plist)])


def _uninstall_launchd() -> None:
    plist = _launchd_plist_path()
    if plist.exists():
        subprocess.run(["launchctl", "unload", "-w", str(plist)], check=False)
        plist.unlink()


def _launchd_state() -> ServiceState:
    plist = _launchd_plist_path()
    command_hints = (
        "\n  status:  launchctl list com.sebastian\n  restart: sebastian service restart"
    )
    if not plist.exists():
        return ServiceState(
            kind="launchd",
            installed=False,
            active=False,
            status_text="launchd: not installed",
        )

    proc = subprocess.run(
        ["launchctl", "list", "com.sebastian"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ServiceState(
            kind="launchd",
            installed=True,
            active=False,
            status_text=f"launchd: installed but not loaded{command_hints}",
        )
    fields = proc.stdout.split(None, 1)
    first_field = fields[0] if fields else ""
    if not first_field.isdigit():
        return ServiceState(
            kind="launchd",
            installed=True,
            active=False,
            status_text=f"launchd: loaded but not running{command_hints}",
        )
    return ServiceState(
        kind="launchd",
        installed=True,
        active=True,
        status_text=f"launchd: running{command_hints}",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise ServiceError(f"命令失败: {' '.join(cmd)} (exit {proc.returncode})")


def _tail_log(log_path: Path, lines: int = 20) -> str:
    if not log_path.exists():
        return ""
    try:
        with log_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 8192)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="replace").splitlines()
        return "\n".join(tail[-lines:])
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.command("install")
def cmd_install() -> None:
    """注册 Sebastian 为系统服务（开机自启 + 异常重启）。"""
    try:
        install()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo("✓ 已安装并启动 Sebastian 系统服务")


@app.command("uninstall")
def cmd_uninstall() -> None:
    """卸载 Sebastian 系统服务。"""
    try:
        uninstall()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo("✓ 已卸载 Sebastian 系统服务")


@app.command("start")
def cmd_start() -> None:
    """启动 Sebastian 系统服务。"""
    try:
        start()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command("stop")
def cmd_stop() -> None:
    """停止 Sebastian 系统服务。"""
    try:
        stop()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command("restart")
def cmd_restart() -> None:
    """重启 Sebastian 系统服务。"""
    try:
        restart()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo("✓ Sebastian 系统服务已重启")


@app.command("status")
def cmd_status() -> None:
    """显示服务状态及最近日志。"""
    from sebastian.config import settings

    try:
        info = status()
    except ServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(info)
    tail = _tail_log(settings.logs_dir / "service.err.log")
    if tail:
        typer.echo("\n--- 最近 service.err.log ---")
        typer.echo(tail)

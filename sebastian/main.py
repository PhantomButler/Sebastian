from __future__ import annotations

import os
import sys

import typer
import uvicorn

from sebastian.cli import service
from sebastian.cli.service import app as service_app


def _resolve_version() -> str:
    import importlib.metadata
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject.exists():
        with pyproject.open("rb") as file:
            project_version = tomllib.load(file)["project"]["version"]
            return str(project_version)
    return importlib.metadata.version("sebastian")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Sebastian v{_resolve_version()}")
        raise typer.Exit()


app = typer.Typer(name="sebastian", help="Sebastian — Personal AI Butler")
app.add_typer(service_app, name="service")


@app.callback()
def main(
    _show_version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show installed version and exit.",
    ),
) -> None:
    """Sebastian command line interface."""


@app.command()
def version() -> None:
    """Print the installed Sebastian version."""
    typer.echo(f"Sebastian v{_resolve_version()}")


@app.command()
def serve(
    host: str = typer.Option(None, help="Override gateway host"),
    port: int = typer.Option(None, help="Override gateway port"),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="以后台模式运行"),
) -> None:
    """Start the Sebastian gateway server."""
    from sebastian.cli.daemon import is_running, pid_path, read_pid, write_pid
    from sebastian.config import ensure_data_dir, settings

    ensure_data_dir()

    h = host or settings.sebastian_gateway_host
    p = port or settings.sebastian_gateway_port
    installed_version = _resolve_version()
    log_file = settings.logs_dir / "main.log"

    # --- startup banner ---
    typer.echo(f"Sebastian v{installed_version}")
    typer.echo(f"  数据目录: {settings.data_dir}")
    typer.echo(f"  日志文件: {log_file}")
    typer.echo(f"  监听地址: http://{h}:{p}")

    if daemon:
        pf = pid_path(settings.run_dir)
        existing = read_pid(pf)
        if existing and is_running(existing):
            typer.echo(f"❌ Sebastian 已在运行 (PID {existing})", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"  运行模式: 后台 (PID 文件: {pf})")

        log_dir = settings.logs_dir
        log_dir.mkdir(parents=True, exist_ok=True)

        pid = os.fork()
        if pid > 0:
            # parent
            typer.echo(f"✓ Sebastian 已启动 (PID {pid})")
            raise typer.Exit(code=0)

        # child — detach
        os.setsid()
        log_fd = open(log_file, "a")  # noqa: SIM115
        os.dup2(log_fd.fileno(), sys.stdout.fileno())
        os.dup2(log_fd.fileno(), sys.stderr.fileno())
        write_pid(pf)
    else:
        typer.echo("  运行模式: 前台 (Ctrl+C 停止)")

    uvicorn.run("sebastian.gateway.app:app", host=h, port=p, reload=reload)


@app.command()
def stop() -> None:
    """Stop the background Sebastian server."""
    from sebastian.cli.daemon import pid_path, stop_process
    from sebastian.config import settings

    pf = pid_path(settings.run_dir)
    if stop_process(pf):
        typer.echo("✓ Sebastian 已停止")
    else:
        typer.echo("Sebastian 未在运行")


@app.command()
def status() -> None:
    """Check whether Sebastian is running."""
    from sebastian.cli.daemon import is_running, pid_path, read_pid, remove_pid
    from sebastian.config import settings

    try:
        service_state = service.get_service_state()
    except service.ServiceError as e:
        typer.echo(f"⚠ 无法读取系统服务状态: {e}", err=True)
    else:
        if service_state.installed:
            typer.echo(service_state.status_text)
            if service_state.active:
                return
            typer.echo("提示：系统服务已安装但未运行；继续检查 legacy daemon。")

    pf = pid_path(settings.run_dir)
    pid = read_pid(pf)
    if pid and is_running(pid):
        typer.echo(f"✓ Sebastian 正在运行 (PID {pid})")
    else:
        typer.echo("Sebastian 未在运行")
        if pid:
            remove_pid(pf)


@app.command()
def logs(
    follow: bool = typer.Option(True, "--follow/--no-follow", "-f", help="实时跟踪"),
    lines: int = typer.Option(50, "--lines", "-n", help="显示最后 N 行"),
) -> None:
    """Tail Sebastian log file."""
    import subprocess

    from sebastian.config import settings

    log_file = settings.logs_dir / "main.log"
    if not log_file.exists():
        typer.echo(f"日志文件不存在: {log_file}")
        raise typer.Exit(code=1)
    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_file))
    subprocess.run(cmd)


@app.command()
def update(
    check: bool = typer.Option(False, "--check", help="只检查是否有新版本，不实际升级"),
    force: bool = typer.Option(False, "--force", help="即使版本一致也强制重新下载"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """Update Sebastian to the latest GitHub release in place."""
    from sebastian.cli.updater import UpdateError, run_update

    try:
        code = run_update(check_only=check, force=force, assume_yes=yes)
    except UpdateError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1) from e
    raise typer.Exit(code=code)


@app.command()
def init(
    headless: bool = typer.Option(
        False, help="Non-interactive CLI wizard (for SSH / headless servers)"
    ),
) -> None:
    """Initialize Sebastian (create owner account + generate JWT secret)."""
    import asyncio

    if headless:
        from sebastian.cli.init_wizard import run_interactive_headless_cli

        asyncio.run(run_interactive_headless_cli())
    else:
        typer.echo(
            "默认通过 Web 向导初始化。请运行 `sebastian serve` 并在浏览器打开提示的 URL。\n"
            "如果当前是无头服务器，请加 --headless 进入命令行向导。"
        )


if __name__ == "__main__":
    app()

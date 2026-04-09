from __future__ import annotations

import typer
import uvicorn

app = typer.Typer(name="sebastian", help="Sebastian — Personal AI Butler")


@app.command()
def serve(
    host: str = typer.Option(None, help="Override gateway host"),
    port: int = typer.Option(None, help="Override gateway port"),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)"),
) -> None:
    """Start the Sebastian gateway server."""
    from sebastian.config import settings

    h = host or settings.sebastian_gateway_host
    p = port or settings.sebastian_gateway_port
    uvicorn.run("sebastian.gateway.app:app", host=h, port=p, reload=reload)


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

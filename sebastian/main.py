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
def init(
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, help="Owner password"
    ),
) -> None:
    """Initialize Sebastian: hash owner password and print to .env."""
    from sebastian.gateway.auth import hash_password

    hashed = hash_password(password)
    typer.echo(f"\nAdd this to your .env:\nSEBASTIAN_OWNER_PASSWORD_HASH={hashed}\n")


if __name__ == "__main__":
    app()

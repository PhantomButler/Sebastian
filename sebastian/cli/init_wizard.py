from __future__ import annotations

from pathlib import Path
from typing import Any

import typer


async def run_headless_wizard(
    *,
    owner_store: Any,
    secret_key_path: Path,
    answers: dict[str, str],
) -> None:
    """Pure-logic headless init wizard (unit-testable).

    Raises RuntimeError if Sebastian is already initialized (owner exists).
    """
    if await owner_store.owner_exists():
        raise RuntimeError("Sebastian is already initialized — owner account already exists.")

    from sebastian.gateway.auth import hash_password
    from sebastian.gateway.setup.secret_key import SecretKeyManager

    await owner_store.create_owner(
        name=answers["name"],
        password_hash=hash_password(answers["password"]),
    )

    mgr = SecretKeyManager(secret_key_path)
    if not mgr.exists():
        mgr.generate()


async def run_interactive_headless_cli() -> None:
    """Typer-driven interactive CLI entrypoint for `sebastian init --headless`."""
    name: str = typer.prompt("Owner name")
    password: str = typer.prompt("Password", hide_input=True)
    while len(password) < 8:
        typer.echo("Password must be at least 8 characters.", err=True)
        password = typer.prompt("Password", hide_input=True)
    confirm: str = typer.prompt("Confirm password", hide_input=True)
    while confirm != password:
        typer.echo("Passwords do not match.", err=True)
        password = typer.prompt("Password", hide_input=True)
        while len(password) < 8:
            typer.echo("Password must be at least 8 characters.", err=True)
            password = typer.prompt("Password", hide_input=True)
        confirm = typer.prompt("Confirm password", hide_input=True)

    from sebastian.config import settings
    from sebastian.store.database import get_session_factory, init_db

    await init_db()
    from sebastian.store.owner_store import OwnerStore

    store = OwnerStore(get_session_factory())

    await run_headless_wizard(
        owner_store=store,
        secret_key_path=settings.resolved_secret_key_path(),
        answers={"name": name, "password": password},
    )

    typer.echo(f"\n✓ Owner '{name}' created.")
    typer.echo("✓ JWT secret key generated.")
    typer.echo("\nRun `sebastian serve` to start the server.\n")

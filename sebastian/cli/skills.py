from __future__ import annotations

from collections.abc import Callable

import httpx
import typer

from sebastian.config import settings
from sebastian.skills_registry.client import (
    DEFAULT_REGISTRY_URL,
    RegistryClient,
    resolve_registry_url,
)
from sebastian.skills_registry.installer import (
    SkillInstallError,
    install_skill,
    remove_installed_skill,
    update_skill,
)
from sebastian.skills_registry.installer import (
    list_installed as _list_installed,
)
from sebastian.skills_registry.models import (
    InstalledSkill,
    SkillDetail,
    SkillRegistryError,
)

app = typer.Typer(
    name="skills",
    help="Search, install, update, and remove Sebastian Skills",
)


def search_registry(query: str, registry: str | None = None) -> list[tuple[str, str]]:
    """Search the configured Skill registry and return printable rows."""
    return [(result.slug, result.description) for result in RegistryClient(registry).search(query)]


def list_installed() -> list[InstalledSkill]:
    """List Skills from the default runtime extensions directory."""
    return _list_installed(settings.skills_extensions_dir)


def _run_or_exit[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except (SkillRegistryError, SkillInstallError, httpx.HTTPError) as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _confirm_custom_registry(registry: str | None) -> None:
    effective_registry = resolve_registry_url(registry)
    default_registry = resolve_registry_url(DEFAULT_REGISTRY_URL)
    if effective_registry == default_registry:
        return
    typer.confirm(
        f"Use non-default registry {effective_registry!r}?",
        abort=True,
    )


def _format_optional(value: object) -> str:
    return "-" if value is None or value == "" else str(value)


def _print_detail(detail: SkillDetail) -> None:
    typer.echo(f"Slug: {detail.slug}")
    typer.echo(f"Name: {detail.name}")
    typer.echo(f"Version: {_format_optional(detail.version)}")
    typer.echo(f"Security: {_format_optional(detail.security_status)}")
    typer.echo(f"Description: {_format_optional(detail.description)}")
    typer.echo(f"Download: {_format_optional(detail.download_url)}")
    typer.echo(f"SHA256: {_format_optional(detail.sha256)}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    registry: str | None = typer.Option(None, "--registry", help="Registry base URL"),
) -> None:
    """Search the Skill registry."""
    rows = _run_or_exit(lambda: search_registry(query, registry=registry))
    for slug, description in rows:
        typer.echo(f"{slug}\t{description}")


@app.command()
def inspect(
    slug: str = typer.Argument(..., help="Skill slug"),
    version: str | None = typer.Option(None, "--version", help="Specific version"),
    registry: str | None = typer.Option(None, "--registry", help="Registry base URL"),
) -> None:
    """Inspect registry metadata for a Skill."""
    detail = _run_or_exit(lambda: RegistryClient(registry).inspect(slug, version=version))
    _print_detail(detail)


@app.command()
def install(
    slug: str = typer.Argument(..., help="Skill slug"),
    version: str | None = typer.Option(None, "--version", help="Specific version"),
    registry: str | None = typer.Option(None, "--registry", help="Registry base URL"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing managed or unmanaged destination",
    ),
) -> None:
    """Install a Skill package."""
    _run_or_exit(lambda: _confirm_custom_registry(registry))
    if force:
        typer.confirm("Overwrite an existing Skill if present?", abort=True)

    result = _run_or_exit(
        lambda: install_skill(
            slug,
            version=version,
            registry=registry,
            force=force,
        )
    )
    typer.echo(f"Installed {result.slug} as {result.registered_name}")
    typer.echo("Available to new Sebastian sessions.")


@app.command(name="list")
def list_command() -> None:
    """List installed Skills."""
    rows = _run_or_exit(list_installed)
    for skill in rows:
        version = _format_optional(skill.version)
        managed = "managed" if skill.managed else "unmanaged"
        typer.echo(f"{skill.slug}\t{skill.registered_name}\t{version}\t{managed}")


@app.command()
def update(
    slug: str | None = typer.Argument(None, help="Skill slug"),
    version: str | None = typer.Option(None, "--version", help="Specific version"),
    registry: str | None = typer.Option(None, "--registry", help="Registry base URL"),
    all_: bool = typer.Option(False, "--all", help="Update all package-managed Skills"),
    force: bool = typer.Option(False, "--force", help="Overwrite local changes"),
    allow_rename: bool = typer.Option(
        False,
        "--allow-rename",
        help="Allow updates that change the runtime Skill name",
    ),
) -> None:
    """Update an installed Skill."""
    if all_:
        typer.echo("❌ Updating all Skills is not implemented yet.", err=True)
        raise typer.Exit(code=1)
    if slug is None:
        typer.echo("❌ Provide a Skill slug or use --all.", err=True)
        raise typer.Exit(code=1)
    _run_or_exit(lambda: _confirm_custom_registry(registry))
    if force:
        typer.confirm("Overwrite local changes if present?", abort=True)
    if allow_rename:
        typer.confirm("Allow this update to rename the runtime Skill?", abort=True)

    result = _run_or_exit(
        lambda: update_skill(
            slug,
            version=version,
            registry=registry,
            force=force,
            allow_rename=allow_rename,
        )
    )
    typer.echo(f"Updated {result.slug} as {result.registered_name}")
    typer.echo("Available to new Sebastian sessions.")


@app.command()
def remove(
    slug: str = typer.Argument(..., help="Skill slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove a package-managed Skill."""
    if not yes:
        typer.confirm(f"Remove installed Skill {slug!r}?", abort=True)

    result = _run_or_exit(lambda: remove_installed_skill(slug, yes=True))
    typer.echo(f"Removed {result.slug} ({result.registered_name})")

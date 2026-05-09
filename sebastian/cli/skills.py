from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

import httpx
import typer

from sebastian.config import settings
from sebastian.skills_registry.client import (
    DEFAULT_REGISTRY_URL,
    RegistryClient,
    resolve_registry_url,
)
from sebastian.skills_registry.installer import (
    MAX_LOCAL_SKILL_READ_BYTES,
    SkillInstallError,
    install_skill,
    read_local_skill_file,
    remove_installed_skill,
    show_local_skill,
    update_skill,
)
from sebastian.skills_registry.installer import (
    list_installed as _list_installed,
)
from sebastian.skills_registry.lockfile import LockfileError
from sebastian.skills_registry.models import (
    InstalledSkill,
    LocalSkillDetail,
    SkillDetail,
    SkillRegistryError,
)

app = typer.Typer(
    name="skills",
    help="Search, show, install, update, and remove Sebastian Skills",
)


class SearchSource(StrEnum):
    LOCAL = "local"
    REGISTRY = "registry"
    ALL = "all"


_ASCII_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_EXACT_SLUG_OR_NAME_SCORE = 120
_SUBSTRING_SLUG_OR_NAME_SCORE = 60
_DESCRIPTION_SCORE = 30
_REGISTERED_NAME_SCORE = 15


def search_registry(
    query: str,
    registry: str | None = None,
) -> list[tuple[str, str | None, str | None, str]]:
    """Search the configured Skill registry and return printable rows."""
    return [
        (
            result.slug,
            result.latest_version,
            result.security_status,
            result.description,
        )
        for result in RegistryClient(registry).search(query)
    ]


def list_installed() -> list[InstalledSkill]:
    """List Skills from the default runtime extensions directory."""
    return _list_installed(settings.skills_extensions_dir)


def _run_or_exit[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except (SkillRegistryError, SkillInstallError, LockfileError, httpx.HTTPError) as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _confirm_custom_registry(registry: str | None) -> None:
    _confirm_registry_url(resolve_registry_url(registry))


def _confirm_registry_url(registry_url: str) -> None:
    if registry_url == resolve_registry_url(DEFAULT_REGISTRY_URL):
        return
    typer.confirm(
        f"Use non-default registry {registry_url!r}?",
        abort=True,
    )


def _resolve_update_registry(slug: str, registry: str | None) -> str | None:
    if registry is not None:
        return resolve_registry_url(registry)
    for skill in list_installed():
        if skill.slug == slug and skill.managed:
            if skill.registry is None:
                return None
            return resolve_registry_url(skill.registry)
    return None


def _effective_update_registry(skill: InstalledSkill, registry: str | None) -> str | None:
    if registry is not None:
        return resolve_registry_url(registry)
    if skill.registry is None:
        return None
    return resolve_registry_url(skill.registry)


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


def _is_ascii_token(token: str) -> bool:
    return token.isascii()


def _search_tokens(query: str) -> tuple[str, ...]:
    seen: set[str] = set()
    tokens: list[str] = []
    for raw in query.split():
        token = raw.strip().casefold()
        if not token:
            continue
        if _is_ascii_token(token) and token in _ASCII_STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tuple(tokens)


def _score_local_skill(skill: InstalledSkill, tokens: tuple[str, ...]) -> int:
    score = 0
    slug = skill.slug.casefold()
    name = skill.name.casefold()
    registered_name = skill.registered_name.casefold()
    description = skill.description.casefold()
    for token in tokens:
        if token == slug or (name and token == name):
            score += _EXACT_SLUG_OR_NAME_SCORE
        elif token in slug or (name and token in name):
            score += _SUBSTRING_SLUG_OR_NAME_SCORE
        if token in description:
            score += _DESCRIPTION_SCORE
        if token in registered_name:
            score += _REGISTERED_NAME_SCORE
    return score


def _source_sort_rank(source: str) -> int:
    return {"builtin": 0, "managed": 1, "unmanaged": 2}.get(source, 3)


def _search_local(query: str) -> list[InstalledSkill]:
    tokens = _search_tokens(query)
    if not tokens:
        return []
    scored = [(_score_local_skill(skill, tokens), skill) for skill in list_installed()]
    matches = [(score, skill) for score, skill in scored if score > 0]
    matches.sort(
        key=lambda item: (
            -item[0],
            _source_sort_rank(item[1].source),
            item[1].slug,
        )
    )
    return [skill for _score, skill in matches]


def _print_local_search_rows(rows: list[InstalledSkill]) -> None:
    typer.echo("LOCAL")
    for skill in rows:
        description = _format_optional(skill.description)
        typer.echo(f"{skill.slug}\t{skill.source}\t{skill.registered_name}\t{description}")


def _print_registry_search_rows(
    rows: list[tuple[str, str | None, str | None, str]],
) -> None:
    typer.echo("REGISTRY")
    for slug, version, security_status, description in rows:
        version_security = f"{_format_optional(version)}/{_format_optional(security_status)}"
        typer.echo(f"{slug}\t{version_security}\t{description}")


def _print_local_detail(detail: LocalSkillDetail, include_body: bool) -> None:
    typer.echo(f"Slug: {detail.slug}")
    typer.echo(f"Name: {detail.name}")
    typer.echo(f"Registered: {detail.registered_name}")
    typer.echo(f"Source: {detail.source}")
    typer.echo(f"Version: {_format_optional(detail.version)}")
    typer.echo(f"Registry: {_format_optional(detail.registry)}")
    typer.echo(f"Path: {detail.path}")
    typer.echo(f"Description: {_format_optional(detail.description)}")
    typer.echo("Files:")
    for relative_path in detail.files:
        typer.echo(f"- {relative_path}")
    if not include_body:
        return
    if len(detail.body.encode("utf-8")) > MAX_LOCAL_SKILL_READ_BYTES:
        raise SkillInstallError("Local Skill body is too large")
    typer.echo("")
    typer.echo("Instructions:")
    typer.echo(detail.body or "-")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    registry: str | None = typer.Option(None, "--registry", help="Registry base URL"),
    source: SearchSource = typer.Option(
        SearchSource.LOCAL,
        "--source",
        help="Search source: local, registry, or all",
    ),
) -> None:
    """Search local Skills by default, optionally querying the registry."""
    if source in (SearchSource.LOCAL, SearchSource.ALL):
        local_rows = _run_or_exit(lambda: _search_local(query))
        _print_local_search_rows(local_rows)
    if source in (SearchSource.REGISTRY, SearchSource.ALL):
        if source is SearchSource.ALL:
            typer.echo("")
        registry_rows = _run_or_exit(lambda: search_registry(query, registry=registry))
        _print_registry_search_rows(registry_rows)


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
    typer.echo("available immediately through sebastian skills list/show/read.")


@app.command(name="list")
def list_command() -> None:
    """List installed Skills."""
    rows = _run_or_exit(list_installed)
    for skill in rows:
        version = _format_optional(skill.version)
        typer.echo(f"{skill.slug}\t{skill.registered_name}\t{version}\t{skill.source}")


@app.command()
def show(
    identifier: str = typer.Argument(..., help="Local Skill slug or runtime name"),
    body: bool = typer.Option(False, "--body", help="Print Skill instructions body"),
) -> None:
    """Show local Skill metadata."""
    detail = _run_or_exit(
        lambda: show_local_skill(identifier, settings.skills_extensions_dir)
    )
    _run_or_exit(lambda: _print_local_detail(detail, include_body=body))


@app.command()
def read(
    identifier: str = typer.Argument(..., help="Local Skill slug or runtime name"),
    relative_path: str = typer.Argument(..., help="Path inside the local Skill"),
) -> None:
    """Read a file from a local Skill directory."""
    content = _run_or_exit(
        lambda: read_local_skill_file(
            identifier,
            relative_path,
            settings.skills_extensions_dir,
        )
    )
    typer.echo(content, nl=False)


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
        _update_all(
            version=version,
            registry=registry,
            force=force,
            allow_rename=allow_rename,
        )
        return
    if slug is None:
        typer.echo("❌ Provide a Skill slug or use --all.", err=True)
        raise typer.Exit(code=1)
    effective_registry = _run_or_exit(lambda: _resolve_update_registry(slug, registry))
    if effective_registry is not None:
        _confirm_registry_url(effective_registry)
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
    typer.echo("available immediately through sebastian skills list/show/read.")


def _update_all(
    *,
    version: str | None,
    registry: str | None,
    force: bool,
    allow_rename: bool,
) -> None:
    installed = _run_or_exit(list_installed)
    targets = [skill for skill in installed if skill.managed]
    if not targets:
        typer.echo("No package-managed Skills to update.")
        return

    confirmed_registries: set[str] = set()
    for skill in targets:
        effective_registry = _effective_update_registry(skill, registry)
        if effective_registry is None or effective_registry in confirmed_registries:
            continue
        _confirm_registry_url(effective_registry)
        confirmed_registries.add(effective_registry)
    if force:
        typer.confirm("Overwrite local changes if present?", abort=True)
    if allow_rename:
        typer.confirm("Allow updates to rename runtime Skills?", abort=True)

    successes = 0
    failures = 0
    for skill in targets:
        try:
            result = update_skill(
                skill.slug,
                version=version,
                registry=registry,
                force=force,
                allow_rename=allow_rename,
            )
        except (SkillRegistryError, SkillInstallError, LockfileError, httpx.HTTPError) as exc:
            failures += 1
            typer.echo(f"❌ {skill.slug}: {exc}", err=True)
            continue
        successes += 1
        typer.echo(f"Updated {result.slug} as {result.registered_name}")

    typer.echo(f"Updated {successes} Skill(s); {failures} failed.")
    if failures:
        raise typer.Exit(code=1)


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

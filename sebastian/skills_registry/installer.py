from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from sebastian.capabilities.skills.metadata import (
    SkillMetadataError,
    parse_skill_metadata,
)
from sebastian.config import settings
from sebastian.skills_registry.client import SLUG_PATTERN, RegistryClient
from sebastian.skills_registry.lockfile import (
    LockfileEntry,
    SkillPackageLock,
    with_package_lock,
)
from sebastian.skills_registry.models import (
    InstalledSkill,
    InstallResult,
    LocalSkillDetail,
    RemoveResult,
)
from sebastian.skills_registry.safety import (
    ArchiveSafetyError,
    compute_package_fingerprint,
    safe_extract_zip,
)

ORIGIN_FILENAME = ".sebastian-origin.json"
HTTP_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_SIZE = 10 * 1_048_576
UNSAFE_STATUSES = {"malicious", "quarantined", "hidden", "suspicious", "blocked"}
logger = logging.getLogger(__name__)


class SkillInstallError(RuntimeError):
    pass


def list_installed(root: Path, *, builtin_dir: Path | None = None) -> list[InstalledSkill]:
    root = root.expanduser().resolve()
    builtin_root = _default_builtin_skills_dir() if builtin_dir is None else builtin_dir
    entries = SkillPackageLock(root).load()
    installed_by_registered_name: dict[str, InstalledSkill] = {}
    managed_paths: set[Path] = set()

    for registered_name, path in _scan_registered_name_owners(
        builtin_root,
        fail_closed=False,
    ).items():
        installed_by_registered_name[registered_name] = InstalledSkill(
            slug=path.name,
            registered_name=registered_name,
            version=None,
            registry=None,
            managed=False,
            path=path,
            source="builtin",
        )

    for slug, entry in entries.items():
        path = root / slug
        managed_paths.add(path.resolve())
        installed_by_registered_name[entry.registered_name] = InstalledSkill(
            slug=slug,
            registered_name=entry.registered_name,
            version=entry.version,
            registry=entry.registry,
            managed=True,
            path=path,
            source="managed",
        )

    for registered_name, path in _scan_registered_name_owners(root).items():
        if path.resolve() in managed_paths:
            continue
        installed_by_registered_name[registered_name] = InstalledSkill(
            slug=path.name,
            registered_name=registered_name,
            version=None,
            registry=None,
            managed=False,
            path=path,
            source="unmanaged",
        )

    return sorted(
        installed_by_registered_name.values(),
        key=lambda skill: (skill.source != "builtin", skill.slug),
    )


def show_local_skill(
    identifier: str,
    root: Path,
    *,
    builtin_dir: Path | None = None,
) -> LocalSkillDetail:
    matches = _find_local_skill_matches(
        identifier,
        list_installed(root, builtin_dir=builtin_dir),
    )
    if not matches:
        raise SkillInstallError(f"Local Skill {identifier!r} was not found")
    if len(matches) > 1:
        candidates = ", ".join(sorted(skill.slug for skill in matches))
        raise SkillInstallError(
            f"Local Skill {identifier!r} is ambiguous; matches: {candidates}"
        )

    skill = matches[0]
    skill_md = skill.path / "SKILL.md"
    try:
        content = skill_md.read_text(encoding="utf-8")
        metadata = parse_skill_metadata(content, fallback_name=skill.path.name)
    except (OSError, UnicodeDecodeError, SkillMetadataError) as exc:
        raise SkillInstallError(f"Invalid local Skill metadata at {skill_md}") from exc

    return LocalSkillDetail(
        slug=skill.slug,
        registered_name=metadata.registered_name,
        description=metadata.description,
        body=metadata.body,
        version=skill.version,
        registry=skill.registry,
        managed=skill.managed,
        source=skill.source,
        path=skill.path,
    )


def install_skill(
    slug: str,
    *,
    version: str | None,
    registry: str | None,
    force: bool,
    skills_root: Path | None = None,
) -> InstallResult:
    root = _default_skills_root() if skills_root is None else skills_root
    client = RegistryClient(registry)
    detail = client.inspect(slug, version=version)
    return _install_from_detail(
        client=client,
        detail=detail,
        requested_slug=slug,
        requested_version=version,
        skills_root=root,
        force=force,
        allow_rename=False,
        require_existing=False,
    )


def update_skill(
    slug: str,
    *,
    version: str | None,
    registry: str | None,
    force: bool,
    allow_rename: bool,
    skills_root: Path | None = None,
) -> InstallResult:
    root = _default_skills_root() if skills_root is None else skills_root
    entries = SkillPackageLock(root).load()
    existing = entries.get(slug)
    if existing is None:
        raise SkillInstallError(f"Skill {slug!r} is not package-managed")

    client = RegistryClient(registry or existing.registry)
    detail = client.inspect(slug, version=version)
    detail_version = getattr(detail, "version", None)
    if (root / slug).exists():
        _validate_local_fingerprint(
            existing,
            current_fingerprint=compute_package_fingerprint(root / slug),
            force=force,
        )
    if not force and isinstance(detail_version, str) and detail_version == existing.version:
        return InstallResult(
            slug=slug,
            registered_name=existing.registered_name,
            version=existing.version,
            path=root / slug,
        )
    return _install_from_detail(
        client=client,
        detail=detail,
        requested_slug=slug,
        requested_version=version,
        skills_root=root,
        force=force,
        allow_rename=allow_rename,
        require_existing=True,
    )


def remove_installed_skill(
    slug: str,
    *,
    yes: bool = False,
    skills_root: Path | None = None,
) -> RemoveResult:
    if not yes:
        raise SkillInstallError("Removing an installed Skill requires explicit confirmation")

    root = _default_skills_root() if skills_root is None else skills_root
    root.mkdir(parents=True, exist_ok=True)
    destination = root / slug
    lock = SkillPackageLock(root)

    with with_package_lock(root):
        entries = lock.load()
        entry = entries.get(slug)
        if entry is None:
            raise SkillInstallError(f"Skill {slug!r} is not package-managed")
        backup: Path | None = None
        if destination.exists():
            backup = _backup_path(destination)
            shutil.move(str(destination), str(backup))

        try:
            updated_entries = dict(entries)
            del updated_entries[slug]
            lock.save(updated_entries)
        except Exception:
            if backup is not None and backup.exists():
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.move(str(backup), str(destination))
            raise
        else:
            _cleanup_backup(backup)

    return RemoveResult(slug=slug, registered_name=entry.registered_name, path=destination)


def _install_from_detail(
    *,
    client: RegistryClient,
    detail: object,
    requested_slug: str,
    requested_version: str | None,
    skills_root: Path,
    force: bool,
    allow_rename: bool,
    require_existing: bool,
) -> InstallResult:
    detail_slug = str(getattr(detail, "slug"))
    detail_version = getattr(detail, "version", None)
    detail_version_text = detail_version if isinstance(detail_version, str) else None
    resolved_version = detail_version_text or requested_version
    detail_sha256 = getattr(detail, "sha256", None)
    registry_sha256 = (
        detail_sha256.strip().lower()
        if isinstance(detail_sha256, str) and detail_sha256.strip()
        else None
    )
    detail_status = getattr(detail, "security_status", None)
    detail_raw = getattr(detail, "raw")

    _validate_response_slug(requested_slug, detail_slug)
    _validate_security_status(detail_status)

    download_url = client.resolve_download_url(
        detail_raw,
        slug=requested_slug,
        version=resolved_version,
    )
    skills_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        dir=skills_root,
        prefix=f".{requested_slug}.install.",
    ) as temp_dir:
        temp_root = Path(temp_dir)
        archive = temp_root / "archive.zip"
        staging_root = temp_root / "staging"

        _download_archive(download_url, archive)
        archive_sha256 = _compute_archive_digest(archive)
        if registry_sha256 is None:
            logger.warning(
                "Registry detail for Skill %s has no sha256; recording local archive digest only",
                requested_slug,
            )
        elif archive_sha256 != registry_sha256:
            raise SkillInstallError("Downloaded archive sha256 does not match registry metadata")
        try:
            safe_extract_zip(archive, staging_root)
        except ArchiveSafetyError as exc:
            raise SkillInstallError(f"Skill archive failed safety validation: {exc}") from exc
        metadata = parse_skill_metadata(
            (staging_root / "SKILL.md").read_text(encoding="utf-8"),
            fallback_name=requested_slug,
        )
        timestamp = _utc_now()

        origin_payload: dict[str, object] = {
            "slug": requested_slug,
            "registered_name": metadata.registered_name,
            "registry": client.registry_url,
            "version": resolved_version,
            "sha256": archive_sha256,
            "sha256_verified": registry_sha256 is not None,
            "download_url": download_url,
            "installed_at": timestamp,
        }

        return _run_install_transaction(
            skills_root=skills_root,
            slug=requested_slug,
            registered_name=metadata.registered_name,
            staging_root=staging_root,
            origin_payload=origin_payload,
            lockfile_entry_factory=lambda fingerprint: LockfileEntry(
                slug=requested_slug,
                registered_name=metadata.registered_name,
                registry=client.registry_url,
                version=resolved_version,
                tag=None,
                sha256=archive_sha256,
                fingerprint=fingerprint,
                installed_at=timestamp,
            ),
            force=force,
            allow_rename=allow_rename,
            require_existing=require_existing,
        )


def _validate_registered_name_available(
    *,
    slug: str,
    registered_name: str,
    entries: dict[str, LockfileEntry],
    owners: dict[str, Path],
    destination: Path,
    force: bool,
) -> None:
    for existing_slug, entry in entries.items():
        if entry.registered_name != registered_name:
            continue
        if existing_slug == slug:
            return
        raise SkillInstallError(
            f"Skill registered name {registered_name!r} is already managed by {existing_slug!r}"
        )

    owner = owners.get(registered_name)
    if owner is None:
        return
    if owner.resolve() == destination.resolve():
        if slug not in entries and not force:
            raise SkillInstallError(
                f"Skill destination {destination.name!r} is unmanaged; retry with force=True "
                "to replace it"
            )
        return
    raise SkillInstallError(
        f"Skill registered name {registered_name!r} is already provided by {owner.name!r}"
    )


def _find_local_skill_matches(
    identifier: str,
    installed: list[InstalledSkill],
) -> list[InstalledSkill]:
    normalized = identifier[7:] if identifier.startswith("skill__") else identifier
    exact_slug = [skill for skill in installed if skill.slug == identifier]
    if exact_slug:
        return _prefer_local_override(exact_slug)
    exact_registered = [skill for skill in installed if skill.registered_name == identifier]
    if exact_registered:
        return _prefer_local_override(exact_registered)
    return [
        skill
        for skill in installed
        if skill.registered_name == f"skill__{normalized}"
    ]


def _prefer_local_override(matches: list[InstalledSkill]) -> list[InstalledSkill]:
    for source in ("managed", "unmanaged", "builtin"):
        preferred = [skill for skill in matches if skill.source == source]
        if preferred:
            return preferred
    return matches


def _scan_registered_name_owners(
    skills_root: Path,
    *,
    fail_closed: bool = True,
) -> dict[str, Path]:
    owners: dict[str, Path] = {}
    if not skills_root.exists():
        return owners

    for child in sorted(skills_root.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            metadata = parse_skill_metadata(
                skill_md.read_text(encoding="utf-8"),
                fallback_name=child.name,
            )
        except (OSError, UnicodeDecodeError, SkillMetadataError) as exc:
            if fail_closed:
                raise SkillInstallError(f"Invalid manual Skill metadata at {skill_md}") from exc
            logger.warning("Skipping invalid Skill metadata at %s: %s", skill_md, exc)
            continue
        owners[metadata.registered_name] = child
    return owners


def _validate_update_registered_name(
    entry: LockfileEntry,
    new_registered_name: str,
    *,
    allow_rename: bool,
) -> None:
    if entry.registered_name == new_registered_name or allow_rename:
        return
    raise SkillInstallError(
        "Update changes runtime tool name "
        f"from {entry.registered_name!r} to {new_registered_name!r}; "
        "retry with allow_rename=True if this is intentional"
    )


def _validate_archive_digest(archive: Path, *, expected_sha256: str) -> None:
    expected = expected_sha256.strip().lower()
    actual = _compute_archive_digest(archive)
    if actual != expected:
        raise SkillInstallError("Downloaded archive sha256 does not match registry metadata")


def _compute_archive_digest(archive: Path) -> str:
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def _validate_security_status(status: str | None) -> None:
    if status is None:
        return
    normalized = status.strip().lower()
    if normalized in UNSAFE_STATUSES:
        raise SkillInstallError(f"Registry marks this Skill as unsafe: {normalized}")


def _validate_response_slug(requested_slug: str, response_slug: str) -> None:
    if not SLUG_PATTERN.fullmatch(requested_slug):
        raise SkillInstallError("Requested Skill slug is invalid")
    if not SLUG_PATTERN.fullmatch(response_slug):
        raise SkillInstallError("Registry response slug is invalid")
    if response_slug != requested_slug:
        raise SkillInstallError(
            f"Registry response slug {response_slug!r} does not match requested slug "
            f"{requested_slug!r}"
        )


def _atomic_write_origin(destination: Path, payload: dict[str, object]) -> None:
    path = destination / ORIGIN_FILENAME
    temp_path = destination / f"{ORIGIN_FILENAME}.tmp"
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)
    _fsync_directory(destination)


def _validate_local_fingerprint(
    entry: LockfileEntry,
    *,
    current_fingerprint: str,
    force: bool,
) -> None:
    if force or entry.fingerprint == current_fingerprint:
        return
    raise SkillInstallError(
        f"Skill {entry.slug!r} has local changes; retry with force=True to overwrite"
    )


def _recoverable_directory_swap(staging: Path, destination: Path) -> Path | None:
    backup: Path | None = None
    if destination.exists():
        backup = _backup_path(destination)
        shutil.move(str(destination), str(backup))
    try:
        shutil.move(str(staging), str(destination))
    except Exception:
        if backup is not None and backup.exists():
            shutil.move(str(backup), str(destination))
        raise
    return backup


def _rollback_swap(destination: Path, backup: Path | None) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if backup is not None and backup.exists():
        shutil.move(str(backup), str(destination))


def _cleanup_backup(backup: Path | None) -> None:
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def _run_install_transaction(
    *,
    skills_root: Path,
    slug: str,
    registered_name: str,
    staging_root: Path,
    origin_payload: dict[str, object],
    lockfile_entry_factory: Callable[[str], LockfileEntry],
    force: bool,
    allow_rename: bool = False,
    require_existing: bool = False,
) -> InstallResult:
    skills_root.mkdir(parents=True, exist_ok=True)
    destination = skills_root / slug
    lock = SkillPackageLock(skills_root)

    with with_package_lock(skills_root):
        entries = lock.load()
        existing = entries.get(slug)
        if require_existing and existing is None:
            raise SkillInstallError(f"Skill {slug!r} is not package-managed")
        if existing is not None:
            if not require_existing and not force:
                raise SkillInstallError(
                    f"Skill {slug!r} is already installed; retry with force=True to overwrite"
                )
            _validate_update_registered_name(
                existing,
                registered_name,
                allow_rename=allow_rename,
            )
            if destination.exists():
                _validate_local_fingerprint(
                    existing,
                    current_fingerprint=compute_package_fingerprint(destination),
                    force=force,
                )

        owners = {
            owner_registered_name: owner_path
            for owner_registered_name, owner_path in _scan_registered_name_owners(
                skills_root
            ).items()
            if owner_path.resolve() != staging_root.resolve()
        }
        _validate_registered_name_available(
            slug=slug,
            registered_name=registered_name,
            entries=entries,
            owners=owners,
            destination=destination,
            force=force,
        )

        backup = _recoverable_directory_swap(staging_root, destination)
        try:
            _atomic_write_origin(destination, origin_payload)
            fingerprint = compute_package_fingerprint(destination)
            updated_entries = dict(entries)
            updated_entries[slug] = lockfile_entry_factory(fingerprint)
            lock.save(updated_entries)
        except Exception:
            _rollback_swap(destination, backup)
            raise
        else:
            _cleanup_backup(backup)

    result_version = origin_payload.get("version")
    return InstallResult(
        slug=slug,
        registered_name=registered_name,
        version=result_version if isinstance(result_version, str) else None,
        path=destination,
    )


def _download_archive(url: str, dest: Path) -> None:
    try:
        with httpx.Client(trust_env=True, timeout=HTTP_TIMEOUT_SECONDS) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                total_size = 0
                with dest.open("wb") as file:
                    for chunk in response.iter_bytes():
                        total_size += len(chunk)
                        if total_size > MAX_DOWNLOAD_SIZE:
                            raise SkillInstallError("Downloaded archive is too large")
                        file.write(chunk)
    except SkillInstallError:
        dest.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise SkillInstallError(f"Failed to download Skill archive: {exc}") from exc


def _default_skills_root() -> Path:
    return settings.skills_extensions_dir


def _default_builtin_skills_dir() -> Path:
    from sebastian.capabilities import skills as skills_pkg

    return Path(skills_pkg.__file__).parent


def _backup_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.backup.{uuid.uuid4().hex}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

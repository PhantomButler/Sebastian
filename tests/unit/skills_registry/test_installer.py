from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from sebastian.skills_registry.lockfile import (
    LockfileEntry,
    SkillPackageLock,
)
from sebastian.skills_registry.models import SkillDetail
from sebastian.skills_registry.safety import (
    ArchiveSafetyError,
    compute_package_fingerprint,
)


def _entry(
    slug: str = "flight",
    *,
    registered_name: str = "skill__flight",
    fingerprint: str = "fp",
    version: str | None = "1.0.0",
) -> LockfileEntry:
    return LockfileEntry(
        slug=slug,
        registered_name=registered_name,
        registry="https://clawhub.ai",
        version=version,
        tag=None,
        sha256="sha",
        fingerprint=fingerprint,
        installed_at="2026-05-08T00:00:00+00:00",
    )


def _write_skill(root: Path, *, name: str, description: str = "Demo") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nBody\n",
        encoding="utf-8",
    )


def test_registered_name_collision_rejects_different_managed_slug(
    tmp_path: Path,
) -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _validate_registered_name_available,
    )

    with pytest.raises(SkillInstallError, match="already managed"):
        _validate_registered_name_available(
            slug="weather-pack",
            registered_name="skill__travel",
            entries={"travel-pack": _entry("travel-pack", registered_name="skill__travel")},
            owners={},
            destination=tmp_path / "weather-pack",
            force=False,
        )


def test_registered_name_collision_allows_same_managed_slug(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import _validate_registered_name_available

    _validate_registered_name_available(
        slug="travel-pack",
        registered_name="skill__travel",
        entries={"travel-pack": _entry("travel-pack", registered_name="skill__travel")},
        owners={},
        destination=tmp_path / "travel-pack",
        force=False,
    )


def test_registered_name_collision_rejects_unmanaged_skill_directory(
    tmp_path: Path,
) -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _scan_registered_name_owners,
        _validate_registered_name_available,
    )

    manual = tmp_path / "manual-travel"
    _write_skill(manual, name="travel", description="Manual travel skill")

    owners = _scan_registered_name_owners(tmp_path)

    with pytest.raises(SkillInstallError, match="manual-travel"):
        _validate_registered_name_available(
            slug="foo-pack",
            registered_name="skill__travel",
            entries={},
            owners=owners,
            destination=tmp_path / "foo-pack",
            force=False,
        )


def test_install_rejects_unmanaged_same_slug_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    manual = tmp_path / "flight"
    _write_skill(manual, name="flight", description="Manual")
    before = (manual / "SKILL.md").read_text(encoding="utf-8")

    def fake_download_archive(url: str, dest: Path) -> None:
        dest.write_bytes(b"zip")

    def fake_extract(archive: Path, destination: Path) -> Path:
        _write_skill(destination, name="flight", description="Registry")
        return destination

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    with pytest.raises(installer.SkillInstallError, match="unmanaged"):
        installer.install_skill(
            "flight",
            version=None,
            registry="https://clawhub.ai",
            force=False,
            skills_root=tmp_path,
        )

    assert (manual / "SKILL.md").read_text(encoding="utf-8") == before
    assert not SkillPackageLock(tmp_path).load()


def test_install_allows_unmanaged_same_slug_with_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    manual = tmp_path / "flight"
    _write_skill(manual, name="flight", description="Manual")

    def fake_download_archive(url: str, dest: Path) -> None:
        dest.write_bytes(b"zip")

    def fake_extract(archive: Path, destination: Path) -> Path:
        _write_skill(destination, name="flight", description="Registry")
        return destination

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    result = installer.install_skill(
        "flight",
        version=None,
        registry="https://clawhub.ai",
        force=True,
        skills_root=tmp_path,
    )

    assert result.path == tmp_path / "flight"
    assert "Registry" in (manual / "SKILL.md").read_text(encoding="utf-8")
    assert "flight" in SkillPackageLock(tmp_path).load()


def test_collision_scan_fails_closed_on_invalid_manual_metadata(
    tmp_path: Path,
) -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _scan_registered_name_owners,
    )

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("---\nname: bad/name\n---\n", encoding="utf-8")

    with pytest.raises(SkillInstallError, match="Invalid manual Skill metadata"):
        _scan_registered_name_owners(tmp_path)


def test_update_registered_name_change_requires_confirmation() -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _validate_update_registered_name,
    )

    with pytest.raises(SkillInstallError, match="runtime tool name"):
        _validate_update_registered_name(
            _entry("flight"),
            "skill__airfare",
            allow_rename=False,
        )


def test_update_registered_name_change_allows_explicit_rename() -> None:
    from sebastian.skills_registry.installer import _validate_update_registered_name

    _validate_update_registered_name(
        _entry("flight"),
        "skill__airfare",
        allow_rename=True,
    )


@pytest.mark.parametrize(
    "status",
    ["malicious", " QUARANTINED ", "Hidden", "suspicious", "blocked"],
)
def test_unsafe_registry_status_is_rejected(status: str) -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _validate_security_status,
    )

    with pytest.raises(SkillInstallError, match="unsafe"):
        _validate_security_status(status)


def test_archive_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _validate_archive_digest,
    )

    archive = tmp_path / "skill.zip"
    archive.write_bytes(b"not-the-registry-archive")

    with pytest.raises(SkillInstallError, match="sha256"):
        _validate_archive_digest(archive, expected_sha256="0" * 64)


def test_archive_digest_match_is_accepted(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import _validate_archive_digest

    archive = tmp_path / "skill.zip"
    archive.write_bytes(b"registry-archive")

    _validate_archive_digest(
        archive,
        expected_sha256=hashlib.sha256(b"registry-archive").hexdigest(),
    )


def test_origin_json_is_written_atomically(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import _atomic_write_origin

    destination = tmp_path / "flight"
    destination.mkdir()

    _atomic_write_origin(destination, {"slug": "flight", "registry": "https://clawhub.ai"})

    assert json.loads((destination / ".sebastian-origin.json").read_text()) == {
        "registry": "https://clawhub.ai",
        "slug": "flight",
    }
    assert not (destination / ".sebastian-origin.json.tmp").exists()


def test_install_transaction_rolls_back_when_origin_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    destination = tmp_path / "flight"
    _write_skill(destination, name="old_flight", description="Old")
    staging = tmp_path / "staging"
    _write_skill(staging, name="flight", description="New")

    def fail_origin(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "_atomic_write_origin", fail_origin)

    with pytest.raises(OSError, match="disk full"):
        installer._run_install_transaction(
            skills_root=tmp_path,
            slug="flight",
            registered_name="skill__flight",
            staging_root=staging,
            origin_payload={"slug": "flight"},
            lockfile_entry_factory=lambda fingerprint: _entry(
                "flight",
                fingerprint=fingerprint,
            ),
            force=True,
        )

    assert "old_flight" in (destination / "SKILL.md").read_text(encoding="utf-8")
    assert not staging.exists()


def test_install_transaction_rolls_back_when_lockfile_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    destination = tmp_path / "flight"
    _write_skill(destination, name="old_flight", description="Old")
    staging = tmp_path / "staging"
    _write_skill(staging, name="flight", description="New")

    def fail_save(self: SkillPackageLock, entries: dict[str, LockfileEntry]) -> None:
        raise OSError("lockfile failed")

    monkeypatch.setattr(SkillPackageLock, "save", fail_save)

    with pytest.raises(OSError, match="lockfile failed"):
        installer._run_install_transaction(
            skills_root=tmp_path,
            slug="flight",
            registered_name="skill__flight",
            staging_root=staging,
            origin_payload={"slug": "flight"},
            lockfile_entry_factory=lambda fingerprint: _entry(
                "flight",
                fingerprint=fingerprint,
            ),
            force=True,
        )

    assert "old_flight" in (destination / "SKILL.md").read_text(encoding="utf-8")


def test_install_transaction_success_is_loader_visible(tmp_path: Path) -> None:
    from sebastian.capabilities.skills._loader import load_skills
    from sebastian.skills_registry.installer import _run_install_transaction

    staging = tmp_path / "staging"
    _write_skill(staging, name="flight", description="Flight search")

    result = _run_install_transaction(
        skills_root=tmp_path,
        slug="flight",
        registered_name="skill__flight",
        staging_root=staging,
        origin_payload={"slug": "flight"},
        lockfile_entry_factory=lambda fingerprint: _entry("flight", fingerprint=fingerprint),
        force=False,
    )

    assert result.path == tmp_path / "flight"
    assert (tmp_path / "flight" / "SKILL.md").is_file()
    assert "skill__flight" in {skill["name"] for skill in load_skills(builtin_dir=tmp_path)}


def test_install_existing_managed_slug_requires_force(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import SkillInstallError, _run_install_transaction

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight", description="Installed")
    existing_fingerprint = compute_package_fingerprint(destination)
    SkillPackageLock(tmp_path).save({"flight": _entry("flight", fingerprint=existing_fingerprint)})
    staging = tmp_path / "staging"
    _write_skill(staging, name="flight", description="Replacement")

    with pytest.raises(SkillInstallError, match="already installed"):
        _run_install_transaction(
            skills_root=tmp_path,
            slug="flight",
            registered_name="skill__flight",
            staging_root=staging,
            origin_payload={"slug": "flight"},
            lockfile_entry_factory=lambda fingerprint: _entry("flight", fingerprint=fingerprint),
            force=False,
        )

    assert "Installed" in (destination / "SKILL.md").read_text(encoding="utf-8")
    assert (staging / "SKILL.md").is_file()


def test_update_rejects_local_fingerprint_mismatch() -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        _validate_local_fingerprint,
    )

    with pytest.raises(SkillInstallError, match="local changes"):
        _validate_local_fingerprint(
            _entry("flight", fingerprint="expected"),
            current_fingerprint="actual",
            force=False,
        )


def test_update_allows_local_fingerprint_mismatch_with_force() -> None:
    from sebastian.skills_registry.installer import _validate_local_fingerprint

    _validate_local_fingerprint(
        _entry("flight", fingerprint="expected"),
        current_fingerprint="actual",
        force=True,
    )


def test_remove_transaction_removes_directory_and_lockfile_entry(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import remove_installed_skill

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight", description="Flight search")
    SkillPackageLock(tmp_path).save(
        {"flight": _entry("flight", fingerprint=compute_package_fingerprint(destination))}
    )

    result = remove_installed_skill("flight", skills_root=tmp_path, yes=True)

    assert result.slug == "flight"
    assert result.registered_name == "skill__flight"
    assert not destination.exists()
    assert "flight" not in SkillPackageLock(tmp_path).load()


def test_remove_transaction_rolls_back_when_lockfile_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry.installer import remove_installed_skill

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight")
    SkillPackageLock(tmp_path).save(
        {"flight": _entry("flight", fingerprint=compute_package_fingerprint(destination))}
    )

    def fail_save(self: SkillPackageLock, entries: dict[str, LockfileEntry]) -> None:
        raise OSError("lockfile failed")

    monkeypatch.setattr(SkillPackageLock, "save", fail_save)

    with pytest.raises(OSError, match="lockfile failed"):
        remove_installed_skill("flight", skills_root=tmp_path, yes=True)

    assert (destination / "SKILL.md").is_file()


def test_remove_deletes_even_when_local_fingerprint_changed(
    tmp_path: Path,
) -> None:
    from sebastian.skills_registry.installer import remove_installed_skill

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight")
    SkillPackageLock(tmp_path).save(
        {"flight": _entry("flight", fingerprint=compute_package_fingerprint(destination))}
    )
    (destination / "README.md").write_text("local edit", encoding="utf-8")

    result = remove_installed_skill("flight", skills_root=tmp_path, yes=True)

    assert result.slug == "flight"
    assert not destination.exists()
    assert "flight" not in SkillPackageLock(tmp_path).load()


def test_remove_rejects_unmanaged_manual_skill(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import (
        SkillInstallError,
        remove_installed_skill,
    )

    _write_skill(tmp_path / "manual", name="manual")

    with pytest.raises(SkillInstallError, match="not package-managed"):
        remove_installed_skill("manual", skills_root=tmp_path, yes=True)


def test_list_installed_merges_managed_and_unmanaged_skills(tmp_path: Path) -> None:
    from sebastian.skills_registry.installer import list_installed

    managed = tmp_path / "flight"
    unmanaged = tmp_path / "manual"
    _write_skill(managed, name="flight", description="Flight search")
    _write_skill(unmanaged, name="manual", description="Manual")
    SkillPackageLock(tmp_path).save({"flight": _entry("flight", version="1.2.3")})

    installed = list_installed(tmp_path)

    assert len(installed) == 2
    assert any(
        item.slug == "flight"
        and item.registered_name == "skill__flight"
        and item.version == "1.2.3"
        and item.registry == "https://clawhub.ai"
        and item.managed is True
        and item.path == managed
        for item in installed
    )
    assert any(
        item.slug == "manual"
        and item.registered_name == "skill__manual"
        and item.version is None
        and item.registry is None
        and item.managed is False
        and item.path == unmanaged
        for item in installed
    )


def test_install_transaction_holds_package_lock_across_all_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    locked = False
    events: list[str] = []
    staging = tmp_path / "staging"
    _write_skill(staging, name="flight")

    @contextlib.contextmanager
    def fake_package_lock(root: Path) -> Iterator[None]:
        nonlocal locked
        assert root == tmp_path
        locked = True
        events.append("lock_enter")
        try:
            yield
        finally:
            events.append("lock_exit")
            locked = False

    def record(event: str) -> None:
        assert locked
        events.append(event)

    class FakeLock:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path

        def load(self) -> dict[str, LockfileEntry]:
            record("load")
            return {}

        def save(self, entries: dict[str, LockfileEntry]) -> None:
            assert "flight" in entries
            record("save")

    def fake_validate(**kwargs: object) -> None:
        record("validate")

    def fake_swap(staging_arg: Path, destination: Path) -> Path | None:
        assert staging_arg == staging
        assert destination == tmp_path / "flight"
        record("swap")
        return tmp_path / ".backup"

    def fake_origin(destination: Path, payload: dict[str, object]) -> None:
        assert destination == tmp_path / "flight"
        record("origin")

    def fake_fingerprint(destination: Path) -> str:
        assert destination == tmp_path / "flight"
        record("fingerprint")
        return "fp"

    def fake_cleanup(backup: Path | None) -> None:
        assert backup == tmp_path / ".backup"
        record("cleanup")

    monkeypatch.setattr(installer, "with_package_lock", fake_package_lock)
    monkeypatch.setattr(installer, "SkillPackageLock", FakeLock)
    monkeypatch.setattr(installer, "_validate_registered_name_available", fake_validate)
    monkeypatch.setattr(installer, "_recoverable_directory_swap", fake_swap)
    monkeypatch.setattr(installer, "_atomic_write_origin", fake_origin)
    monkeypatch.setattr(installer, "compute_package_fingerprint", fake_fingerprint)
    monkeypatch.setattr(installer, "_cleanup_backup", fake_cleanup)

    installer._run_install_transaction(
        skills_root=tmp_path,
        slug="flight",
        registered_name="skill__flight",
        staging_root=staging,
        origin_payload={"slug": "flight"},
        lockfile_entry_factory=lambda fingerprint: _entry("flight", fingerprint=fingerprint),
        force=False,
    )

    assert events == [
        "lock_enter",
        "load",
        "validate",
        "swap",
        "origin",
        "fingerprint",
        "save",
        "cleanup",
        "lock_exit",
    ]


@dataclass(frozen=True)
class _FakeClient:
    registry_url: str | None = None

    def inspect(self, slug: str, *, version: str | None = None) -> SkillDetail:
        return SkillDetail(
            slug=slug,
            name="Flight",
            description="Flight skill",
            version=version or "1.0.0",
            download_url="https://clawhub.ai/flight.zip",
            sha256=hashlib.sha256(b"zip").hexdigest(),
            security_status="safe",
            raw={"download_url": "https://clawhub.ai/flight.zip"},
        )

    def resolve_download_url(
        self,
        data: dict[str, object],
        *,
        slug: str,
        version: str | None,
    ) -> str:
        return str(data["download_url"])


@dataclass(frozen=True)
class _FakeClientWithResponseSlug:
    registry_url: str | None = None

    def inspect(self, slug: str, *, version: str | None = None) -> SkillDetail:
        return SkillDetail(
            slug=_RESPONSE_SLUG,
            name="Flight",
            description="Flight skill",
            version=version or "1.0.0",
            download_url="https://clawhub.ai/flight.zip",
            sha256=hashlib.sha256(b"zip").hexdigest(),
            security_status="safe",
            raw={"download_url": "https://clawhub.ai/flight.zip"},
        )

    def resolve_download_url(
        self,
        data: dict[str, object],
        *,
        slug: str,
        version: str | None,
    ) -> str:
        return str(data["download_url"])


_RESPONSE_SLUG = "flight"


@dataclass(frozen=True)
class _FakeClientWithoutDigest:
    registry_url: str | None = None

    def inspect(self, slug: str, *, version: str | None = None) -> SkillDetail:
        return SkillDetail(
            slug=slug,
            name="Flight",
            description="Flight skill",
            version=version or "1.0.0",
            download_url="https://clawhub.ai/flight.zip",
            sha256=None,
            security_status="safe",
            raw={"download_url": "https://clawhub.ai/flight.zip"},
        )

    def resolve_download_url(
        self,
        data: dict[str, object],
        *,
        slug: str,
        version: str | None,
    ) -> str:
        return str(data["download_url"])


@dataclass(frozen=True)
class _FakeClientWithoutVersionEcho:
    registry_url: str | None = None

    def inspect(self, slug: str, *, version: str | None = None) -> SkillDetail:
        return SkillDetail(
            slug=slug,
            name="Flight",
            description="Flight skill",
            version=None,
            download_url=None,
            sha256=hashlib.sha256(b"zip").hexdigest(),
            security_status="safe",
            raw={},
        )

    def resolve_download_url(
        self,
        data: dict[str, object],
        *,
        slug: str,
        version: str | None,
    ) -> str:
        assert version == "1.2.3"
        return f"https://clawhub.ai/api/v1/download?slug={slug}&version={version}"


def test_install_skill_uses_registry_download_digest_and_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    def fake_download_archive(url: str, dest: Path) -> None:
        assert url == "https://clawhub.ai/flight.zip"
        dest.write_bytes(b"zip")

    def fake_extract(archive: Path, destination: Path) -> Path:
        assert archive.read_bytes() == b"zip"
        _write_skill(destination, name="flight")
        return destination

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    result = installer.install_skill(
        "flight",
        version=None,
        registry="https://clawhub.ai",
        force=False,
        skills_root=tmp_path,
    )

    assert result.slug == "flight"
    assert result.registered_name == "skill__flight"
    assert result.version == "1.0.0"
    assert result.path == tmp_path / "flight"
    assert (result.path / "SKILL.md").is_file()
    assert (result.path / ".sebastian-origin.json").is_file()


def test_install_skill_requested_version_used_when_detail_omits_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    def fake_download_archive(url: str, dest: Path) -> None:
        assert url == "https://clawhub.ai/api/v1/download?slug=flight&version=1.2.3"
        dest.write_bytes(b"zip")

    def fake_extract(archive: Path, destination: Path) -> Path:
        _write_skill(destination, name="flight")
        return destination

    monkeypatch.setattr(installer, "RegistryClient", _FakeClientWithoutVersionEcho)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    installer.install_skill(
        "flight",
        version="1.2.3",
        registry="https://clawhub.ai",
        force=False,
        skills_root=tmp_path,
    )


def test_update_skill_current_version_noops_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight")
    SkillPackageLock(tmp_path).save(
        {"flight": _entry("flight", fingerprint=compute_package_fingerprint(destination))}
    )

    def fail_install_from_detail(*args: object, **kwargs: object) -> None:
        raise AssertionError("current-version update should not download or replace")

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)
    monkeypatch.setattr(installer, "_install_from_detail", fail_install_from_detail)

    result = installer.update_skill(
        "flight",
        version=None,
        registry=None,
        force=False,
        allow_rename=False,
        skills_root=tmp_path,
    )

    assert result.slug == "flight"
    assert result.registered_name == "skill__flight"
    assert result.version == "1.0.0"
    assert result.path == destination


def test_update_skill_current_version_still_rejects_local_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight")
    SkillPackageLock(tmp_path).save(
        {"flight": _entry("flight", fingerprint=compute_package_fingerprint(destination))}
    )
    (destination / "README.md").write_text("local edit", encoding="utf-8")

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)

    with pytest.raises(installer.SkillInstallError, match="local changes"):
        installer.update_skill(
            "flight",
            version=None,
            registry=None,
            force=False,
            allow_rename=False,
            skills_root=tmp_path,
        )


def test_update_skill_current_version_force_still_replaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    destination = tmp_path / "flight"
    _write_skill(destination, name="flight")
    SkillPackageLock(tmp_path).save(
        {"flight": _entry("flight", fingerprint=compute_package_fingerprint(destination))}
    )
    calls: list[bool] = []

    def fake_install_from_detail(
        *,
        client: object,
        detail: object,
        requested_slug: str,
        requested_version: str | None,
        skills_root: Path,
        force: bool,
        allow_rename: bool,
        require_existing: bool,
    ) -> object:
        calls.append(force)
        return installer.InstallResult(
            slug=requested_slug,
            registered_name="skill__flight",
            version="1.0.0",
            path=skills_root / requested_slug,
        )

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)
    monkeypatch.setattr(installer, "_install_from_detail", fake_install_from_detail)

    installer.update_skill(
        "flight",
        version=None,
        registry=None,
        force=True,
        allow_rename=False,
        skills_root=tmp_path,
    )

    assert calls == [True]


def test_install_skill_without_registry_digest_records_local_archive_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    def fake_download_archive(url: str, dest: Path) -> None:
        dest.write_bytes(b"zip-without-registry-digest")

    def fake_extract(archive: Path, destination: Path) -> Path:
        _write_skill(destination, name="flight")
        return destination

    monkeypatch.setattr(installer, "RegistryClient", _FakeClientWithoutDigest)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    result = installer.install_skill(
        "flight",
        version=None,
        registry="https://clawhub.ai",
        force=False,
        skills_root=tmp_path,
    )

    expected_sha = hashlib.sha256(b"zip-without-registry-digest").hexdigest()
    origin = json.loads((result.path / ".sebastian-origin.json").read_text(encoding="utf-8"))
    entry = SkillPackageLock(tmp_path).load()["flight"]
    assert origin["sha256"] == expected_sha
    assert origin["sha256_verified"] is False
    assert entry.sha256 == expected_sha


def test_install_skill_wraps_archive_safety_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    def fake_download_archive(url: str, dest: Path) -> None:
        dest.write_bytes(b"zip")

    def fake_extract(archive: Path, destination: Path) -> Path:
        raise ArchiveSafetyError("path traversal")

    monkeypatch.setattr(installer, "RegistryClient", _FakeClient)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    with pytest.raises(installer.SkillInstallError, match="path traversal"):
        installer.install_skill(
            "flight",
            version=None,
            registry="https://clawhub.ai",
            force=False,
            skills_root=tmp_path,
        )


@pytest.mark.parametrize("response_slug", ["../evil", "different"])
def test_install_rejects_malicious_or_mismatched_response_slug_without_touching_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response_slug: str,
) -> None:
    from sebastian.skills_registry import installer

    skills_root = tmp_path / "skills"
    outside = tmp_path / "evil"
    global _RESPONSE_SLUG
    _RESPONSE_SLUG = response_slug

    def fake_download_archive(url: str, dest: Path) -> None:
        dest.write_bytes(b"zip")

    def fake_extract(archive: Path, destination: Path) -> Path:
        _write_skill(destination, name="flight")
        return destination

    monkeypatch.setattr(installer, "RegistryClient", _FakeClientWithResponseSlug)
    monkeypatch.setattr(installer, "_download_archive", fake_download_archive)
    monkeypatch.setattr(installer, "safe_extract_zip", fake_extract)

    with pytest.raises(installer.SkillInstallError, match="slug"):
        installer.install_skill(
            "flight",
            version=None,
            registry="https://clawhub.ai",
            force=False,
            skills_root=skills_root,
        )

    assert not outside.exists()
    assert not (skills_root / "different").exists()
    assert not (skills_root / "flight").exists()


def test_download_archive_rejects_oversized_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    monkeypatch.setattr(installer, "MAX_DOWNLOAD_SIZE", 3)
    monkeypatch.setattr(installer.httpx, "Client", _fake_httpx_client([b"12", b"34"]))

    with pytest.raises(installer.SkillInstallError, match="too large"):
        installer._download_archive("https://clawhub.ai/flight.zip", tmp_path / "skill.zip")


def test_download_archive_wraps_network_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sebastian.skills_registry import installer

    class FailingClient:
        def __init__(self, *, trust_env: bool, timeout: int) -> None:
            pass

        def __enter__(self) -> FailingClient:
            raise httpx.ConnectError("network down")

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(installer.httpx, "Client", FailingClient)

    with pytest.raises(installer.SkillInstallError, match="download"):
        installer._download_archive("https://clawhub.ai/flight.zip", tmp_path / "skill.zip")


def _fake_httpx_client(chunks: Iterable[bytes]) -> type[object]:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self) -> Iterator[bytes]:
            yield from chunks

    class FakeClient:
        def __init__(self, *, trust_env: bool, timeout: int) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def stream(self, method: str, url: str) -> FakeResponse:
            assert method == "GET"
            assert url == "https://clawhub.ai/flight.zip"
            return FakeResponse()

    return FakeClient

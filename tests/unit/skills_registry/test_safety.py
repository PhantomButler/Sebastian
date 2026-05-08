from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from sebastian.skills_registry.safety import (
    ArchiveSafetyError,
    compute_package_fingerprint,
    safe_extract_zip,
)


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    archive = path / "skill.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return archive


def test_safe_extract_zip_rejects_path_traversal(tmp_path: Path) -> None:
    archive = _zip(
        tmp_path,
        {
            "SKILL.md": b"---\nname: demo\n---\nDemo",
            "../evil": b"owned",
        },
    )

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "extract")

    assert not (tmp_path / "evil").exists()


def test_safe_extract_zip_accepts_root_skill_md(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {"SKILL.md": b"---\nname: demo\n---\nDemo"})

    root = safe_extract_zip(archive, tmp_path / "extract")

    assert root == tmp_path / "extract"


def test_safe_extract_zip_accepts_single_root_skill_md(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {"demo/SKILL.md": b"---\nname: demo\n---\nDemo"})

    root = safe_extract_zip(archive, tmp_path / "extract")

    assert root == tmp_path / "extract" / "demo"


def test_safe_extract_zip_requires_root_level_or_single_root_skill_md(
    tmp_path: Path,
) -> None:
    archive = _zip(
        tmp_path,
        {
            "demo/SKILL.md": b"---\nname: demo\n---\nDemo",
            "other/SKILL.md": b"---\nname: other\n---\nOther",
        },
    )

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "extract")


def test_safe_extract_zip_rejects_archive_without_skill_md(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {"skill/README.md": b"# Skill"})

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "extract")


def test_safe_extract_zip_cleans_destination_when_skill_md_missing(
    tmp_path: Path,
) -> None:
    archive = _zip(tmp_path, {"skill/README.md": b"# Skill"})
    destination = tmp_path / "extract"

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, destination)

    assert list(destination.iterdir()) == []


@pytest.mark.parametrize(
    "skill_md",
    [
        b"\xff\xfe\x00",
        b"---\nname: bad/name\n---\nDemo",
    ],
)
def test_safe_extract_zip_cleans_destination_when_skill_md_invalid(
    tmp_path: Path,
    skill_md: bytes,
) -> None:
    archive = _zip(
        tmp_path,
        {
            "SKILL.md": skill_md,
            "README.md": b"# Demo",
        },
    )
    destination = tmp_path / "extract"

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, destination)

    assert list(destination.iterdir()) == []


def test_compute_package_fingerprint_excludes_manager_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: demo\n---\nDemo", encoding="utf-8")

    before = compute_package_fingerprint(root)

    (root / ".sebastian-origin.json").write_text("{}", encoding="utf-8")
    manager_dir = root / ".sebastian"
    manager_dir.mkdir()
    (manager_dir / "install.json").write_text("{}", encoding="utf-8")

    assert compute_package_fingerprint(root) == before


def test_compute_package_fingerprint_includes_regular_files(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: demo\n---\nDemo", encoding="utf-8")

    before = compute_package_fingerprint(root)
    (root / "README.md").write_text("read me", encoding="utf-8")

    assert compute_package_fingerprint(root) != before


def test_safe_extract_zip_rejects_symlink_entries(tmp_path: Path) -> None:
    archive = tmp_path / "skill.zip"
    info = zipfile.ZipInfo("link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("SKILL.md", b"---\nname: demo\n---\nDemo")
        zf.writestr(info, b"target")

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "extract")


def test_safe_extract_zip_rejects_special_file_entries(tmp_path: Path) -> None:
    archive = tmp_path / "skill.zip"
    info = zipfile.ZipInfo("pipe")
    info.external_attr = (stat.S_IFIFO | 0o644) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("SKILL.md", b"---\nname: demo\n---\nDemo")
        zf.writestr(info, b"")

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "extract")


def test_safe_extract_zip_rejects_binary_skill_md(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {"SKILL.md": b"\xff\xfe\x00"})

    with pytest.raises(ArchiveSafetyError, match="SKILL.md must be UTF-8 text"):
        safe_extract_zip(archive, tmp_path / "extract")


def test_safe_extract_zip_rejects_invalid_skill_md_frontmatter_name(
    tmp_path: Path,
) -> None:
    archive = _zip(tmp_path, {"SKILL.md": b"---\nname: bad/name\n---\nDemo"})

    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "extract")

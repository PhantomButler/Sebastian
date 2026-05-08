from __future__ import annotations

import hashlib
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from sebastian.capabilities.skills.metadata import (
    SkillMetadataError,
    parse_skill_metadata,
)

MAX_FILES = 200
MAX_FILE_SIZE = 1_048_576
MAX_TOTAL_SIZE = 5 * 1_048_576
MANAGER_METADATA = {".sebastian-origin.json"}


class ArchiveSafetyError(RuntimeError):
    pass


def safe_extract_zip(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        dir=destination.parent,
        prefix=f".{destination.name}-",
    ) as temp_dir:
        temp_destination = Path(temp_dir)
        temp_root = temp_destination.resolve()

        with zipfile.ZipFile(archive) as zf:
            _validate_zip_infos(zf.infolist(), temp_root)
            zf.extractall(temp_destination)

        root = _validate_extracted_skill_root(temp_destination)
        for child in root.iterdir():
            shutil.move(str(child), destination / child.name)

    return destination


def _validate_extracted_skill_root(destination: Path) -> Path:
    root = _find_skill_root(destination)
    skill_md = root / "SKILL.md"
    try:
        content = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveSafetyError("SKILL.md must be UTF-8 text") from exc

    try:
        parse_skill_metadata(content, fallback_name=root.name)
    except SkillMetadataError as exc:
        raise ArchiveSafetyError(str(exc)) from exc

    return root


def compute_package_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root)
        if _is_manager_metadata(relative):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_zip_infos(infos: list[zipfile.ZipInfo], destination_root: Path) -> None:
    file_count = 0
    total_size = 0
    for info in infos:
        if _zipinfo_is_symlink(info):
            raise ArchiveSafetyError("Archive must not contain symlinks")
        if _zipinfo_is_special_file(info):
            raise ArchiveSafetyError("Archive must not contain special files")

        target = (destination_root / info.filename).resolve()
        if not _is_relative_to(target, destination_root):
            raise ArchiveSafetyError("Archive contains path traversal")

        if info.is_dir():
            continue

        file_count += 1
        if file_count > MAX_FILES:
            raise ArchiveSafetyError(f"Archive must contain at most {MAX_FILES} files")
        if info.file_size > MAX_FILE_SIZE:
            raise ArchiveSafetyError(f"Archive file exceeds maximum size of {MAX_FILE_SIZE} bytes")
        total_size += info.file_size
        if total_size > MAX_TOTAL_SIZE:
            raise ArchiveSafetyError(
                f"Archive exceeds maximum total size of {MAX_TOTAL_SIZE} bytes"
            )


def _find_skill_root(destination: Path) -> Path:
    root_skill = destination / "SKILL.md"
    if root_skill.is_file():
        return destination

    children = list(destination.iterdir())
    if len(children) == 1 and children[0].is_dir() and (children[0] / "SKILL.md").is_file():
        return children[0]
    raise ArchiveSafetyError("Archive must contain root-level or single-root SKILL.md")


def _is_manager_metadata(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    return parts[0] in MANAGER_METADATA or parts[0] == ".sebastian"


def _zipinfo_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = _zipinfo_mode(info)
    return stat.S_ISLNK(mode)


def _zipinfo_is_special_file(info: zipfile.ZipInfo) -> bool:
    mode = _zipinfo_mode(info)
    file_type = stat.S_IFMT(mode)
    if file_type == 0:
        return False
    return not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode))


def _zipinfo_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

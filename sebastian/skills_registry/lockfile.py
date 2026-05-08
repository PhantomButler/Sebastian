from __future__ import annotations

import contextlib
import dataclasses
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

LOCKFILE_NAME = ".sebastian-skills.lock.json"
MUTEX_NAME = ".sebastian-skills.lock"
LOCKFILE_VERSION = 1


class LockfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class LockfileEntry:
    slug: str
    registered_name: str
    registry: str
    version: str | None
    tag: str | None
    sha256: str | None
    fingerprint: str
    installed_at: str


@contextlib.contextmanager
def with_package_lock(root: Path) -> Iterator[None]:
    try:
        import fcntl
    except ImportError as exc:
        raise RuntimeError("Skill package lock requires POSIX fcntl.flock support") from exc

    root.mkdir(parents=True, exist_ok=True)
    mutex_path = root / MUTEX_NAME
    with mutex_path.open("a+b") as mutex_file:
        fcntl.flock(mutex_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(mutex_file.fileno(), fcntl.LOCK_UN)


class SkillPackageLock:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / LOCKFILE_NAME

    def load(self) -> dict[str, LockfileEntry]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open(encoding="utf-8") as file:
                data = json.load(file)
        except JSONDecodeError as exc:
            raise LockfileError("Skill package lockfile contains malformed JSON") from exc
        if not isinstance(data, dict):
            raise LockfileError("Skill package lockfile root must be an object")
        if data.get("version") != LOCKFILE_VERSION:
            raise LockfileError("Unsupported skill package lockfile version")
        skills = data.get("skills")
        if not isinstance(skills, dict):
            raise LockfileError("Skill package lockfile skills must be an object")
        entries: dict[str, LockfileEntry] = {}
        for slug, raw_entry in skills.items():
            if not isinstance(slug, str):
                raise LockfileError("Skill package lockfile skill slugs must be strings")
            if not isinstance(raw_entry, dict):
                raise LockfileError(f"Malformed lockfile entry for skill {slug!r}")
            try:
                entries[slug] = LockfileEntry(**raw_entry)
            except TypeError as exc:
                raise LockfileError(f"Malformed lockfile entry for skill {slug!r}") from exc
        return entries

    def save(self, entries: dict[str, LockfileEntry]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": LOCKFILE_VERSION,
            "skills": {slug: dataclasses.asdict(entry) for slug, entry in sorted(entries.items())},
        }
        _atomic_write_json(self.path, payload)

    def update_entry(self, entry: LockfileEntry) -> None:
        with with_package_lock(self.root):
            entries = self.load()
            entries[entry.slug] = entry
            self.save(entries)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class SkillFileFingerprint:
    relative_path: str
    mtime_ns: int
    size: int


SkillFingerprint = tuple[SkillFileFingerprint, ...]


@dataclass(frozen=True)
class SkillReloadResult:
    changed: bool
    version: int
    fingerprint: SkillFingerprint
    error: str | None = None


def compute_skill_fingerprint(
    builtin_dir: Path,
    extra_dirs: list[Path] | None = None,
) -> SkillFingerprint:
    entries: list[SkillFileFingerprint] = []
    for base in _skill_dirs(builtin_dir, extra_dirs or []):
        if not base.exists():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            stat = skill_md.stat()
            relative_path = f"{base.resolve()}::{skill_md.relative_to(base)}"
            entries.append(
                SkillFileFingerprint(
                    relative_path=relative_path,
                    mtime_ns=stat.st_mtime_ns,
                    size=stat.st_size,
                )
            )
    return tuple(sorted(entries))


def _skill_dirs(builtin_dir: Path, extra_dirs: list[Path]) -> list[Path]:
    return [builtin_dir, *extra_dirs]


class SkillHotReloader:
    def __init__(
        self,
        *,
        builtin_dir: Path,
        extra_dirs: list[Path] | None = None,
        fingerprint: SkillFingerprint | None = None,
        version: int = 0,
    ) -> None:
        self._builtin_dir = builtin_dir
        self._extra_dirs = extra_dirs or []
        self._fingerprint = (
            fingerprint
            if fingerprint is not None
            else compute_skill_fingerprint(builtin_dir, self._extra_dirs)
        )
        self._version = version
        self._lock = asyncio.Lock()

    @classmethod
    def seeded(
        cls,
        *,
        builtin_dir: Path,
        extra_dirs: list[Path] | None = None,
    ) -> SkillHotReloader:
        return cls(
            builtin_dir=builtin_dir,
            extra_dirs=extra_dirs,
            fingerprint=compute_skill_fingerprint(builtin_dir, extra_dirs or []),
            version=0,
        )

    @property
    def version(self) -> int:
        return self._version

    async def maybe_reload(self) -> SkillReloadResult:
        async with self._lock:
            try:
                latest = compute_skill_fingerprint(self._builtin_dir, self._extra_dirs)
            except Exception:
                logger.warning("Skill hot reload failed", exc_info=True)
                return SkillReloadResult(
                    changed=False,
                    version=self._version,
                    fingerprint=self._fingerprint,
                    error="Skill hot reload failed",
                )
            if latest == self._fingerprint:
                return SkillReloadResult(
                    changed=False,
                    version=self._version,
                    fingerprint=latest,
                )

            self._fingerprint = latest
            self._version += 1
            return SkillReloadResult(
                changed=True,
                version=self._version,
                fingerprint=latest,
            )

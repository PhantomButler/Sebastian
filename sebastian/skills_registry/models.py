from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class SkillRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillSearchResult:
    slug: str
    name: str
    description: str
    latest_version: str | None = None
    security_status: str | None = None


@dataclass(frozen=True)
class SkillDetail:
    slug: str
    name: str
    description: str
    version: str | None
    download_url: str | None
    sha256: str | None
    security_status: str | None
    raw: dict[str, object]


@dataclass(frozen=True)
class InstalledSkill:
    slug: str
    registered_name: str
    version: str | None
    registry: str | None
    managed: bool
    path: Path
    source: str = "managed"
    description: str = ""
    name: str = ""


@dataclass(frozen=True)
class LocalSkillDetail:
    slug: str
    name: str
    registered_name: str
    description: str
    body: str
    files: tuple[str, ...]
    version: str | None
    registry: str | None
    managed: bool
    source: str
    path: Path


@dataclass(frozen=True)
class InstallResult:
    slug: str
    registered_name: str
    version: str | None
    path: Path


@dataclass(frozen=True)
class RemoveResult:
    slug: str
    registered_name: str
    path: Path

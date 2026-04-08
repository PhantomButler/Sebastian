from __future__ import annotations

import os
import secrets
from pathlib import Path


class SecretKeyManager:
    """Manage the JWT signing secret stored at a single file (chmod 600)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def generate(self) -> str:
        if self._path.exists():
            raise FileExistsError(f"Secret key already exists at {self._path}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(self._path, flags, 0o600)
        try:
            os.write(fd, key.encode("utf-8"))
        finally:
            os.close(fd)
        return key

    def read(self) -> str:
        if not self._path.exists():
            raise FileNotFoundError(f"Secret key not found at {self._path}")
        return self._path.read_text(encoding="utf-8").strip()

from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.gateway.setup.secret_key import SecretKeyManager


def test_generate_creates_file_with_600_permission(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)

    key = mgr.generate()

    assert target.exists()
    assert len(key) >= 32
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_generate_is_idempotent_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)
    mgr.generate()

    with pytest.raises(FileExistsError):
        mgr.generate()


def test_read_returns_persisted_key(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)
    generated = mgr.generate()

    assert mgr.read() == generated


def test_read_raises_when_missing(tmp_path: Path) -> None:
    mgr = SecretKeyManager(tmp_path / "nope.key")

    with pytest.raises(FileNotFoundError):
        mgr.read()


def test_exists_reflects_file_presence(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)

    assert mgr.exists() is False
    mgr.generate()
    assert mgr.exists() is True


def test_generate_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "secret.key"
    mgr = SecretKeyManager(target)

    mgr.generate()

    assert target.exists()

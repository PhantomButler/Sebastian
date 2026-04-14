from __future__ import annotations

from pathlib import Path

from sebastian.config import Settings


def test_secret_key_path_default_uses_data_dir() -> None:
    s = Settings(sebastian_data_dir="/tmp/sebx")
    assert s.resolved_secret_key_path() == Path("/tmp/sebx/secret.key")


def test_secret_key_path_explicit_override() -> None:
    s = Settings(
        sebastian_data_dir="/tmp/sebx",
        sebastian_secret_key_path="/etc/sebastian/secret.key",
    )
    assert s.resolved_secret_key_path() == Path("/etc/sebastian/secret.key")


def test_secret_key_path_expands_tilde() -> None:
    s = Settings(sebastian_secret_key_path="~/custom/secret.key")
    assert s.resolved_secret_key_path() == Path("~/custom/secret.key").expanduser()

from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.gateway.auth import JwtSigner


def test_signer_reads_secret_from_file(tmp_path: Path) -> None:
    key_file = tmp_path / "secret.key"
    key_file.write_text("file-secret-abc")

    signer = JwtSigner(secret_key_path=key_file, algorithm="HS256", expire_minutes=60)
    token = signer.encode({"sub": "eric"})
    payload = signer.decode(token)

    assert payload["sub"] == "eric"


def test_signer_refuses_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent.key"

    with pytest.raises(RuntimeError, match="Secret key file not found"):
        JwtSigner(
            secret_key_path=missing,
            algorithm="HS256",
            expire_minutes=60,
        )

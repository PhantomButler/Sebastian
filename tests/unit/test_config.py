from __future__ import annotations

import os
import pytest


def test_settings_defaults():
    """Settings should load with sane defaults even without a .env file."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    from sebastian.config import Settings

    s = Settings()
    assert s.sebastian_gateway_port == 8000
    assert s.sebastian_jwt_algorithm == "HS256"
    assert s.sebastian_owner_name == "Owner"
    assert "sqlite" in s.database_url


def test_database_url_uses_data_dir(tmp_path):
    """database_url should embed the data dir path."""
    from sebastian.config import Settings

    s = Settings(sebastian_data_dir=str(tmp_path))
    assert str(tmp_path) in s.database_url


def test_jwt_create_and_decode():
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    from sebastian.gateway.auth import create_access_token, decode_token
    token = create_access_token({"sub": "owner", "role": "owner"})
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload["sub"] == "owner"
    assert payload["role"] == "owner"


def test_jwt_invalid_token_raises():
    from fastapi import HTTPException
    from sebastian.gateway.auth import decode_token
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.valid.token")
    assert exc_info.value.status_code == 401


def test_hash_and_verify_password():
    from sebastian.gateway.auth import hash_password, verify_password
    hashed = hash_password("secretpassword")
    assert verify_password("secretpassword", hashed)
    assert not verify_password("wrongpassword", hashed)

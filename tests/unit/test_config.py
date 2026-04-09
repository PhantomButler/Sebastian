from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_settings_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Settings should load with sane defaults even without a .env file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from sebastian.config import Settings

    s = Settings()
    assert s.sebastian_gateway_port == 8823
    assert s.sebastian_jwt_algorithm == "HS256"
    assert s.sebastian_owner_name == "Owner"
    assert "sqlite" in s.database_url


def test_database_url_uses_data_dir(tmp_path: Path) -> None:
    """database_url should embed the data dir path."""
    from sebastian.config import Settings

    s = Settings(sebastian_data_dir=str(tmp_path))
    assert str(tmp_path) in s.database_url


def test_jwt_create_and_decode() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    from sebastian.gateway.auth import create_access_token, decode_token

    token = create_access_token({"sub": "owner", "role": "owner"})
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload["sub"] == "owner"
    assert payload["role"] == "owner"


def test_jwt_invalid_token_raises() -> None:
    from fastapi import HTTPException

    from sebastian.gateway.auth import decode_token

    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.valid.token")
    assert exc_info.value.status_code == 401


def test_hash_and_verify_password() -> None:
    from sebastian.gateway.auth import hash_password, verify_password

    hashed = hash_password("secretpassword")
    assert verify_password("secretpassword", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_sessions_dir_derived_from_data_dir() -> None:
    from sebastian.config import settings

    assert (
        settings.sessions_dir
        == Path(settings.sebastian_data_dir).expanduser().resolve() / "sessions"
    )


def test_log_settings_defaults() -> None:
    """日志开关默认值应为 False。"""
    from sebastian.config import Settings

    s = Settings()
    assert s.sebastian_log_llm_stream is False
    assert s.sebastian_log_sse is False


def test_log_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量应能覆盖日志开关默认值。"""
    monkeypatch.setenv("SEBASTIAN_LOG_LLM_STREAM", "true")
    monkeypatch.setenv("SEBASTIAN_LOG_SSE", "true")
    from sebastian.config import Settings

    s = Settings()
    assert s.sebastian_log_llm_stream is True
    assert s.sebastian_log_sse is True

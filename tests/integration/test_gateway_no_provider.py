from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def empty_db_client(tmp_path):
    """Gateway with empty DB (no LLM provider configured)."""
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with patch.dict(
        os.environ,
        {
            "SEBASTIAN_OWNER_PASSWORD_HASH": password_hash,
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        },
    ):
        import sebastian.config as cfg_module

        importlib.reload(cfg_module)
        with patch.object(cfg_module.settings, "sebastian_owner_password_hash", password_hash):
            from sebastian.gateway.app import create_app

            test_app = create_app()
            with TestClient(test_app, raise_server_exceptions=True) as test_client:
                yield test_client


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_lifespan_starts_with_empty_db(empty_db_client: TestClient) -> None:
    """Gateway should start normally even when no LLM provider is configured."""
    # Reaching this point means lifespan completed successfully.
    response = empty_db_client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200


def test_send_turn_returns_400_no_llm_provider(empty_db_client: TestClient) -> None:
    token = _login(empty_db_client)
    response = empty_db_client.post(
        "/api/v1/turns",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"
    assert "Settings" in detail["message"] or "设置" in detail["message"]

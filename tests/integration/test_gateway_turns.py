from __future__ import annotations
import os
import pytest
from unittest.mock import AsyncMock, patch

# Set env vars before any app imports
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")


@pytest.fixture
def mock_chat():
    with patch(
        "sebastian.orchestrator.sebas.Sebastian.chat",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "Mocked response from Sebastian."
        yield m


@pytest.fixture
def client(mock_chat, tmp_path):
    from sebastian.gateway.auth import hash_password
    pw_hash = hash_password("testpass")
    with patch.dict(os.environ, {
        "SEBASTIAN_OWNER_PASSWORD_HASH": pw_hash,
        "SEBASTIAN_DATA_DIR": str(tmp_path),
        "ANTHROPIC_API_KEY": "test-key-not-real",
        "SEBASTIAN_JWT_SECRET": "test-secret-key",
    }):
        # Reload config to pick up patched env vars
        import importlib
        import sebastian.config as cfg_module
        importlib.reload(cfg_module)

        # Patch settings object directly to ensure password hash is set
        with patch.object(cfg_module.settings, "sebastian_owner_password_hash", pw_hash):
            from starlette.testclient import TestClient
            from sebastian.gateway.app import create_app
            test_app = create_app()
            with TestClient(test_app, raise_server_exceptions=True) as c:
                yield c


def _login(client) -> str:
    resp = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_success(client):
    token = _login(client)
    assert len(token) > 10


def test_login_wrong_password(client):
    resp = client.post("/api/v1/auth/login", json={"password": "wrongpass"})
    assert resp.status_code == 401


def test_send_turn_requires_auth(client):
    resp = client.post("/api/v1/turns", json={"message": "hello"})
    # FastAPI's HTTPBearer returns 403 when no credentials are provided,
    # but returns 401 on some versions; accept either as "unauthenticated"
    assert resp.status_code in (401, 403)


def test_send_turn_returns_response(client, mock_chat):
    token = _login(client)
    resp = client.post(
        "/api/v1/turns",
        json={"message": "Hello Sebastian"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["response"] == "Mocked response from Sebastian."
    assert "session_id" in data

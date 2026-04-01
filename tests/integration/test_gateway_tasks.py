from __future__ import annotations
import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")


@pytest.fixture
def client(tmp_path):
    from sebastian.gateway.auth import hash_password
    pw_hash = hash_password("testpass")
    with patch(
        "sebastian.orchestrator.sebas.Sebastian.chat",
        new_callable=AsyncMock,
        return_value="ok",
    ):
        with patch.dict(os.environ, {
            "SEBASTIAN_OWNER_PASSWORD_HASH": pw_hash,
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "ANTHROPIC_API_KEY": "test-key-not-real",
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        }):
            import importlib
            import sebastian.config as cfg_module
            importlib.reload(cfg_module)

            with patch.object(cfg_module.settings, "sebastian_owner_password_hash", pw_hash):
                from starlette.testclient import TestClient
                from sebastian.gateway.app import create_app
                test_app = create_app()
                with TestClient(test_app) as c:
                    yield c


def _token(client) -> str:
    resp = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_list_tasks_empty(client):
    token = _token(client)
    resp = client.get(
        "/api/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["tasks"] == []


def test_get_nonexistent_task(client):
    token = _token(client)
    resp = client.get(
        "/api/v1/tasks/nonexistent-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_agents_endpoint(client):
    token = _token(client)
    resp = client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["name"] == "sebastian"

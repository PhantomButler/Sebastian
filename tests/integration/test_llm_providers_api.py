from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def client(tmp_path):
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with patch.dict(
        os.environ,
        {
            "SEBASTIAN_OWNER_PASSWORD_HASH": password_hash,
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "ANTHROPIC_API_KEY": "test-key-not-real",
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        },
    ):
        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        with patch.object(cfg_module.settings, "sebastian_owner_password_hash", password_hash):
            with patch(
                "sebastian.gateway.routes.turns._ensure_llm_ready",
                new_callable=AsyncMock,
            ):
                from starlette.testclient import TestClient

                from sebastian.gateway.app import create_app

                app = create_app()
                with TestClient(app, raise_server_exceptions=True) as test_client:
                    # Login first
                    login_resp = test_client.post(
                        "/api/v1/auth/login",
                        json={"password": "testpass"},
                    )
                    assert login_resp.status_code == 200
                    token = login_resp.json()["access_token"]

                    yield test_client, token


@pytest.fixture(autouse=True)
def set_env():
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")


def test_llm_providers_crud(client) -> None:
    http_client, _ = client
    # Route exists at minimum (auth may reject)
    resp = http_client.get(
        "/api/v1/llm-providers",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code in (200, 401, 403)


def test_create_provider_with_thinking_capability(client) -> None:
    http_client, token = client

    resp = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Test Adaptive",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "thinking_capability": "adaptive",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["thinking_capability"] == "adaptive"

    list_resp = http_client.get("/api/v1/llm-providers", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    providers = list_resp.json()["providers"]
    created = next(p for p in providers if p["id"] == data["id"])
    assert created["thinking_capability"] == "adaptive"


def test_update_provider_thinking_capability(client) -> None:
    http_client, token = client

    create = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "TestU",
            "provider_type": "openai",
            "api_key": "sk-fake",
            "model": "o3",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    upd = http_client.put(
        f"/api/v1/llm-providers/{pid}",
        json={"thinking_capability": "effort"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 200
    assert upd.json()["thinking_capability"] == "effort"

from __future__ import annotations

import asyncio
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
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "ANTHROPIC_API_KEY": "test-key-not-real",
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        },
    ):
        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        with patch(
            "sebastian.gateway.routes.turns._ensure_llm_ready",
            new_callable=AsyncMock,
        ):
            import sebastian.store.database as db_module

            db_module._engine = None
            db_module._session_factory = None

            from sebastian.store.database import get_session_factory, init_db
            from sebastian.store.owner_store import OwnerStore

            async def _seed() -> None:
                await init_db()
                await OwnerStore(get_session_factory()).create_owner(
                    name="test-owner",
                    password_hash=password_hash,
                )

            asyncio.run(_seed())
            (tmp_path / "secret.key").write_text("test-secret-key")

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
            "base_url": "https://api.anthropic.com",
            "thinking_capability": "adaptive",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["api_key"] == "sk-ant-fake"
    assert data["thinking_capability"] == "adaptive"

    list_resp = http_client.get(
        "/api/v1/llm-providers", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_resp.status_code == 200
    providers = list_resp.json()["providers"]
    created = next(p for p in providers if p["id"] == data["id"])
    assert created["api_key"] == "sk-ant-fake"
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
            "base_url": "https://api.openai.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    upd = http_client.put(
        f"/api/v1/llm-providers/{pid}",
        json={"thinking_capability": "effort", "base_url": "https://api.openai.com/v1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 200
    assert upd.json()["api_key"] == "sk-fake"
    assert upd.json()["thinking_capability"] == "effort"


def test_create_default_provider_unsets_previous_default(client) -> None:
    http_client, token = client

    first = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Claude Home",
            "provider_type": "anthropic",
            "api_key": "sk-ant-first",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
            "is_default": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201
    assert first.json()["is_default"] is True

    second = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "OpenAI Work",
            "provider_type": "openai",
            "api_key": "sk-second",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "is_default": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 201
    assert second.json()["is_default"] is True

    list_resp = http_client.get(
        "/api/v1/llm-providers", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_resp.status_code == 200
    providers = list_resp.json()["providers"]
    defaults = [provider for provider in providers if provider["is_default"]]

    assert len(defaults) == 1
    assert defaults[0]["id"] == second.json()["id"]


def test_update_provider_to_default_unsets_previous_default(client) -> None:
    http_client, token = client

    first = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Claude Home",
            "provider_type": "anthropic",
            "api_key": "sk-ant-first",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
            "is_default": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    second = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "OpenAI Work",
            "provider_type": "openai",
            "api_key": "sk-second",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "is_default": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 201

    update_resp = http_client.put(
        f"/api/v1/llm-providers/{second.json()['id']}",
        json={"is_default": True, "base_url": "https://api.openai.com/v1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["is_default"] is True

    list_resp = http_client.get(
        "/api/v1/llm-providers", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_resp.status_code == 200
    providers = list_resp.json()["providers"]
    defaults = [provider for provider in providers if provider["is_default"]]

    assert len(defaults) == 1
    assert defaults[0]["id"] == second.json()["id"]


def test_put_provider_clears_thinking_capability_with_explicit_null(client) -> None:
    """PUT 显式传 thinking_capability: null 应清空字段。"""
    http_client, token = client

    create = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "ClearMe",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
            "thinking_capability": "effort",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    assert create.json()["thinking_capability"] == "effort"

    upd = http_client.put(
        f"/api/v1/llm-providers/{pid}",
        json={"thinking_capability": None, "base_url": "https://api.anthropic.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 200
    assert upd.json()["thinking_capability"] is None

    list_resp = http_client.get(
        "/api/v1/llm-providers", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_resp.status_code == 200
    providers = list_resp.json()["providers"]
    updated = next(p for p in providers if p["id"] == pid)
    assert updated["thinking_capability"] is None


def test_put_provider_omitted_field_preserves_value(client) -> None:
    """PUT 不传 thinking_capability 时应保留原值。"""
    http_client, token = client

    create = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Preserve",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
            "thinking_capability": "effort",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    upd = http_client.put(
        f"/api/v1/llm-providers/{pid}",
        json={"name": "PreserveRenamed", "base_url": "https://api.anthropic.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["name"] == "PreserveRenamed"
    assert body["thinking_capability"] == "effort"


@pytest.mark.parametrize("field", ["name", "api_key", "model", "is_default"])
def test_put_provider_rejects_explicit_null_on_required_fields(
    client,
    field: str,
) -> None:
    """nullable=False 的列显式传 null 应返回 400，而不是 500。"""
    http_client, token = client

    create = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "NullGuard",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
            "thinking_capability": "effort",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    upd = http_client.put(
        f"/api/v1/llm-providers/{pid}",
        json={
            field: None,
            **({"base_url": "https://api.anthropic.com"} if field != "base_url" else {}),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 400
    assert field in upd.json()["detail"]


def test_create_provider_requires_base_url(client) -> None:
    http_client, token = client

    resp = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Missing Base URL",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 422
    assert "base_url" in resp.text


def test_update_provider_requires_base_url(client) -> None:
    http_client, token = client

    create = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": "Need Base URL On Edit",
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201

    upd = http_client.put(
        f"/api/v1/llm-providers/{create.json()['id']}",
        json={"name": "Rename Only"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 400
    assert "base_url" in upd.json()["detail"]

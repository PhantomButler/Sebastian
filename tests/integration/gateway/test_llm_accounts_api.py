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
                from sebastian.store.database import get_engine

                await get_engine().dispose()
                await asyncio.sleep(0)

            asyncio.run(_seed())
            db_module._engine = None
            db_module._session_factory = None
            (tmp_path / "secret.key").write_text("test-secret-key")

            from starlette.testclient import TestClient

            from sebastian.gateway.app import create_app

            app = create_app()
            with TestClient(app, raise_server_exceptions=True) as test_client:
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


def test_catalog_endpoint(client) -> None:
    http_client, token = client
    resp = http_client.get(
        "/api/v1/llm-catalog",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    ids = [p["id"] for p in providers]
    assert "anthropic" in ids
    assert "openai" in ids


def test_create_builtin_account(client) -> None:
    http_client, token = client
    resp = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Anthropic Home",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-ant-fake",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Anthropic Home"
    assert data["catalog_provider_id"] == "anthropic"
    assert data["provider_type"] == "anthropic"
    assert data["has_api_key"] is True
    assert data["base_url_override"] is None
    assert "id" in data


def test_create_custom_account(client) -> None:
    http_client, token = client
    resp = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "My Local LLM",
            "catalog_provider_id": "custom",
            "api_key": "local-key",
            "provider_type": "openai",
            "base_url_override": "https://my-llm.example.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["catalog_provider_id"] == "custom"
    assert data["provider_type"] == "openai"
    assert data["base_url_override"] == "https://my-llm.example.com/v1"


def test_list_accounts(client) -> None:
    http_client, token = client
    http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "First",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Second",
            "catalog_provider_id": "openai",
            "api_key": "sk-2",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = http_client.get(
        "/api/v1/llm-accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    accounts = resp.json()["accounts"]
    assert len(accounts) == 2
    names = [a["name"] for a in accounts]
    assert "First" in names
    assert "Second" in names


def test_update_account_name(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Original",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    upd = http_client.put(
        f"/api/v1/llm-accounts/{aid}",
        json={"name": "Renamed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Renamed"


def test_update_account_api_key(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Key Test",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-old",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    upd = http_client.put(
        f"/api/v1/llm-accounts/{aid}",
        json={"api_key": "sk-new"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd.status_code == 200
    assert upd.json()["has_api_key"] is True


def test_delete_account_unbound(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "ToDelete",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-del",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    resp = http_client.delete(
        f"/api/v1/llm-accounts/{aid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    list_resp = http_client.get(
        "/api/v1/llm-accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    ids = [a["id"] for a in list_resp.json()["accounts"]]
    assert aid not in ids


def test_delete_account_bound_returns_409(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Bound",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-bound",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    http_client.put(
        "/api/v1/llm-bindings/default",
        json={"account_id": aid, "model_id": "claude-sonnet-4-6"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = http_client.delete(
        f"/api/v1/llm-accounts/{aid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_custom_model_crud_for_custom_account(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-custom",
            "provider_type": "openai",
            "base_url_override": "https://my-llm.example.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    model_resp = http_client.post(
        f"/api/v1/llm-accounts/{aid}/models",
        json={
            "model_id": "my-model-v1",
            "display_name": "My Model V1",
            "context_window_tokens": 128000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert model_resp.status_code == 201
    model_data = model_resp.json()
    assert model_data["model_id"] == "my-model-v1"
    mid = model_data["id"]

    list_resp = http_client.get(
        f"/api/v1/llm-accounts/{aid}/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()["models"]) == 1

    upd_resp = http_client.put(
        f"/api/v1/llm-accounts/{aid}/models/{mid}",
        json={"display_name": "My Model V1 Updated"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upd_resp.status_code == 200
    assert upd_resp.json()["display_name"] == "My Model V1 Updated"

    del_resp = http_client.delete(
        f"/api/v1/llm-accounts/{aid}/models/{mid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204


def test_custom_model_reject_for_builtin_account(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Anthropic",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-ant",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    resp = http_client.post(
        f"/api/v1/llm-accounts/{aid}/models",
        json={
            "model_id": "test",
            "display_name": "Test",
            "context_window_tokens": 128000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_default_binding_set_and_get(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Default",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-default",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    put_resp = http_client.put(
        "/api/v1/llm-bindings/default",
        json={"account_id": aid, "model_id": "claude-sonnet-4-6"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert put_resp.status_code == 200
    data = put_resp.json()
    assert data["account_id"] == aid
    assert data["model_id"] == "claude-sonnet-4-6"

    get_resp = http_client.get(
        "/api/v1/llm-bindings/default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["account_id"] == aid


def test_default_binding_set_validates_model(client) -> None:
    http_client, token = client
    create = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Default",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-default",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = create.json()["id"]

    resp = http_client.put(
        "/api/v1/llm-bindings/default",
        json={"account_id": aid, "model_id": "nonexistent-model"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_create_account_rejects_invalid_base_url(client) -> None:
    http_client, token = client
    resp = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Bad URL",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-test",
            "base_url_override": "not-a-url",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


def test_custom_model_model_id_change_returns_409_when_referenced(client) -> None:
    http_client, token = client

    account = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom 409 Test",
            "catalog_provider_id": "custom",
            "api_key": "sk-custom",
            "provider_type": "openai",
            "base_url_override": "https://custom.api.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert account.status_code == 201
    account_id = account.json()["id"]

    model = http_client.post(
        f"/api/v1/llm-accounts/{account_id}/models",
        json={
            "model_id": "my-model-v1",
            "display_name": "My Model V1",
            "context_window_tokens": 32000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert model.status_code == 201
    model_record_id = model.json()["id"]

    http_client.put(
        "/api/v1/llm-bindings/default",
        json={"account_id": account_id, "model_id": "my-model-v1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = http_client.put(
        f"/api/v1/llm-accounts/{account_id}/models/{model_record_id}",
        json={"model_id": "my-model-v2"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "binding" in resp.json()["detail"].lower()


def test_custom_model_delete_returns_409_when_referenced(client) -> None:
    http_client, token = client

    account = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom Delete 409",
            "catalog_provider_id": "custom",
            "api_key": "sk-custom2",
            "provider_type": "openai",
            "base_url_override": "https://custom2.api.com/v1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert account.status_code == 201
    account_id = account.json()["id"]

    model = http_client.post(
        f"/api/v1/llm-accounts/{account_id}/models",
        json={
            "model_id": "bound-model",
            "display_name": "Bound Model",
            "context_window_tokens": 64000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert model.status_code == 201
    model_record_id = model.json()["id"]

    http_client.put(
        "/api/v1/llm-bindings/default",
        json={"account_id": account_id, "model_id": "bound-model"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = http_client.delete(
        f"/api/v1/llm-accounts/{account_id}/models/{model_record_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409

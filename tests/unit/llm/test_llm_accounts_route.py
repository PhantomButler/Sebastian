from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sebastian.gateway.routes.llm_accounts import (
    _account_to_dict,
)


def _make_account(**overrides: Any) -> SimpleNamespace:
    now = _dt.datetime.now(_dt.UTC)
    base = {
        "id": "acc1",
        "name": "Anthropic Account",
        "catalog_provider_id": "anthropic",
        "provider_type": "anthropic",
        "api_key_enc": "enc-key",
        "base_url_override": None,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_custom_model(**overrides: Any) -> SimpleNamespace:
    now = _dt.datetime.now(_dt.UTC)
    base = {
        "id": "cm1",
        "account_id": "acc1",
        "model_id": "my-model",
        "display_name": "My Model",
        "context_window_tokens": 128000,
        "thinking_capability": None,
        "thinking_format": None,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def mock_registry() -> MagicMock:
    r = MagicMock()
    r.list_accounts = AsyncMock(return_value=[])
    r.get_account = AsyncMock(return_value=None)
    r.create_account = AsyncMock()
    r.update_account = AsyncMock(return_value=None)
    r.delete_account = AsyncMock(return_value=False)
    r.list_bindings = AsyncMock(return_value=[])
    r.get_binding = AsyncMock(return_value=None)
    r.set_binding = AsyncMock(return_value=None)
    r.get_model_spec = AsyncMock(return_value=None)
    return r


@pytest.fixture
def mock_db_factory():
    class FakeResult:
        def scalar_one_or_none(self):
            return None

        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, stmt):
            return FakeResult()

        async def delete(self, obj):
            pass

        async def commit(self):
            pass

        def add(self, obj):
            pass

        async def refresh(self, obj):
            pass

    factory = MagicMock(return_value=FakeSession())
    return factory


@pytest.fixture
def client(
    mock_registry: MagicMock,
    mock_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", mock_registry)
    monkeypatch.setattr(state, "db_factory", mock_db_factory, raising=False)

    from sebastian.gateway.auth import require_auth
    from sebastian.gateway.routes.llm_accounts import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    return TestClient(app)


def test_create_account_rejects_empty_api_key(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Test",
            "catalog_provider_id": "anthropic",
            "api_key": "",
        },
    )
    assert resp.status_code == 400
    assert "api_key" in resp.json()["detail"]


def test_create_account_rejects_unknown_catalog_provider(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Test",
            "catalog_provider_id": "nonexistent_provider",
            "api_key": "sk-test",
        },
    )
    assert resp.status_code == 400
    assert "Unknown catalog provider" in resp.json()["detail"]


def test_create_account_custom_without_provider_type(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
        },
    )
    assert resp.status_code == 400
    assert "provider_type" in resp.json()["detail"]


def test_create_account_custom_without_base_url(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
            "provider_type": "openai",
        },
    )
    assert resp.status_code == 400
    assert "base_url_override" in resp.json()["detail"]


def test_create_account_custom_rejects_invalid_base_url(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
            "provider_type": "openai",
            "base_url_override": "not-a-url",
        },
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


def test_create_account_custom_success(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.create_account = AsyncMock()

    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Custom",
            "catalog_provider_id": "custom",
            "api_key": "sk-test",
            "provider_type": "openai",
            "base_url_override": "https://my-llm.example.com/v1",
        },
    )
    assert resp.status_code == 201
    mock_registry.create_account.assert_awaited_once()


def test_create_account_builtin_success(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.create_account = AsyncMock()

    resp = client.post(
        "/api/v1/llm-accounts",
        json={
            "name": "Anthropic",
            "catalog_provider_id": "anthropic",
            "api_key": "sk-ant-test",
        },
    )
    assert resp.status_code == 201
    mock_registry.create_account.assert_awaited_once()


def test_update_account_rejects_null_api_key(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/llm-accounts/acc1",
        json={"api_key": None},
    )
    assert resp.status_code == 400
    assert "api_key" in resp.json()["detail"]


def test_update_account_rejects_empty_api_key(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/llm-accounts/acc1",
        json={"api_key": ""},
    )
    assert resp.status_code == 400
    assert "api_key" in resp.json()["detail"]


def test_update_account_rejects_invalid_base_url(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/llm-accounts/acc1",
        json={"base_url_override": "not-a-url"},
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


def test_update_account_404_when_not_found(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.update_account = AsyncMock(return_value=None)

    resp = client.put(
        "/api/v1/llm-accounts/nonexistent",
        json={"name": "New Name"},
    )
    assert resp.status_code == 404


def test_delete_account_returns_409_when_bound(
    client: TestClient, mock_registry: MagicMock, mock_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bound_record = MagicMock()
    bound_record.agent_type = "sebastian"

    class FakeBoundResult:
        def scalars(self):
            return self

        def all(self):
            return [bound_record]

    class BoundSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, stmt):
            return FakeBoundResult()

    mock_db_factory.return_value = BoundSession()

    resp = client.delete("/api/v1/llm-accounts/acc1")
    assert resp.status_code == 409


def test_delete_account_404_when_not_found(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.delete_account = AsyncMock(return_value=False)

    resp = client.delete("/api/v1/llm-accounts/nonexistent")
    assert resp.status_code == 404


def test_catalog_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/llm-catalog")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert len(providers) > 0
    anthropic = next(p for p in providers if p["id"] == "anthropic")
    assert len(anthropic["models"]) > 0


def test_custom_model_rejects_non_custom_account(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.get_account = AsyncMock(
        return_value=_make_account(catalog_provider_id="anthropic")
    )

    resp = client.post(
        "/api/v1/llm-accounts/acc1/models",
        json={
            "model_id": "test-model",
            "display_name": "Test",
            "context_window_tokens": 128000,
        },
    )
    assert resp.status_code == 400
    assert "custom" in resp.json()["detail"].lower()


def test_custom_model_404_for_unknown_account(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.get_account = AsyncMock(return_value=None)

    resp = client.get("/api/v1/llm-accounts/nonexistent/models")
    assert resp.status_code == 404


def test_default_binding_get_returns_null_when_unset(client: TestClient) -> None:
    resp = client.get("/api/v1/llm-bindings/default")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] is None
    assert data["model_id"] is None


def test_default_binding_set_validates_account(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.get_account = AsyncMock(return_value=None)

    resp = client.put(
        "/api/v1/llm-bindings/default",
        json={"account_id": "bogus", "model_id": "model-1"},
    )
    assert resp.status_code == 400


def test_account_to_dict_masks_api_key() -> None:
    record = _make_account(api_key_enc="enc-key")
    result = _account_to_dict(record)
    assert result["has_api_key"] is True

    record_empty = _make_account(api_key_enc="")
    result_empty = _account_to_dict(record_empty)
    assert result_empty["has_api_key"] is False

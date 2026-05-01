# tests/unit/test_memory_components_route.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sebastian.memory.consolidation.provider_bindings import (
    MEMORY_CONSOLIDATOR_BINDING,
    MEMORY_EXTRACTOR_BINDING,
)


def _make_binding(
    agent_type: str,
    account_id: str | None = None,
    model_id: str | None = None,
) -> MagicMock:
    b = MagicMock()
    b.agent_type = agent_type
    b.account_id = account_id
    b.model_id = model_id
    b.thinking_effort = None
    return b


def _make_account_record(aid: str = "acc-1") -> MagicMock:
    r = MagicMock()
    r.id = aid
    r.catalog_provider_id = "anthropic"
    return r


def _make_model_spec(capability: str = "none") -> MagicMock:
    m = MagicMock()
    m.thinking_capability = capability
    return m


@pytest.fixture
def mock_registry() -> MagicMock:
    r = MagicMock()
    r.list_bindings = AsyncMock(return_value=[])
    r.get_binding = AsyncMock(return_value=None)
    r.get_account = AsyncMock(return_value=None)
    r.get_model_spec = AsyncMock(return_value=None)
    r.set_binding = AsyncMock(return_value=_make_binding(MEMORY_EXTRACTOR_BINDING))
    r.clear_binding = AsyncMock()
    return r


@pytest.fixture
def client(mock_registry: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import sebastian.gateway.state as state

    monkeypatch.setattr(state, "llm_registry", mock_registry)

    from sebastian.gateway.auth import require_auth
    from sebastian.gateway.routes.memory_components import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    return TestClient(app)


def test_list_returns_both_components_with_null_binding(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.list_bindings = AsyncMock(return_value=[])
    resp = client.get("/api/v1/memory/components")
    assert resp.status_code == 200
    data = resp.json()
    types = [c["component_type"] for c in data["components"]]
    assert MEMORY_EXTRACTOR_BINDING in types
    assert MEMORY_CONSOLIDATOR_BINDING in types
    for c in data["components"]:
        assert c["binding"] is None
        assert "display_name" in c
        assert "description" in c


def test_list_shows_existing_binding(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.list_bindings = AsyncMock(
        return_value=[
            _make_binding(MEMORY_EXTRACTOR_BINDING, account_id="acc-abc", model_id="model-1")
        ]
    )
    resp = client.get("/api/v1/memory/components")
    assert resp.status_code == 200
    by_type = {c["component_type"]: c for c in resp.json()["components"]}
    assert by_type[MEMORY_EXTRACTOR_BINDING]["binding"]["account_id"] == "acc-abc"
    assert by_type[MEMORY_EXTRACTOR_BINDING]["binding"]["model_id"] == "model-1"
    assert by_type[MEMORY_CONSOLIDATOR_BINDING]["binding"] is None


def test_get_binding_no_row_returns_null(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.get_binding = AsyncMock(return_value=None)
    resp = client.get(f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding")
    assert resp.status_code == 200
    body = resp.json()
    assert body["component_type"] == MEMORY_EXTRACTOR_BINDING
    assert body["account_id"] is None
    assert body["model_id"] is None


def test_get_binding_unknown_type_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/memory/components/unknown_thing/llm-binding")
    assert resp.status_code == 404


def test_put_resets_effort_when_binding_changes(
    client: TestClient, mock_registry: MagicMock
) -> None:
    mock_registry.get_account = AsyncMock(return_value=_make_account_record("acc-1"))
    mock_registry.get_model_spec = AsyncMock(return_value=_make_model_spec("adaptive"))
    mock_registry.get_binding = AsyncMock(return_value=None)
    mock_registry.set_binding = AsyncMock(
        return_value=_make_binding(MEMORY_EXTRACTOR_BINDING, "acc-1", "model-1")
    )
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"account_id": "acc-1", "model_id": "model-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    kwargs = mock_registry.set_binding.call_args.kwargs
    assert kwargs["thinking_effort"] is None


def test_put_preserves_effort_when_binding_unchanged(
    client: TestClient, mock_registry: MagicMock
) -> None:
    existing = _make_binding(MEMORY_EXTRACTOR_BINDING, "acc-1", "model-1")
    mock_registry.get_account = AsyncMock(return_value=_make_account_record("acc-1"))
    mock_registry.get_model_spec = AsyncMock(return_value=_make_model_spec("adaptive"))
    mock_registry.get_binding = AsyncMock(return_value=existing)
    mock_registry.set_binding = AsyncMock(return_value=existing)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"account_id": "acc-1", "model_id": "model-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    assert mock_registry.set_binding.call_args.kwargs["thinking_effort"] == "high"


def test_put_clears_effort_for_none_capability(
    client: TestClient, mock_registry: MagicMock
) -> None:
    existing = _make_binding(MEMORY_EXTRACTOR_BINDING, "acc-1", "model-1")
    mock_registry.get_account = AsyncMock(return_value=_make_account_record("acc-1"))
    mock_registry.get_model_spec = AsyncMock(return_value=_make_model_spec("none"))
    mock_registry.get_binding = AsyncMock(return_value=existing)
    mock_registry.set_binding = AsyncMock(return_value=existing)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"account_id": "acc-1", "model_id": "model-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    assert mock_registry.set_binding.call_args.kwargs["thinking_effort"] is None


def test_put_clears_effort_for_always_on_capability(
    client: TestClient, mock_registry: MagicMock
) -> None:
    existing = _make_binding(MEMORY_EXTRACTOR_BINDING, "acc-1", "model-1")
    mock_registry.get_account = AsyncMock(return_value=_make_account_record("acc-1"))
    mock_registry.get_model_spec = AsyncMock(return_value=_make_model_spec("always_on"))
    mock_registry.get_binding = AsyncMock(return_value=existing)
    mock_registry.set_binding = AsyncMock(return_value=existing)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"account_id": "acc-1", "model_id": "model-1", "thinking_effort": "high"},
    )
    assert resp.status_code == 200
    assert mock_registry.set_binding.call_args.kwargs["thinking_effort"] is None


def test_put_unknown_account_returns_400(client: TestClient, mock_registry: MagicMock) -> None:
    mock_registry.get_account = AsyncMock(return_value=None)
    resp = client.put(
        f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding",
        json={"account_id": "nonexistent", "model_id": "model-1"},
    )
    assert resp.status_code == 400


def test_put_unknown_component_returns_404(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/memory/components/bad_type/llm-binding",
        json={"account_id": None, "model_id": None},
    )
    assert resp.status_code == 404


def test_delete_returns_204_and_calls_clear(client: TestClient, mock_registry: MagicMock) -> None:
    resp = client.delete(f"/api/v1/memory/components/{MEMORY_EXTRACTOR_BINDING}/llm-binding")
    assert resp.status_code == 204
    mock_registry.clear_binding.assert_awaited_once_with(MEMORY_EXTRACTOR_BINDING)


def test_delete_unknown_component_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/v1/memory/components/bad_type/llm-binding")
    assert resp.status_code == 404

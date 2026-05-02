from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sebastian.gateway.auth import require_auth
from sebastian.gateway.routes.soul import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    async def _fake_auth() -> dict[str, str]:
        return {"user_id": "test"}

    app.dependency_overrides[require_auth] = _fake_auth
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_get_current_soul_requires_auth() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")  # NO dependency_overrides
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/soul/current")
    assert resp.status_code == 401


def test_get_current_soul_returns_active_soul(client: TestClient) -> None:
    mock_loader = MagicMock()
    mock_loader.current_soul = "cortana"

    mock_state = MagicMock()
    mock_state.soul_loader = mock_loader

    with patch("sebastian.gateway.routes.soul._get_state", return_value=mock_state):
        resp = client.get("/api/v1/soul/current")

    assert resp.status_code == 200
    assert resp.json() == {"active_soul": "cortana"}

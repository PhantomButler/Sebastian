# tests/integration/test_debug_route.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret")

    # setup_logging before app import
    from sebastian.log import setup_logging
    setup_logging(data_dir=tmp_path)

    from fastapi import FastAPI
    from sebastian.gateway.routes.debug import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


@pytest.fixture()
def auth_headers(tmp_path: Path) -> dict[str, str]:
    from sebastian.gateway.auth import create_access_token
    token = create_access_token({"sub": "owner", "role": "owner"})
    return {"Authorization": f"Bearer {token}"}


def test_get_logging_state(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/debug/logging", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_stream_enabled"] is False
    assert body["sse_enabled"] is False


def test_patch_logging_state(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.patch(
        "/api/v1/debug/logging",
        json={"llm_stream_enabled": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_stream_enabled"] is True
    assert body["sse_enabled"] is False  # 未传的字段保持不变


def test_patch_requires_auth(client: TestClient) -> None:
    resp = client.patch("/api/v1/debug/logging", json={"sse_enabled": True})
    assert resp.status_code == 401

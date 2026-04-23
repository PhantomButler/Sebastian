from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest


def _seed_and_get_app(tmp_path: Path, password: str):
    """Seed owner + secret.key before lifespan runs (Strategy B)."""
    import sebastian.store.database as db_module

    db_module._engine = None
    db_module._session_factory = None

    from sebastian.gateway.auth import hash_password
    from sebastian.store.database import get_session_factory, init_db
    from sebastian.store.owner_store import OwnerStore

    async def _seed() -> None:
        await init_db()
        await OwnerStore(get_session_factory()).create_owner(
            name="Eric", password_hash=hash_password(password)
        )
        from sebastian.store.database import get_engine

        await get_engine().dispose()
        await asyncio.sleep(0)

    asyncio.run(_seed())
    db_module._engine = None
    db_module._session_factory = None
    (tmp_path / "secret.key").write_text("integration-secret")

    from sebastian.gateway.app import create_app

    return create_app()


def test_login_succeeds_with_store_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "ignored-when-secret-file-present")

    import sebastian.config as cfg_module

    importlib.reload(cfg_module)

    app = _seed_and_get_app(tmp_path, "hunter2")

    from starlette.testclient import TestClient

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/v1/auth/login", json={"password": "hunter2"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()


def test_login_rejects_wrong_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "ignored-when-secret-file-present")

    import sebastian.config as cfg_module

    importlib.reload(cfg_module)

    app = _seed_and_get_app(tmp_path, "correctpass")

    from starlette.testclient import TestClient

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/v1/auth/login", json={"password": "wrongpass"})
        assert resp.status_code == 401

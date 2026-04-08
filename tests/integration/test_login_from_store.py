from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.store.database import Base
from sebastian.store.owner_store import OwnerStore

pytestmark = pytest.mark.skip(reason="unblocked by Task 2.8 state wiring")


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db", future=True)
    async with engine.begin() as conn:
        from sebastian.store import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_login_succeeds_with_store_owner(tmp_path: Path, session_factory) -> None:
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")
    store = OwnerStore(session_factory)
    await store.create_owner(name="Eric", password_hash=password_hash)

    secret_key_path = tmp_path / "secret.key"
    secret_key_path.write_text("test-secret-key", encoding="utf-8")

    import importlib

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret-key")

        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        from starlette.testclient import TestClient

        def create_app():
            from sebastian.gateway.app import create_app as _create_app

            return _create_app()

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.post("/api/v1/auth/login", json={"password": "testpass"})
            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(tmp_path: Path, session_factory) -> None:
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("correctpass")
    store = OwnerStore(session_factory)
    await store.create_owner(name="Eric", password_hash=password_hash)

    import importlib

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret-key")

        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        from starlette.testclient import TestClient

        def create_app():
            from sebastian.gateway.app import create_app as _create_app

            return _create_app()

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.post("/api/v1/auth/login", json={"password": "wrongpass"})
            assert response.status_code == 401

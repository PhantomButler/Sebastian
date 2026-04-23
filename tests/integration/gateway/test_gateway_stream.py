from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")


async def _single_chunk_stream():
    yield "id: 1\ndata: {}\n\n"


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

        test_app = create_app()
        with TestClient(test_app, raise_server_exceptions=True) as test_client:
            yield test_client


def _login(client) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_global_stream_forwards_last_event_id_header(client):
    token = _login(client)

    import sebastian.gateway.state as state

    state.sse_manager.stream = MagicMock(return_value=_single_chunk_stream())

    with client.stream(
        "GET",
        "/api/v1/stream",
        headers={
            "Authorization": f"Bearer {token}",
            "Last-Event-ID": "7",
        },
    ) as response:
        first_chunk = next(response.iter_text())

    assert response.status_code == 200
    assert first_chunk == "id: 1\ndata: {}\n\n"
    state.sse_manager.stream.assert_called_once_with(
        session_id=None,
        last_event_id=7,
    )


def test_session_stream_forwards_session_filter_and_last_event_id(client):
    token = _login(client)

    import sebastian.gateway.state as state

    state.sse_manager.stream = MagicMock(return_value=_single_chunk_stream())

    with client.stream(
        "GET",
        "/api/v1/sessions/session-123/stream",
        headers={
            "Authorization": f"Bearer {token}",
            "Last-Event-ID": "3",
        },
    ) as response:
        first_chunk = next(response.iter_text())

    assert response.status_code == 200
    assert first_chunk == "id: 1\ndata: {}\n\n"
    state.sse_manager.stream.assert_called_once_with(
        session_id="session-123",
        last_event_id=3,
    )

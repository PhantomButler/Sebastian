from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def empty_db_client(tmp_path):
    """Gateway with empty DB (no LLM provider configured)."""
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with patch.dict(
        os.environ,
        {
            "SEBASTIAN_DATA_DIR": str(tmp_path),
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

        asyncio.run(_seed())
        (tmp_path / "secret.key").write_text("test-secret-key")

        from sebastian.gateway.app import create_app

        test_app = create_app()
        with TestClient(test_app, raise_server_exceptions=True) as test_client:
            yield test_client
        db_module._engine = None
        db_module._session_factory = None


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_lifespan_starts_with_empty_db(empty_db_client: TestClient) -> None:
    """Gateway should start normally even when no LLM provider is configured."""
    # Reaching this point means lifespan completed successfully.
    response = empty_db_client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200


def test_send_turn_returns_400_no_llm_provider(empty_db_client: TestClient) -> None:
    token = _login(empty_db_client)
    response = empty_db_client.post(
        "/api/v1/turns",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"
    assert "Settings" in detail["message"] or "设置" in detail["message"]


def test_create_agent_session_returns_400(empty_db_client: TestClient) -> None:
    token = _login(empty_db_client)
    response = empty_db_client.post(
        "/api/v1/agents/sebastian/sessions",
        json={"content": "hello sub-agent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # pre-check 先于 agent_type 404 检查
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"


def test_send_turn_to_session_returns_400(empty_db_client: TestClient) -> None:
    """Need an existing session to hit this route. Create one directly via store."""
    token = _login(empty_db_client)

    # Create a session directly via store (bypass create route which is also gated).
    import sebastian.gateway.state as state

    async def _seed() -> str:
        from sebastian.core.types import Session

        session = Session(
            agent_type="sebastian",
            title="seed",
            goal="seed",
            depth=1,
        )
        await state.session_store.create_session(session)
        await state.index_store.upsert(session)
        return session.id

    session_id = asyncio.run(_seed())

    response = empty_db_client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"

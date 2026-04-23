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

            test_app = create_app()
            with TestClient(test_app, raise_server_exceptions=True) as test_client:
                yield test_client


def _login(http_client) -> str:
    response = http_client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_get_todos_empty_for_new_session(client):
    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    token = _login(client)

    session = Session(agent_type="sebastian", title="t")
    asyncio.run(state.session_store.create_session(session))

    response = client.get(
        f"/api/v1/sessions/{session.id}/todos",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["todos"] == []
    assert body["updated_at"] is None


def test_get_todos_returns_written(client):
    import sebastian.gateway.state as state
    from sebastian.core.types import Session, TodoItem, TodoStatus

    token = _login(client)

    session = Session(agent_type="sebastian", title="t")
    asyncio.run(state.session_store.create_session(session))

    asyncio.run(
        state.todo_store.write(
            "sebastian",
            session.id,
            [
                TodoItem(content="a", active_form="doing a", status=TodoStatus.IN_PROGRESS),
                TodoItem(content="b", active_form="doing b", status=TodoStatus.PENDING),
            ],
        )
    )

    response = client.get(
        f"/api/v1/sessions/{session.id}/todos",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["todos"]) == 2
    assert body["todos"][0]["content"] == "a"
    assert body["todos"][0]["activeForm"] == "doing a"
    assert body["todos"][0]["status"] == "in_progress"
    assert body["updated_at"] is not None

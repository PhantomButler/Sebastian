from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

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


def _login(client) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _capture_background_task(scheduled_coroutines: list[object]):
    import asyncio as _asyncio
    import inspect as _inspect
    import sys as _sys

    _real_create_task = _asyncio.create_task
    _ROUTE_MARKERS = ("gateway/routes/sessions.py", "gateway/routes/turns.py")
    _MOCK_MARKER = "unittest/mock.py"

    def _direct_caller_is_route() -> bool:
        frame = _sys._getframe(2)
        while frame is not None:
            filename = frame.f_code.co_filename or ""
            if _MOCK_MARKER not in filename:
                return any(m in filename for m in _ROUTE_MARKERS)
            frame = frame.f_back
        return False

    def inner(coroutine, **kwargs):
        if _inspect.iscoroutine(coroutine) and _direct_caller_is_route():
            scheduled_coroutines.append(coroutine)
            coroutine.close()
            return MagicMock()
        return _real_create_task(coroutine, **kwargs)

    return inner


def test_create_agent_session_without_session_id_auto_generates_id(client) -> None:
    """POST without session_id uses auto-generated id (old behavior preserved)."""
    import sebastian.gateway.state as state

    token = _login(client)
    agent_type = next(iter(state.agent_instances.keys()))

    scheduled_coroutines: list[object] = []

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        response = client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "Hello agent"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"]
    assert body["session_id"] != "None"  # must not be the string "None"
    assert len(scheduled_coroutines) == 1


def test_create_agent_session_accepts_client_session_id(client) -> None:
    """POST /agents/{type}/sessions with session_id uses client-provided id."""
    import sebastian.gateway.state as state

    token = _login(client)
    agent_type = next(iter(state.agent_instances.keys()))

    scheduled_coroutines: list[object] = []

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        response = client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "Hello agent", "session_id": "app-session-1"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "app-session-1"
    assert "ts" in body
    assert len(scheduled_coroutines) == 1


def test_create_agent_session_is_idempotent_for_same_client_id(client) -> None:
    """Same session_id + same content = 200 with no new agent turn started."""
    import sebastian.gateway.state as state

    token = _login(client)
    agent_type = next(iter(state.agent_instances.keys()))

    scheduled_coroutines: list[object] = []

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        resp1 = client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "My unique goal", "session_id": "idempotent-session-42"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp1.status_code == 200, resp1.text
    assert resp1.json()["session_id"] == "idempotent-session-42"
    assert len(scheduled_coroutines) == 1

    # Second POST with same session_id + same content — must be idempotent
    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        resp2 = client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "My unique goal", "session_id": "idempotent-session-42"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["session_id"] == "idempotent-session-42"
    # No new background task should have been created on the second call
    assert len(scheduled_coroutines) == 1


def test_create_agent_session_conflicts_when_client_id_matches_different_goal(
    client,
) -> None:
    """Same session_id + different content = 409."""
    import sebastian.gateway.state as state

    token = _login(client)
    agent_type = next(iter(state.agent_instances.keys()))

    scheduled_coroutines: list[object] = []

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        resp1 = client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "First goal", "session_id": "conflict-session-99"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp1.status_code == 200, resp1.text

    # Second POST with same session_id but different content
    resp2 = client.post(
        f"/api/v1/agents/{agent_type}/sessions",
        json={"content": "Different goal", "session_id": "conflict-session-99"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp2.status_code == 409, resp2.text

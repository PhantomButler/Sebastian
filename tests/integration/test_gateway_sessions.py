from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")


@pytest.fixture
def client(tmp_path):
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with patch.dict(
        os.environ,
        {
            "SEBASTIAN_OWNER_PASSWORD_HASH": password_hash,
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "ANTHROPIC_API_KEY": "test-key-not-real",
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        },
    ):
        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        with patch.object(
            cfg_module.settings, "sebastian_owner_password_hash", password_hash
        ):
            with patch(
                "sebastian.orchestrator.sebas.Sebastian.run_streaming",
                new_callable=AsyncMock,
                return_value="Session reply",
            ) as mock_run_streaming:
                with patch(
                    "sebastian.orchestrator.sebas.Sebastian.intervene",
                    new_callable=AsyncMock,
                    return_value="Intervened reply",
                ) as mock_intervene:
                    from starlette.testclient import TestClient

                    from sebastian.gateway.app import create_app

                    test_app = create_app()
                    with TestClient(test_app, raise_server_exceptions=True) as test_client:
                        yield test_client, mock_run_streaming, mock_intervene


def _login(client) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _store_session(session) -> None:
    import sebastian.gateway.state as state

    asyncio.run(state.session_store.create_session(session))
    asyncio.run(state.index_store.upsert(session))


def _store_task(task, agent_type: str, agent_id: str) -> None:
    import sebastian.gateway.state as state

    asyncio.run(state.session_store.create_task(task, agent_type, agent_id))


def _capture_background_task(scheduled_coroutines: list[object]):
    def inner(coroutine):
        scheduled_coroutines.append(coroutine)
        coroutine.close()
        return MagicMock()

    return inner


def test_list_sessions_empty(client):
    http_client, _, _ = client
    token = _login(http_client)

    response = http_client.get(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"sessions": []}


def test_get_session_returns_meta_and_messages(client):
    http_client, _, _ = client
    token = _login(http_client)

    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    session = Session(
        agent_type="sebastian",
        agent_id="sebastian_01",
        title="Hello world",
    )
    assert state.session_store is not None
    assert state.index_store is not None

    asyncio.run(state.session_store.create_session(session))
    asyncio.run(
        state.session_store.append_message(
            session.id,
            "user",
            "Hello",
            agent_type="sebastian",
            agent_id="sebastian_01",
        )
    )
    asyncio.run(state.index_store.upsert(session))

    response = http_client.get(
        f"/api/v1/sessions/{session.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["session"]["id"] == session.id
    assert data["messages"][0]["content"] == "Hello"


def test_send_turn_to_sebastian_session_runs_background_stream(client):
    http_client, mock_run_streaming, _ = client
    token = _login(http_client)

    from sebastian.core.types import Session

    session = Session(
        agent_type="sebastian",
        agent_id="sebastian_01",
        title="Sebastian session",
    )
    _store_session(session)
    scheduled_coroutines = []

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        response = http_client.post(
            f"/api/v1/sessions/{session.id}/turns",
            json={"content": "Continue the conversation"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_id"] == session.id
    assert "ts" in payload
    assert "response" not in payload
    assert len(scheduled_coroutines) == 1
    mock_run_streaming.assert_called_once_with("Continue the conversation", session.id)
    assert mock_run_streaming.await_count == 0


def test_send_turn_to_subagent_session_uses_intervention(client):
    http_client, _, mock_intervene = client
    token = _login(http_client)

    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    session = Session(agent_type="stock", agent_id="stock_02", title="Stock session")
    original_updated_at = session.updated_at
    _store_session(session)
    scheduled_coroutines = []

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        response = http_client.post(
            f"/api/v1/sessions/{session.id}/turns",
            json={"content": "Please revise the plan"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_id"] == session.id
    assert "ts" in payload
    assert "response" not in payload
    assert len(scheduled_coroutines) == 1
    mock_intervene.assert_called_once_with("stock", session.id, "Please revise the plan")
    assert mock_intervene.await_count == 0

    stored_session = asyncio.run(
        state.session_store.get_session(session.id, "stock", "stock_02")
    )
    assert stored_session is not None
    assert stored_session.updated_at >= original_updated_at


def test_session_task_routes_resolve_stored_agent_metadata(client):
    http_client, _, _ = client
    token = _login(http_client)

    from sebastian.core.types import Session, Task

    session = Session(agent_type="stock", agent_id="stock_03", title="Task session")
    task = Task(session_id=session.id, goal="Review the investment thesis")
    _store_session(session)
    _store_task(task, "stock", "stock_03")

    list_response = http_client.get(
        f"/api/v1/sessions/{session.id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200, list_response.text
    tasks = list_response.json()["tasks"]
    assert [item["id"] for item in tasks] == [task.id]

    detail_response = http_client.get(
        f"/api/v1/sessions/{session.id}/tasks/{task.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["task"]["id"] == task.id


@pytest.mark.parametrize(
    ("method", "route_suffix", "result_key"),
    [
        ("post", "pause", "paused"),
        ("delete", "", "cancelled"),
    ],
)
def test_task_mutation_routes_require_task_to_belong_to_resolved_session(
    client,
    method: str,
    route_suffix: str,
    result_key: str,
):
    http_client, _, _ = client
    token = _login(http_client)

    import sebastian.gateway.state as state
    from sebastian.core.types import Session, Task

    session = Session(agent_type="stock", agent_id="stock_02", title="Owned task session")
    task = Task(session_id=session.id, goal="Pause or cancel this task")
    _store_session(session)
    _store_task(task, "stock", "stock_02")

    route = f"/api/v1/sessions/{session.id}/tasks/{task.id}"
    if route_suffix:
        route = f"{route}/{route_suffix}"

    with patch.object(
        state.sebastian._task_manager,
        "cancel",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_cancel:
        response = getattr(http_client, method)(
            route,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"task_id": task.id, result_key: True}
    mock_cancel.assert_awaited_once_with(task.id)


@pytest.mark.parametrize(
    ("method", "route_suffix"),
    [
        ("post", "pause"),
        ("delete", ""),
    ],
)
def test_task_mutation_routes_return_404_for_task_outside_resolved_session(
    client,
    method: str,
    route_suffix: str,
):
    http_client, _, _ = client
    token = _login(http_client)

    import sebastian.gateway.state as state
    from sebastian.core.types import Session, Task

    owning_session = Session(agent_type="stock", agent_id="stock_01", title="Owning session")
    other_session = Session(agent_type="stock", agent_id="stock_02", title="Other session")
    task = Task(session_id=owning_session.id, goal="Do not mutate via the wrong session")
    _store_session(owning_session)
    _store_session(other_session)
    _store_task(task, "stock", "stock_01")

    route = f"/api/v1/sessions/{other_session.id}/tasks/{task.id}"
    if route_suffix:
        route = f"{route}/{route_suffix}"

    with patch.object(
        state.sebastian._task_manager,
        "cancel",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_cancel:
        response = getattr(http_client, method)(
            route,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Task not found"
    mock_cancel.assert_not_awaited()

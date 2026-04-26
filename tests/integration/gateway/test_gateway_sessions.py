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
            with patch(
                "sebastian.orchestrator.sebas.Sebastian.run_streaming",
                new_callable=AsyncMock,
                return_value="Session reply",
            ) as mock_run_streaming:
                import sebastian.store.database as db_module

                db_module._engine = None
                db_module._session_factory = None

                data_subdir = tmp_path / "data"
                data_subdir.mkdir(exist_ok=True)
                (data_subdir / "secret.key").write_text("test-secret-key")

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

                from starlette.testclient import TestClient

                from sebastian.gateway.app import create_app

                test_app = create_app()
                with TestClient(test_app, raise_server_exceptions=True) as test_client:
                    yield test_client, mock_run_streaming, None


def _login(client) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _store_session(session) -> None:
    import sebastian.gateway.state as state

    asyncio.run(state.session_store.create_session(session))


def _store_task(task, agent_type: str, agent_id: str = "") -> None:
    import sebastian.gateway.state as state

    asyncio.run(state.session_store.create_task(task, agent_type))


def _capture_background_task(scheduled_coroutines: list[object]):
    import asyncio as _asyncio
    import inspect as _inspect
    import sys as _sys

    _real_create_task = _asyncio.create_task
    _ROUTE_MARKERS = ("gateway/routes/sessions.py", "gateway/routes/turns.py")
    _MOCK_MARKER = "unittest/mock.py"

    def _direct_caller_is_route() -> bool:
        """Find the first non-mock frame in the call stack and check if it's a route handler."""
        frame = _sys._getframe(2)  # skip inner() itself + mock._execute_mock_call
        while frame is not None:
            filename = frame.f_code.co_filename or ""
            if _MOCK_MARKER not in filename:
                # This is the first non-mock frame — the actual caller of create_task
                return any(m in filename for m in _ROUTE_MARKERS)
            frame = frame.f_back
        return False

    def inner(coroutine, **kwargs):
        # Only intercept coroutines created directly from gateway route handlers
        # (i.e. agent run_streaming session turns).  Pass through everything else
        # (e.g. SQLAlchemy's internal asyncio.create_task calls on session close).
        if _inspect.iscoroutine(coroutine) and _direct_caller_is_route():
            scheduled_coroutines.append(coroutine)
            coroutine.close()
            return MagicMock()
        return _real_create_task(coroutine, **kwargs)

    return inner


def test_list_sessions_empty(client):
    http_client, _, _ = client
    token = _login(http_client)

    response = http_client.get(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sessions"] == []
    assert body["total"] == 0


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

    asyncio.run(state.session_store.create_session(session))
    asyncio.run(
        state.session_store.append_message(
            session.id,
            "user",
            "Hello",
            agent_type="sebastian",
        )
    )

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


def test_send_turn_to_subagent_session_schedules_background_task(client):
    http_client, _, _ = client
    token = _login(http_client)

    # Register a mock agent instance for "code" (the only agent in test registry)
    from unittest.mock import AsyncMock as _AsyncMock

    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    mock_agent = _AsyncMock()
    mock_agent.run_streaming = _AsyncMock(return_value="Agent reply")
    original_instances = dict(state.agent_instances)
    state.agent_instances["code"] = mock_agent

    try:
        session = Session(agent_type="code", agent_id="code_01", title="Code session")
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

        stored_session = asyncio.run(state.session_store.get_session(session.id, "code"))
        assert stored_session is not None
        # Strip tzinfo for comparison: SQLite returns naive datetimes, Session uses UTC-aware.
        stored_naive = stored_session.updated_at.replace(tzinfo=None)
        original_naive = original_updated_at.replace(tzinfo=None)
        assert stored_naive >= original_naive
    finally:
        state.agent_instances.clear()
        state.agent_instances.update(original_instances)


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


# ──────────────────────────────────────────────────────────────────────────────
# POST /sessions/{session_id}/cancel
# ──────────────────────────────────────────────────────────────────────────────


def test_post_cancel_unknown_session_returns_404(client) -> None:
    """Non-existent session returns 404."""
    http_client, _, _ = client
    token = _login(http_client)

    resp = http_client.post(
        "/api/v1/sessions/nonexistent-session/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_post_cancel_idle_session_returns_200(client) -> None:
    """Session with no active stream returns 200 — a pending cancel is registered."""
    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    http_client, _, _ = client
    token = _login(http_client)

    session = Session(id="idle-cancel", agent_type="sebastian", title="t")
    asyncio.run(state.session_store.create_session(session))

    resp = http_client.post(
        "/api/v1/sessions/idle-cancel/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_sub_agent_turns_accepts_thinking_effort(client) -> None:
    """Test that POST /sessions/{id}/turns accepts thinking_effort for sub-agents."""
    from unittest.mock import AsyncMock as _AsyncMock

    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    http_client, _, _ = client
    token = _login(http_client)

    # Get first available agent from agent_instances
    sub_agent_type = next(iter(state.agent_instances.keys()))
    original_instances = dict(state.agent_instances)

    # Create a mock agent with tracking
    mock_agent = _AsyncMock()
    mock_agent.run_streaming = _AsyncMock(return_value="Agent reply")
    state.agent_instances[sub_agent_type] = mock_agent

    try:
        # Create a real session
        session = Session(
            agent_type=sub_agent_type, agent_id=f"{sub_agent_type}_01", title="Test session"
        )
        _store_session(session)

        scheduled_coroutines = []

        with patch(
            "sebastian.gateway.routes.sessions.asyncio.create_task",
            side_effect=_capture_background_task(scheduled_coroutines),
        ):
            resp = http_client.post(
                f"/api/v1/sessions/{session.id}/turns",
                json={"content": "follow up", "thinking_effort": "medium"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text
        assert len(scheduled_coroutines) == 1
        # A4: thinking_effort is no longer passed to run_streaming from the HTTP layer;
        # the agent reads it internally from llm_registry.get_provider().
        mock_agent.run_streaming.assert_called_once_with("follow up", session.id)
    finally:
        # Restore original
        state.agent_instances.clear()
        state.agent_instances.update(original_instances)


def test_cancel_right_after_turn_returns_200(client) -> None:
    """POST /cancel right after POST /turns must not 404 even before _active_streams is registered.

    Simulates the race: the background task created by POST /turns is intercepted and
    closed before run_streaming ever executes (so _active_streams is never populated).
    The immediately following POST /cancel must still return 200 by writing a pending
    cancel intent, and _pending_cancel_intents must be populated for that session.
    """
    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    http_client, mock_run_streaming, _ = client
    token = _login(http_client)

    session = Session(
        agent_type="sebastian",
        agent_id="sebastian_01",
        title="Race test session",
    )
    _store_session(session)

    scheduled_coroutines: list[object] = []

    # Intercept asyncio.create_task so run_streaming never actually runs
    # and _active_streams is never populated — this simulates the race window.
    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_capture_background_task(scheduled_coroutines),
    ):
        turn_resp = http_client.post(
            f"/api/v1/sessions/{session.id}/turns",
            json={"content": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert turn_resp.status_code == 200, turn_resp.text
    assert len(scheduled_coroutines) == 1  # background task was created and closed

    # _active_streams is NOT populated (run_streaming never ran).
    # Immediately cancel — must return 200, not 404.
    cancel_resp = http_client.post(
        f"/api/v1/sessions/{session.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancel_resp.status_code == 200, cancel_resp.text

    # The pending cancel intent must have been recorded in the agent.
    assert session.id in state.sebastian._pending_cancel_intents

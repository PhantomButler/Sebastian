from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared client fixture (mirrors test_gateway_sessions.py pattern exactly)
# ---------------------------------------------------------------------------


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
            ):
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
                    yield test_client


def _login(client) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _create_session(agent_type: str = "sebastian"):
    from sebastian.core.types import Session

    return Session(agent_type=agent_type, title="Compaction test session")


def _store_session(session) -> None:
    import sebastian.gateway.state as state

    asyncio.run(state.session_store.create_session(session))


# ---------------------------------------------------------------------------
# POST /sessions/{id}/compact — happy path: compacted
# ---------------------------------------------------------------------------


def test_compact_session_returns_compaction_result(client) -> None:
    """POST /compact returns JSON with status and metadata on success."""
    import sebastian.gateway.state as state
    from sebastian.context.compaction import CompactionResult

    http_client = client
    token = _login(http_client)

    session = _create_session()
    _store_session(session)

    mock_result = CompactionResult(
        status="compacted",
        summary_item_id="item-uuid-1",
        source_seq_start=1,
        source_seq_end=20,
        archived_item_count=15,
        source_token_estimate=12000,
        summary_token_estimate=800,
    )

    with patch.object(
        state.context_compaction_worker,
        "compact_session",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = http_client.post(
            f"/api/v1/sessions/{session.id}/compact",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "compacted"
    assert body["summary_item_id"] == "item-uuid-1"
    assert body["source_seq_start"] == 1
    assert body["source_seq_end"] == 20
    assert body["archived_item_count"] == 15
    assert body["source_token_estimate"] == 12000
    assert body["summary_token_estimate"] == 800


# ---------------------------------------------------------------------------
# POST /sessions/{id}/compact — skipped variant
# ---------------------------------------------------------------------------


def test_compact_session_returns_skipped_status(client) -> None:
    """POST /compact returns status=skipped when worker decides to skip."""
    import sebastian.gateway.state as state
    from sebastian.context.compaction import CompactionResult

    http_client = client
    token = _login(http_client)

    session = _create_session()
    _store_session(session)

    mock_result = CompactionResult(status="skipped", reason="range_too_small")

    with patch.object(
        state.context_compaction_worker,
        "compact_session",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = http_client.post(
            f"/api/v1/sessions/{session.id}/compact",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "range_too_small"


# ---------------------------------------------------------------------------
# POST /sessions/{id}/compact — 404 for unknown session
# ---------------------------------------------------------------------------


def test_compact_unknown_session_returns_404(client) -> None:
    http_client = client
    token = _login(http_client)

    resp = http_client.post(
        "/api/v1/sessions/nonexistent-id/compact",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /sessions/{id}/compact — 409 when session has an active stream
# ---------------------------------------------------------------------------


def test_compact_session_with_active_stream_returns_409(client) -> None:
    """POST /compact returns 409 when the session has an active running stream."""
    import sebastian.gateway.state as state

    http_client = client
    token = _login(http_client)

    session = _create_session()
    _store_session(session)

    # Simulate an active stream by patching _active_streams on sebastian
    mock_task = MagicMock()
    mock_task.done.return_value = False

    # Patch the sebastian agent's _active_streams to contain our session
    original = dict(state.sebastian._active_streams)
    state.sebastian._active_streams[session.id] = mock_task
    try:
        resp = http_client.post(
            f"/api/v1/sessions/{session.id}/compact",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        state.sebastian._active_streams.clear()
        state.sebastian._active_streams.update(original)

    assert resp.status_code == 409, resp.text
    assert "active" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /sessions/{id}/compaction/status
# ---------------------------------------------------------------------------


def test_compaction_status_returns_expected_fields(client) -> None:
    """GET /compaction/status returns token_estimate, last_summary_seq, etc."""
    import sebastian.gateway.state as state

    http_client = client
    token = _login(http_client)

    session = _create_session()
    _store_session(session)

    # Patch get_context_timeline_items to return an empty list
    with patch.object(
        state.session_store,
        "get_context_timeline_items",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = http_client.get(
            f"/api/v1/sessions/{session.id}/compaction/status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "token_estimate" in body
    assert "last_summary_seq" in body
    assert "compactable_exchange_count" in body
    assert "retained_recent_exchanges" in body
    # With empty timeline: estimator returns base overhead (8), no summary seq
    assert body["token_estimate"] >= 0
    assert body["last_summary_seq"] is None
    assert body["compactable_exchange_count"] == 0
    assert body["retained_recent_exchanges"] == 8


def test_compaction_status_reports_last_summary_seq(client) -> None:
    """GET /compaction/status picks up last context_summary seq from timeline."""
    import sebastian.gateway.state as state

    http_client = client
    token = _login(http_client)

    session = _create_session()
    _store_session(session)

    timeline = [
        {"seq": 1, "kind": "user_message", "content": "hello"},
        {"seq": 2, "kind": "assistant_message", "content": "hi"},
        {"seq": 3, "kind": "context_summary", "content": "summary text"},
        {"seq": 4, "kind": "user_message", "content": "continue"},
    ]

    with patch.object(
        state.session_store,
        "get_context_timeline_items",
        new_callable=AsyncMock,
        return_value=timeline,
    ):
        resp = http_client.get(
            f"/api/v1/sessions/{session.id}/compaction/status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_summary_seq"] == 3


def test_compaction_status_unknown_session_returns_404(client) -> None:
    http_client = client
    token = _login(http_client)

    resp = http_client.get(
        "/api/v1/sessions/nonexistent-id/compaction/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /sessions/{id}/compact — dry_run variant
# ---------------------------------------------------------------------------


def test_compact_session_dry_run_forwards_flag_and_returns_status(client) -> None:
    """Verifies the gateway forwards dry_run=True and returns the worker's dry_run response shape.

    DB non-persistence is covered by the unit test:
    tests/unit/context/test_compaction.py::test_worker_dry_run_skips_llm_and_returns_dry_run_status
    """
    import sebastian.gateway.state as state
    from sebastian.context.compaction import CompactionResult

    http_client = client
    token = _login(http_client)

    session = _create_session()
    _store_session(session)

    dry_run_result = CompactionResult(
        status="dry_run",
        source_seq_start=1,
        source_seq_end=16,
        archived_item_count=16,
        source_token_estimate=9500,
        summary_item_id=None,
    )

    with patch.object(
        state.context_compaction_worker,
        "compact_session",
        new_callable=AsyncMock,
        return_value=dry_run_result,
    ) as mock_compact:
        resp = http_client.post(
            f"/api/v1/sessions/{session.id}/compact",
            json={"dry_run": True},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "dry_run"
    assert body["summary_item_id"] is None
    assert body["source_token_estimate"] == 9500

    # Verify the gateway forwarded dry_run=True to the worker
    call_kwargs = mock_compact.call_args
    assert call_kwargs.kwargs.get("dry_run") is True

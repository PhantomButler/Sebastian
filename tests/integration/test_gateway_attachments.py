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

            app = create_app()
            with TestClient(app, raise_server_exceptions=True) as test_client:
                login_resp = test_client.post(
                    "/api/v1/auth/login",
                    json={"password": "testpass"},
                )
                assert login_resp.status_code == 200
                token = login_resp.json()["access_token"]

                yield test_client, token


def test_upload_text_file_returns_metadata(client) -> None:
    http_client, token = client

    response = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "text_file"
    assert body["status"] == "uploaded"
    assert "id" in body
    assert "sha256" in body
    assert body["filename"] == "notes.md"


def test_download_attachment_returns_original_bytes(client) -> None:
    http_client, token = client

    # Upload first
    upload_resp = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    att_id = upload_resp.json()["id"]

    # Download
    get_resp = http_client.get(
        f"/api/v1/attachments/{att_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.content == b"# hello"
    assert "text/markdown" in get_resp.headers.get("content-type", "")


def test_download_nonexistent_attachment_returns_404(client) -> None:
    http_client, token = client

    get_resp = http_client.get(
        "/api/v1/attachments/nonexistent-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 404


def test_upload_unsupported_kind_returns_400(client) -> None:
    http_client, token = client

    response = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "video"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422  # FastAPI form validation rejects unknown Literal


def test_upload_image_returns_metadata(client) -> None:
    http_client, token = client

    # Minimal valid JPEG header bytes
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )

    response = http_client.post(
        "/api/v1/attachments",
        files={"file": ("photo.jpg", jpeg_bytes, "image/jpeg")},
        data={"kind": "image"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "image"
    assert body["status"] == "uploaded"
    assert body["filename"] == "photo.jpg"


def test_upload_requires_auth(client) -> None:
    http_client, _token = client

    response = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
    )
    assert response.status_code == 401


def test_download_attachment_requires_auth(client) -> None:
    http_client, _ = client
    resp = http_client.get("/api/v1/attachments/nonexistent-id")
    assert resp.status_code == 401


def test_download_thumbnail_requires_auth(client) -> None:
    http_client, _ = client
    resp = http_client.get("/api/v1/attachments/nonexistent-id/thumbnail")
    assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Turn API + attachment timeline tests
# ─────────────────────────────────────────────────────────────────────────────


def _upload_text_file(http_client, token: str, content: bytes = b"# hello") -> str:
    """Upload a text_file attachment and return its ID."""
    resp = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", content, "text/markdown")},
        data={"kind": "text_file"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_send_turn_empty_content_no_attachments_is_rejected(client) -> None:
    """Empty content with no attachment_ids must return 400."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    resp = http_client.post(
        "/api/v1/turns",
        json={"content": "", "attachment_ids": []},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "content or attachment_ids required" in resp.text


def test_send_turn_too_many_attachments_is_rejected(client) -> None:
    """Sending > 5 attachments in a single turn must return 400."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    attachment_ids = [_upload_text_file(http_client, token, f"file {i}".encode()) for i in range(6)]

    resp = http_client.post(
        "/api/v1/turns",
        json={"content": "hello", "attachment_ids": attachment_ids},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "max 5 attachments" in resp.text


def test_send_turn_empty_content_with_attachment_is_allowed(client) -> None:
    """content="" with attachment_ids present must be accepted (returns 200)."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    att_id = _upload_text_file(http_client, token)

    with patch("sebastian.gateway.state.sebastian.run_streaming", new_callable=AsyncMock):
        resp = http_client.post(
            "/api/v1/turns",
            json={"content": "", "attachment_ids": [att_id]},
            headers=headers,
        )
    assert resp.status_code == 200, resp.text
    assert "session_id" in resp.json()


def test_send_turn_already_attached_attachment_rejected(client) -> None:
    """Submitting an already-attached attachment_id must return 409."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    att_id = _upload_text_file(http_client, token)

    # First turn: attaches the file
    with patch("sebastian.gateway.state.sebastian.run_streaming", new_callable=AsyncMock):
        first_resp = http_client.post(
            "/api/v1/turns",
            json={"content": "first", "attachment_ids": [att_id]},
            headers=headers,
        )
    assert first_resp.status_code == 200, first_resp.text

    # Second turn with the same attachment_id must fail (status != 'uploaded')
    resp = http_client.post(
        "/api/v1/turns",
        json={"content": "second", "attachment_ids": [att_id]},
        headers=headers,
    )
    assert resp.status_code == 409


def test_send_turn_with_attachment_writes_timeline(client) -> None:
    """Turn with attachment must write user_message + attachment timeline items sharing exchange_id."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    att_id = _upload_text_file(http_client, token)

    with patch("sebastian.gateway.state.sebastian.run_streaming", new_callable=AsyncMock):
        turn_resp = http_client.post(
            "/api/v1/turns",
            json={"content": "check this file", "attachment_ids": [att_id]},
            headers=headers,
        )
    assert turn_resp.status_code == 200, turn_resp.text
    session_id = turn_resp.json()["session_id"]

    # Retrieve session timeline
    session_resp = http_client.get(
        f"/api/v1/sessions/{session_id}",
        headers=headers,
    )
    assert session_resp.status_code == 200, session_resp.text
    timeline = session_resp.json()["timeline_items"]

    user_items = [t for t in timeline if t.get("kind") == "user_message"]
    att_items = [t for t in timeline if t.get("kind") == "attachment"]

    assert len(user_items) == 1, f"Expected 1 user_message, got {len(user_items)}"
    assert len(att_items) == 1, f"Expected 1 attachment item, got {len(att_items)}"

    # Both must share the same exchange_id
    assert user_items[0]["exchange_id"] is not None
    assert user_items[0]["exchange_id"] == att_items[0]["exchange_id"]

    # Attachment item payload must contain attachment_id
    assert att_items[0]["payload"]["attachment_id"] == att_id

    # Attachment status must now be 'attached'
    get_att_resp = http_client.get(
        f"/api/v1/attachments/{att_id}",
        headers=headers,
    )
    # After attachment the blob is readable (200 OK)
    assert get_att_resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Sub-agent session + attachment tests
# ─────────────────────────────────────────────────────────────────────────────


def test_concurrent_turns_cannot_double_attach_same_attachment(client) -> None:
    """Two concurrent turns referencing the same attachment must result in exactly one success."""
    import concurrent.futures

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    # Upload a single attachment
    resp = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    att_id = resp.json()["id"]

    with patch("sebastian.gateway.state.sebastian.run_streaming", new_callable=AsyncMock):

        def send_turn():
            return http_client.post(
                "/api/v1/turns",
                json={"content": "test", "attachment_ids": [att_id]},
                headers=headers,
            ).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1, f2 = executor.submit(send_turn), executor.submit(send_turn)
            statuses = [f1.result(), f2.result()]

    assert statuses.count(200) == 1, f"Expected exactly 1 success, got statuses={statuses}"
    assert any(s == 409 for s in statuses), f"Expected a 409, got statuses={statuses}"


def test_attachment_validation_failure_does_not_leave_dangling_session(client) -> None:
    """When attachment validation fails for a new session, the provisional session must be deleted."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    # Before: count sessions
    sessions_before = http_client.get("/api/v1/sessions", headers=headers)
    count_before = len(sessions_before.json())

    # Send turn with 6 attachments (no session_id → new session, exceeds limit)
    att_ids = [_upload_text_file(http_client, token, f"content {i}".encode()) for i in range(6)]
    resp = http_client.post(
        "/api/v1/turns",
        json={"content": "test", "attachment_ids": att_ids},
        headers=headers,
    )
    assert resp.status_code == 400

    # After: session count must be unchanged
    sessions_after = http_client.get("/api/v1/sessions", headers=headers)
    count_after = len(sessions_after.json())
    assert count_after == count_before, "A dangling session was created despite validation failure"


def test_create_agent_session_with_attachment_no_duplicate_user_message(client) -> None:
    """Sub-agent session creation with attachments should write user_message exactly once."""
    import asyncio as _asyncio
    import inspect as _inspect
    import sys as _sys
    from unittest.mock import MagicMock

    import sebastian.gateway.state as state

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    # Use the first registered sub-agent type (not the main sebastian orchestrator)
    agent_type = next(iter(state.agent_instances.keys()))

    # Upload attachment
    upload_resp = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# sub-agent test", "text/markdown")},
        data={"kind": "text_file"},
        headers=headers,
    )
    assert upload_resp.status_code == 201
    att_id = upload_resp.json()["id"]

    # Capture and discard the background agent task (suppress actual LLM call).
    # Only suppress coroutines dispatched from the sessions route file; let all
    # other asyncio.create_task calls (e.g. SQLAlchemy internals) pass through.
    from unittest.mock import MagicMock

    _real_create_task = _asyncio.create_task
    _SESSIONS_ROUTE = "gateway/routes/sessions.py"

    def _suppress_route_task(coroutine, **kwargs):
        frame = _sys._getframe(1)
        filename = frame.f_code.co_filename or ""
        if _SESSIONS_ROUTE in filename and _inspect.iscoroutine(coroutine):
            coroutine.close()
            mock_task = MagicMock()
            mock_task.done.return_value = True
            return mock_task
        return _real_create_task(coroutine, **kwargs)

    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_suppress_route_task,
    ):
        resp = http_client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "", "attachment_ids": [att_id]},
            headers=headers,
        )

    # Should succeed
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    # Get timeline
    detail_resp = http_client.get(
        f"/api/v1/sessions/{session_id}",
        headers=headers,
    )
    assert detail_resp.status_code == 200
    timeline = detail_resp.json()["timeline_items"]

    # Should have exactly one user_message and one attachment, both with same exchange_id
    user_items = [i for i in timeline if i["kind"] == "user_message"]
    att_items = [i for i in timeline if i["kind"] == "attachment"]
    assert len(user_items) == 1, f"expected 1 user_message, got {len(user_items)}"
    assert len(att_items) == 1, f"expected 1 attachment, got {len(att_items)}"
    assert user_items[0]["exchange_id"] == att_items[0]["exchange_id"]


def test_existing_agent_session_turn_with_attachment_writes_timeline(client) -> None:
    """Sending a turn with attachment to an existing sub-agent session writes timeline items."""
    import asyncio as _asyncio
    import inspect as _inspect
    import sys as _sys
    from unittest.mock import MagicMock

    import sebastian.gateway.state as state

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    # Use the first registered sub-agent type
    agent_type = next(iter(state.agent_instances.keys()))

    # ── helper to suppress background LLM tasks from sessions route ──────────
    _real_create_task = _asyncio.create_task
    _SESSIONS_ROUTE = "gateway/routes/sessions.py"

    def _suppress_route_task(coroutine, **kwargs):
        frame = _sys._getframe(1)
        filename = frame.f_code.co_filename or ""
        if _SESSIONS_ROUTE in filename and _inspect.iscoroutine(coroutine):
            coroutine.close()
            mock_task = MagicMock()
            mock_task.done.return_value = True
            return mock_task
        return _real_create_task(coroutine, **kwargs)

    # Step 1: Create a session (initial turn, no attachment)
    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_suppress_route_task,
    ):
        create = http_client.post(
            f"/api/v1/agents/{agent_type}/sessions",
            json={"content": "initial"},
            headers=headers,
        )
    assert create.status_code == 200, create.text
    session_id = create.json()["session_id"]

    # Step 2: Upload an attachment
    upload = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    att_id = upload.json()["id"]

    # Step 3: Send a follow-up turn to the existing session with the attachment
    with patch(
        "sebastian.gateway.routes.sessions.asyncio.create_task",
        side_effect=_suppress_route_task,
    ):
        turn = http_client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"content": "", "attachment_ids": [att_id]},
            headers=headers,
        )
    assert turn.status_code == 200, turn.text

    # Step 4: Verify the attachment timeline item was written
    detail = http_client.get(
        f"/api/v1/sessions/{session_id}?include_archived=true",
        headers=headers,
    )
    assert detail.status_code == 200
    timeline = detail.json()["timeline_items"]
    attachment_items = [
        item for item in timeline
        if item["kind"] == "attachment" and item["payload"]["attachment_id"] == att_id
    ]
    assert len(attachment_items) == 1, (
        f"Expected 1 attachment timeline item, got {len(attachment_items)}"
    )

    # Also verify a co-located user_message item sharing the same exchange_id was written
    attachment_exchange_id = attachment_items[0]["exchange_id"]
    user_message_items = [
        item for item in timeline
        if item["kind"] == "user_message" and item["exchange_id"] == attachment_exchange_id
    ]
    assert len(user_message_items) == 1, (
        f"Expected 1 user_message with exchange_id={attachment_exchange_id!r}, "
        f"got {len(user_message_items)}"
    )


def test_orphaned_attachment_cannot_be_reused_in_new_turn(client) -> None:
    """After a session is deleted (orphaning its attachment), reusing the attachment must return 409."""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: upload a text file
    att_id = _upload_text_file(http_client, token)

    # Step 2: attach it to a session by sending a turn (LLM call is mocked)
    with patch("sebastian.gateway.state.sebastian.run_streaming", new_callable=AsyncMock):
        turn_resp = http_client.post(
            "/api/v1/turns",
            json={"content": "check this file", "attachment_ids": [att_id]},
            headers=headers,
        )
    assert turn_resp.status_code == 200, turn_resp.text
    session_id = turn_resp.json()["session_id"]

    # Step 3: delete the session — backend calls mark_session_orphaned → attachment.status="orphaned"
    del_resp = http_client.delete(
        f"/api/v1/sessions/{session_id}",
        headers=headers,
    )
    assert del_resp.status_code == 200, del_resp.text

    # Step 4: try to reuse the same attachment_id in a new turn — must be rejected
    resp = http_client.post(
        "/api/v1/turns",
        json={"content": "reuse orphaned", "attachment_ids": [att_id]},
        headers=headers,
    )
    assert resp.status_code == 409, (
        f"Expected 409 for orphaned attachment, got {resp.status_code}: {resp.text}"
    )

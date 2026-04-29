from __future__ import annotations

import asyncio
import importlib
import os
import time
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
    assert "attachment_id" in body
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
    att_id = upload_resp.json()["attachment_id"]

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
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

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
    return resp.json()["attachment_id"]


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
    """Turn with attachment must write user_message + attachment timeline items
    sharing exchange_id."""
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


def test_send_file_tool_result_artifact_hydrates_without_model_content_leak(client) -> None:
    import sebastian.gateway.state as state

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    artifact = {
        "kind": "text_file",
        "attachment_id": "att-agent-1",
        "filename": "notes.md",
        "mime_type": "text/markdown",
        "size_bytes": 20,
        "download_url": "/api/v1/attachments/att-agent-1",
    }
    blocks = [
        {
            "type": "tool",
            "tool_call_id": "toolu_send_file",
            "tool_name": "send_file",
            "input": {"file_path": "/tmp/notes.md"},
            "status": "done",
            "assistant_turn_id": "turn-agent-file",
            "provider_call_index": 0,
            "block_index": 0,
        },
        {
            "type": "tool_result",
            "tool_call_id": "toolu_send_file",
            "tool_name": "send_file",
            "model_content": "已向用户发送文件 notes.md",
            "display": "已向用户发送文件 notes.md",
            "ok": True,
            "artifact": artifact,
            "assistant_turn_id": "turn-agent-file",
            "provider_call_index": 0,
            "block_index": 1,
        },
    ]

    async def fake_run_streaming(content: str, session_id: str, **_kwargs) -> str:
        await state.session_store.append_message(
            session_id,
            "assistant",
            "",
            agent_type="sebastian",
            blocks=blocks,
        )
        return ""

    with patch("sebastian.gateway.state.sebastian.run_streaming", side_effect=fake_run_streaming):
        turn_resp = http_client.post(
            "/api/v1/turns",
            json={"content": "send me the generated file"},
            headers=headers,
        )
    assert turn_resp.status_code == 200, turn_resp.text
    session_id = turn_resp.json()["session_id"]

    timeline = []
    for _ in range(20):
        detail_resp = http_client.get(
            f"/api/v1/sessions/{session_id}?include_archived=true",
            headers=headers,
        )
        assert detail_resp.status_code == 200, detail_resp.text
        timeline = detail_resp.json()["timeline_items"]
        if any(item["kind"] == "tool_result" for item in timeline):
            break
        time.sleep(0.05)

    result_items = [item for item in timeline if item["kind"] == "tool_result"]
    assert len(result_items) == 1
    result_item = result_items[0]
    payload = result_item["payload"]
    assert payload["artifact"]["attachment_id"] == "att-agent-1"
    assert "text_excerpt" not in payload["artifact"]
    assert result_item["content"] == "已向用户发送文件 notes.md"
    assert "attachment_id" not in result_item["content"]
    assert "text_excerpt" not in result_item["content"]
    assert "text_excerpt" not in payload
    assert "model_content" not in payload


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
    att_id = resp.json()["attachment_id"]

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
    """When attachment validation fails for a new session, the provisional session
    must be deleted."""
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
    att_id = upload_resp.json()["attachment_id"]

    # Capture and discard the background agent task (suppress actual LLM call).
    # Only suppress coroutines dispatched from the sessions route file; let all
    # other asyncio.create_task calls (e.g. SQLAlchemy internals) pass through.

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
    att_id = upload.json()["attachment_id"]

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
        item
        for item in timeline
        if item["kind"] == "attachment" and item["payload"]["attachment_id"] == att_id
    ]
    assert len(attachment_items) == 1, (
        f"Expected 1 attachment timeline item, got {len(attachment_items)}"
    )

    # Also verify a co-located user_message item sharing the same exchange_id was written
    attachment_exchange_id = attachment_items[0]["exchange_id"]
    user_message_items = [
        item
        for item in timeline
        if item["kind"] == "user_message" and item["exchange_id"] == attachment_exchange_id
    ]
    assert len(user_message_items) == 1, (
        f"Expected 1 user_message with exchange_id={attachment_exchange_id!r}, "
        f"got {len(user_message_items)}"
    )


def test_thumbnail_returns_real_thumb_when_present(client) -> None:
    """上传 image → /thumbnail 返回真正的缩略图（尺寸 ≤ 256）。"""
    from io import BytesIO

    from PIL import Image

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    img = Image.new("RGB", (1024, 768), color=(0, 100, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    payload = buf.getvalue()

    resp = http_client.post(
        "/api/v1/attachments",
        data={"kind": "image"},
        files={"file": ("photo.jpg", payload, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 201
    att_id = resp.json()["attachment_id"]

    thumb_resp = http_client.get(
        f"/api/v1/attachments/{att_id}/thumbnail",
        headers=headers,
    )
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"].startswith("image/jpeg")

    out = Image.open(BytesIO(thumb_resp.content))
    assert max(out.size) <= 256


def test_thumbnail_falls_back_to_blob_when_thumb_missing(client) -> None:
    """thumb 不存在但 blob 存在 → fallback 返回原图。"""
    from io import BytesIO

    from PIL import Image

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    img = Image.new("RGB", (200, 200), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    payload = buf.getvalue()

    resp = http_client.post(
        "/api/v1/attachments",
        data={"kind": "image"},
        files={"file": ("p.jpg", payload, "image/jpeg")},
        headers=headers,
    )
    att_id = resp.json()["attachment_id"]
    sha = resp.json()["sha256"]

    # 手动删除 thumb 文件，模拟老数据 / 生成失败
    import sebastian.gateway.state as state

    thumb_abs = state.attachment_store._root_dir / "thumbs" / sha[:2] / f"{sha}.jpg"
    thumb_abs.unlink(missing_ok=True)

    thumb_resp = http_client.get(
        f"/api/v1/attachments/{att_id}/thumbnail",
        headers=headers,
    )
    assert thumb_resp.status_code == 200
    # fallback 用 record.mime_type，仍是 image/jpeg
    assert thumb_resp.headers["content-type"].startswith("image/jpeg")
    # 但 body 是原图（尺寸 200×200）
    out = Image.open(BytesIO(thumb_resp.content))
    assert out.size == (200, 200)


def test_thumbnail_returns_400_for_text_file(client) -> None:
    """text_file 类型 attachment 调 /thumbnail 应返回 400。"""
    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    resp = http_client.post(
        "/api/v1/attachments",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"kind": "text_file"},
        headers=headers,
    )
    assert resp.status_code == 201
    att_id = resp.json()["attachment_id"]

    thumb_resp = http_client.get(
        f"/api/v1/attachments/{att_id}/thumbnail",
        headers=headers,
    )
    assert thumb_resp.status_code == 400
    assert "image" in thumb_resp.json()["detail"].lower()


def test_orphaned_attachment_cannot_be_reused_in_new_turn(client) -> None:
    """After a session is deleted (orphaning its attachment), reusing the attachment
    must return 409."""
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

    # Step 3: delete the session — backend calls mark_session_orphaned → status="orphaned"
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


def test_thumbnail_returns_404_when_thumb_and_blob_both_missing(client) -> None:
    """thumb 与原 blob 都被删除 → /thumbnail 返回 404。"""
    from io import BytesIO

    from PIL import Image

    http_client, token = client
    headers = {"Authorization": f"Bearer {token}"}

    img = Image.new("RGB", (100, 100), color=(50, 50, 50))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    payload = buf.getvalue()

    resp = http_client.post(
        "/api/v1/attachments",
        data={"kind": "image"},
        files={"file": ("p.jpg", payload, "image/jpeg")},
        headers=headers,
    )
    att_id = resp.json()["attachment_id"]
    sha = resp.json()["sha256"]

    # 手动删除 thumb 和 blob 文件
    import sebastian.gateway.state as state

    root = state.attachment_store._root_dir
    (root / "thumbs" / sha[:2] / f"{sha}.jpg").unlink(missing_ok=True)
    (root / "blobs" / sha[:2] / sha).unlink(missing_ok=True)

    thumb_resp = http_client.get(
        f"/api/v1/attachments/{att_id}/thumbnail",
        headers=headers,
    )
    assert thumb_resp.status_code == 404

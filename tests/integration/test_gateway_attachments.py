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
    assert response.status_code == 200, response.text
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
    assert upload_resp.status_code == 200, upload_resp.text
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
    assert response.status_code == 200, response.text
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

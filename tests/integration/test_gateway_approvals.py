from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SEBASTIAN_JWT_SECRET", "test-secret-key")
os.environ.setdefault("SEBASTIAN_DATA_DIR", "/tmp/sebastian_test")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret-key")

        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        import sebastian.store.database as db_module

        db_module._engine = None
        db_module._session_factory = None

        from starlette.testclient import TestClient

        from sebastian.gateway.app import create_app

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as test_client:
            import sebastian.gateway.state as state
            from sebastian.store.owner_store import OwnerStore

            async def _seed_owner() -> None:
                await OwnerStore(state.db_factory).create_owner(
                    name="test-owner",
                    password_hash=password_hash,
                )

            asyncio.run(_seed_owner())
            yield test_client


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    token = payload["access_token"]
    assert isinstance(token, str)
    return token


def test_list_approvals_uses_db_factory_and_returns_description(
    client: TestClient,
) -> None:
    import asyncio

    import sebastian.gateway.state as state
    from sebastian.store.models import ApprovalRecord

    async def seed() -> None:
        async with state.db_factory() as session:
            await session.merge(
                ApprovalRecord(
                    id="approval-1",
                    task_id="task-1",
                    session_id="session-1",
                    tool_name="shell",
                    tool_input={"cmd": "ls"},
                    status="pending",
                    created_at=datetime.now(UTC),
                    resolved_at=None,
                )
            )
            await session.commit()

    asyncio.run(seed())

    token = _login(client)
    response = client.get(
        "/api/v1/approvals",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    approval = response.json()["approvals"][0]
    assert approval["id"] == "approval-1"
    assert approval["description"]

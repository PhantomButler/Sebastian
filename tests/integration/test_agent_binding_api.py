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

            app = create_app()
            with TestClient(app, raise_server_exceptions=True) as test_client:
                login_resp = test_client.post(
                    "/api/v1/auth/login",
                    json={"password": "testpass"},
                )
                assert login_resp.status_code == 200
                token = login_resp.json()["access_token"]

                yield test_client, token


def _create_account(http_client, token, *, name: str) -> str:
    resp = http_client.post(
        "/api/v1/llm-accounts",
        json={
            "name": name,
            "catalog_provider_id": "anthropic",
            "api_key": "sk-ant-fake",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_list_agents_includes_sebastian_first(client) -> None:
    http_client, token = client

    resp = http_client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) >= 1
    first = agents[0]
    assert first["agent_type"] == "sebastian"
    assert first["is_orchestrator"] is True
    assert "binding" in first


def test_get_binding_for_sebastian_returns_record(client) -> None:
    http_client, token = client

    resp = http_client.get(
        "/api/v1/agents/sebastian/llm-binding",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_type"] == "sebastian"
    assert data["account_id"] is None
    assert data["model_id"] is None


def test_put_binding_with_thinking_effort(client) -> None:
    http_client, token = client

    aid = _create_account(http_client, token, name="Adaptive")

    resp = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "account_id": aid,
            "model_id": "claude-sonnet-4-6",
            "thinking_effort": "high",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == aid
    assert data["model_id"] == "claude-sonnet-4-6"
    # binding changed (none → set) → effort forced to None
    assert data["thinking_effort"] is None

    # Second PUT: same binding, effort preserved
    resp2 = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "account_id": aid,
            "model_id": "claude-sonnet-4-6",
            "thinking_effort": "high",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["thinking_effort"] == "high"


def test_put_binding_switching_account_forces_reset(client) -> None:
    http_client, token = client

    aid_a = _create_account(http_client, token, name="AccountA")
    aid_b = _create_account(http_client, token, name="AccountB")

    http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"account_id": aid_a, "model_id": "claude-sonnet-4-6"},
        headers={"Authorization": f"Bearer {token}"},
    )
    http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "account_id": aid_a,
            "model_id": "claude-sonnet-4-6",
            "thinking_effort": "high",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "account_id": aid_b,
            "model_id": "claude-sonnet-4-6",
            "thinking_effort": "high",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == aid_b
    assert data["thinking_effort"] is None


def test_put_binding_to_none_capability_model_clears_thinking(client) -> None:
    http_client, token = client

    aid = _create_account(http_client, token, name="NoThinking")

    http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"account_id": aid, "model_id": "claude-haiku-4-5"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={
            "account_id": aid,
            "model_id": "claude-haiku-4-5",
            "thinking_effort": "high",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["thinking_effort"] is None


def test_send_turn_with_extra_thinking_effort_field_is_accepted(client) -> None:
    from unittest.mock import AsyncMock, patch

    http_client, token = client

    with (
        patch(
            "sebastian.gateway.state.sebastian.get_or_create_session",
            new_callable=AsyncMock,
        ) as mock_session,
        patch(
            "sebastian.gateway.state.sebastian.run_streaming",
            new_callable=AsyncMock,
        ),
    ):
        from sebastian.core.types import Session

        mock_session.return_value = Session(
            agent_type="sebastian",
            title="test",
            goal="test",
        )

        resp = http_client.post(
            "/api/v1/turns",
            json={
                "content": "hello",
                "thinking_effort": "high",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200

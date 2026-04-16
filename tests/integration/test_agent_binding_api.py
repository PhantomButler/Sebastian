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

            asyncio.run(_seed())
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


def _create_provider(http_client, token, *, name: str, thinking_capability: str | None) -> str:
    """Helper: create a provider and return its id."""
    resp = http_client.post(
        "/api/v1/llm-providers",
        json={
            "name": name,
            "provider_type": "anthropic",
            "api_key": "sk-ant-fake",
            "model": "claude-opus-4-6",
            "base_url": "https://api.anthropic.com",
            **(
                {"thinking_capability": thinking_capability}
                if thinking_capability is not None
                else {}
            ),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_list_agents_includes_sebastian_first(client) -> None:
    """list_agents 返回的 agents 数组第一个元素是 sebastian，并带 is_orchestrator: True。"""
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
    """GET /agents/sebastian/llm-binding 返回 200（不再 403/404）。"""
    http_client, token = client

    resp = http_client.get(
        "/api/v1/agents/sebastian/llm-binding",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_type"] == "sebastian"
    # 未设置 binding 时 provider_id 为 None
    assert data["provider_id"] is None


def test_put_binding_with_thinking_fields(client) -> None:
    """PUT 接受 thinking_effort / thinking_adaptive，adaptive capability 下直接存储。"""
    http_client, token = client

    pid = _create_provider(http_client, token, name="Adaptive", thinking_capability="adaptive")

    # 首次 PUT：provider 从无到有，强制 reset — effort/adaptive 应被清空
    resp = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid, "thinking_effort": "high", "thinking_adaptive": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_id"] == pid
    # provider 切换（从无到有）→ 强制清空
    assert data["thinking_effort"] is None
    assert data["thinking_adaptive"] is False

    # 第二次 PUT：同一 provider，不切换 → effort/adaptive 直接保存
    resp2 = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid, "thinking_effort": "high", "thinking_adaptive": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["thinking_effort"] == "high"
    assert data2["thinking_adaptive"] is True


def test_put_binding_switching_provider_forces_reset(client) -> None:
    """切换 provider 时强制清空 effort/adaptive，忽略请求体里的值。"""
    http_client, token = client

    pid_a = _create_provider(http_client, token, name="ProviderA", thinking_capability="adaptive")
    pid_b = _create_provider(http_client, token, name="ProviderB", thinking_capability="adaptive")

    # 绑定到 A，同一 provider 再次 PUT 保存 effort
    http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid_a},
        headers={"Authorization": f"Bearer {token}"},
    )
    http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid_a, "thinking_effort": "high", "thinking_adaptive": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    # 切换到 B，即使请求体带了 effort/adaptive，应被强制清空
    resp = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid_b, "thinking_effort": "high", "thinking_adaptive": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_id"] == pid_b
    assert data["thinking_effort"] is None
    assert data["thinking_adaptive"] is False


def test_put_binding_to_none_capability_provider_clears_thinking(client) -> None:
    """binding 到 thinking_capability='none' 的 provider，强制清空 effort/adaptive。"""
    http_client, token = client

    pid = _create_provider(http_client, token, name="NoThinking", thinking_capability="none")

    # 先绑定到该 provider
    http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid},
        headers={"Authorization": f"Bearer {token}"},
    )

    # 同一 provider 再次 PUT 带上 effort/adaptive — capability=none 应强制清空
    resp = http_client.put(
        "/api/v1/agents/sebastian/llm-binding",
        json={"provider_id": pid, "thinking_effort": "high", "thinking_adaptive": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["thinking_effort"] is None
    assert data["thinking_adaptive"] is False


def test_send_turn_with_extra_thinking_effort_field_is_accepted(client) -> None:
    """带 thinking_effort 字段的请求体不应导致 422；字段被静默忽略（pydantic 默认 extra='ignore'）。

    A5 回归：DTO 里已删除该字段，客户端旧版本带此字段也不应报错。
    """
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
                "thinking_effort": "high",  # 已从 DTO 移除，应被 pydantic 静默忽略
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200

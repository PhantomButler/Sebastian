from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _build_app_with_mocks(agents: dict, bindings: list, all_records: list | None = None) -> FastAPI:
    import sebastian.gateway.state as state

    _records = all_records or []

    state.agent_registry = agents
    state.index_store = MagicMock()
    state.index_store.list_by_agent_type = AsyncMock(return_value=[])
    state.llm_registry = MagicMock()
    state.llm_registry.list_bindings = AsyncMock(return_value=bindings)
    state.llm_registry.list_all = AsyncMock(return_value=_records)
    state.llm_registry.get_binding = AsyncMock(
        side_effect=lambda agent_type: next(
            (b for b in bindings if b.agent_type == agent_type), None
        )
    )
    state.llm_registry.get_record = AsyncMock(
        side_effect=lambda provider_id: next((r for r in _records if r.id == provider_id), None)
    )

    app = FastAPI()
    from sebastian.gateway.auth import require_auth
    from sebastian.gateway.routes import agents as agents_mod

    async def _fake_auth() -> dict[str, str]:
        return {"user_id": "test"}

    app.dependency_overrides[require_auth] = _fake_auth
    app.include_router(agents_mod.router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_list_agents_includes_bound_provider_id_when_bound() -> None:
    from sebastian.agents._loader import AgentConfig
    from sebastian.store.models import AgentLLMBindingRecord

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="Code writer",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    bindings = [
        AgentLLMBindingRecord(agent_type="forge", provider_id="prov-123"),
    ]
    app = _build_app_with_mocks(agents, bindings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agents")
    assert resp.status_code == 200
    data = resp.json()
    # sebastian is always first
    assert data["agents"][0]["agent_type"] == "sebastian"
    forge = next(a for a in data["agents"] if a["agent_type"] == "forge")
    assert forge["binding"]["provider_id"] == "prov-123"


@pytest.mark.asyncio
async def test_list_agents_returns_null_bound_provider_when_unbound() -> None:
    from sebastian.agents._loader import AgentConfig

    agents = {
        "aide": AgentConfig(
            agent_type="aide",
            name="AideAgent",
            description="Research",
            max_children=2,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/agents")
    data = resp.json()
    aide = next(a for a in data["agents"] if a["agent_type"] == "aide")
    assert aide["binding"] is None


@pytest.mark.asyncio
async def test_put_binding_sets_provider_id() -> None:
    from sebastian.agents._loader import AgentConfig
    from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="Code writer",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    provider_record = LLMProviderRecord(
        id="prov-1",
        name="x",
        provider_type="anthropic",
        api_key_enc="k",
        model="m",
        is_default=False,
    )
    app = _build_app_with_mocks(agents, [], all_records=[provider_record])
    import sebastian.gateway.state as state

    state.llm_registry.set_binding = AsyncMock(
        return_value=AgentLLMBindingRecord(agent_type="forge", provider_id="prov-1")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/forge/llm-binding",
            json={"provider_id": "prov-1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_type"] == "forge"
    assert data["provider_id"] == "prov-1"
    # provider changed (none → prov-1), so effort forced to None
    state.llm_registry.set_binding.assert_awaited_once_with("forge", "prov-1", thinking_effort=None)


@pytest.mark.asyncio
async def test_put_binding_with_null_clears_binding() -> None:
    from sebastian.agents._loader import AgentConfig
    from sebastian.store.models import AgentLLMBindingRecord

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    import sebastian.gateway.state as state

    state.llm_registry.set_binding = AsyncMock(
        return_value=AgentLLMBindingRecord(agent_type="forge", provider_id=None)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/forge/llm-binding",
            json={"provider_id": None},
        )
    assert resp.status_code == 200
    assert resp.json()["provider_id"] is None


@pytest.mark.asyncio
async def test_put_binding_404_for_unknown_agent() -> None:
    app = _build_app_with_mocks({}, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/ghost/llm-binding",
            json={"provider_id": "prov-1"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_binding_400_for_unknown_provider() -> None:
    from sebastian.agents._loader import AgentConfig

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    # list_all returns empty → provider id "bogus" not found → 400
    app = _build_app_with_mocks(agents, [], all_records=[])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/agents/forge/llm-binding",
            json={"provider_id": "bogus"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_binding_returns_204() -> None:
    from sebastian.agents._loader import AgentConfig

    agents = {
        "forge": AgentConfig(
            agent_type="forge",
            name="ForgeAgent",
            description="",
            max_children=5,
            stalled_threshold_minutes=5,
            agent_class=MagicMock(),
        )
    }
    app = _build_app_with_mocks(agents, [])
    import sebastian.gateway.state as state

    state.llm_registry.clear_binding = AsyncMock(return_value=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/v1/agents/forge/llm-binding")
    assert resp.status_code == 204
    state.llm_registry.clear_binding.assert_awaited_once_with("forge")


@pytest.mark.asyncio
async def test_delete_binding_404_for_unknown_agent() -> None:
    app = _build_app_with_mocks({}, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/v1/agents/ghost/llm-binding")
    assert resp.status_code == 404

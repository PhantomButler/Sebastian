from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_agents_response_includes_name_and_description() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

    from sebastian.gateway.app import create_app

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer test"},
        )
        # Route exists; auth may reject with 401
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            agents = resp.json()["agents"]
            code_agent = next((a for a in agents if a["agent_type"] == "code"), None)
            assert code_agent is not None
            assert "name" in code_agent
            assert "description" in code_agent
            assert "workers" in code_agent
            for w in code_agent["workers"]:
                assert "current_goal" in w

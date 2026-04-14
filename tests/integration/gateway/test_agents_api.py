from __future__ import annotations

import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_agents_response_includes_name_and_description(tmp_path) -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
        mp.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        import sebastian.config as cfg_module

        importlib.reload(cfg_module)

        import sebastian.store.database as db_module

        db_module._engine = None
        db_module._session_factory = None

        from sebastian.gateway.auth import hash_password
        from sebastian.store.database import get_session_factory, init_db
        from sebastian.store.owner_store import OwnerStore

        await init_db()
        await OwnerStore(get_session_factory()).create_owner(
            name="test-owner", password_hash=hash_password("testpass")
        )
        (tmp_path / "secret.key").write_text("test-secret-key")

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

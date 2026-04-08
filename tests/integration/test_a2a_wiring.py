from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_gateway_starts_with_agent_registry_and_instances(tmp_path) -> None:
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

        async with app.router.lifespan_context(app):
            import sebastian.gateway.state as state

            assert hasattr(state, "agent_registry")
            assert hasattr(state, "agent_instances")
            assert "code" in state.agent_registry
            assert "code" in state.agent_instances

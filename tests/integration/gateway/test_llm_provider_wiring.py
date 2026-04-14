from __future__ import annotations

import importlib
import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.mark.asyncio
async def test_gateway_starts_and_has_llm_registry(tmp_path) -> None:
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
        importlib.reload(importlib.import_module("sebastian.config"))

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

            assert hasattr(state, "llm_registry")
            from sebastian.llm.registry import LLMProviderRegistry

            assert isinstance(state.llm_registry, LLMProviderRegistry)

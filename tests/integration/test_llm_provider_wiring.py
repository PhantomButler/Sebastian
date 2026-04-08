from __future__ import annotations

import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.mark.asyncio
async def test_gateway_starts_and_has_llm_registry(tmp_path) -> None:
    import importlib

    import sebastian.config as cfg_module

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
        importlib.reload(cfg_module)

        from sebastian.gateway.app import create_app

        app = create_app()

        async with app.router.lifespan_context(app):
            import sebastian.gateway.state as state

            assert hasattr(state, "llm_registry")
            from sebastian.llm.registry import LLMProviderRegistry

            assert isinstance(state.llm_registry, LLMProviderRegistry)

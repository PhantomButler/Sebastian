from __future__ import annotations

import os

import pytest


@pytest.mark.asyncio
async def test_gateway_starts_with_dispatcher_and_agent_registry() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")

    from sebastian.gateway.app import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        import sebastian.gateway.state as state

        assert hasattr(state, "dispatcher")
        assert hasattr(state, "agent_registry")
        assert "code" in state.agent_registry
        assert "stock" in state.agent_registry
        assert "life" in state.agent_registry

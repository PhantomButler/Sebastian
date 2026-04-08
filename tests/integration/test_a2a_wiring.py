from __future__ import annotations

import os

import pytest


@pytest.mark.asyncio
async def test_gateway_starts_with_agent_registry_and_instances() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

    from sebastian.gateway.app import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        import sebastian.gateway.state as state

        assert hasattr(state, "agent_registry")
        assert hasattr(state, "agent_instances")
        assert "code" in state.agent_registry
        assert "code" in state.agent_instances

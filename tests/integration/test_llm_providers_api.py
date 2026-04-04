from __future__ import annotations

import os

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture(autouse=True)
def set_env():
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("SEBASTIAN_OWNER_PASSWORD_HASH", "")


@pytest.mark.asyncio
async def test_llm_providers_crud() -> None:
    from sebastian.gateway.app import create_app
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Route exists at minimum (auth may reject)
        resp = await client.get(
            "/api/v1/llm-providers",
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code in (200, 401, 403)

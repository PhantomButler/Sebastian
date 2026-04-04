from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_llm_provider_record_roundtrip(db_session) -> None:
    from sqlalchemy import select

    from sebastian.store.models import LLMProviderRecord

    record = LLMProviderRecord(
        name="Claude Home",
        provider_type="anthropic",
        base_url=None,
        api_key="sk-ant-test",
        model="claude-opus-4-6",
        thinking_format=None,
        is_default=True,
    )
    db_session.add(record)
    await db_session.commit()

    result = await db_session.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.is_default)
    )
    loaded = result.scalar_one()
    assert loaded.name == "Claude Home"
    assert loaded.api_key == "sk-ant-test"
    assert loaded.provider_type == "anthropic"
    assert loaded.is_default is True

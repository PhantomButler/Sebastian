from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.types import Session
from sebastian.store.index_store import IndexStore


@pytest.mark.asyncio
async def test_upsert_stores_goal(tmp_path: Path):
    store = IndexStore(tmp_path)
    session = Session(
        agent_type="code",
        title="写代码",
        goal="重构 auth 模块",
        depth=2,
    )
    await store.upsert(session)
    entries = await store.list_all()
    assert len(entries) == 1
    assert entries[0]["goal"] == "重构 auth 模块"


@pytest.mark.asyncio
async def test_upsert_goal_distinct_from_title(tmp_path: Path):
    store = IndexStore(tmp_path)
    session = Session(
        agent_type="code",
        title="写代码",
        goal="重构 auth 模块，保持接口兼容",
        depth=2,
    )
    await store.upsert(session)
    entries = await store.list_all()
    assert entries[0]["goal"] != entries[0]["title"]

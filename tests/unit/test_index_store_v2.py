from __future__ import annotations

import pytest
from pathlib import Path
from sebastian.core.types import Session
from sebastian.store.index_store import IndexStore


@pytest.mark.asyncio
async def test_upsert_writes_new_fields(tmp_path: Path):
    store = IndexStore(tmp_path)
    session = Session(
        id="test1", agent_type="code", title="test", depth=2,
        parent_session_id=None,
    )
    await store.upsert(session)
    entries = await store.list_all()
    entry = entries[0]
    assert entry["depth"] == 2
    assert entry["parent_session_id"] is None
    assert "last_activity_at" in entry
    assert "agent_id" not in entry


@pytest.mark.asyncio
async def test_list_active_children(tmp_path: Path):
    store = IndexStore(tmp_path)
    parent = Session(id="parent1", agent_type="code", title="parent", depth=2)
    await store.upsert(parent)
    child1 = Session(id="child1", agent_type="code", title="c1", depth=3, parent_session_id="parent1")
    child2 = Session(id="child2", agent_type="code", title="c2", depth=3, parent_session_id="parent1")
    await store.upsert(child1)
    await store.upsert(child2)
    children = await store.list_active_children("code", "parent1")
    assert len(children) == 2

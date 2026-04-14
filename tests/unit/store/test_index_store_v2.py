from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.types import Session, SessionStatus
from sebastian.store.index_store import IndexStore


@pytest.mark.asyncio
async def test_upsert_writes_new_fields(tmp_path: Path):
    store = IndexStore(tmp_path)
    session = Session(
        id="test1",
        agent_type="code",
        title="test",
        depth=2,
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
    child1 = Session(
        id="child1", agent_type="code", title="c1", depth=3, parent_session_id="parent1"
    )
    child2 = Session(
        id="child2", agent_type="code", title="c2", depth=3, parent_session_id="parent1"
    )
    await store.upsert(child1)
    await store.upsert(child2)
    children = await store.list_active_children("code", "parent1")
    assert len(children) == 2


@pytest.mark.asyncio
async def test_list_active_children_excludes_inactive(tmp_path: Path):
    store = IndexStore(tmp_path)
    # Active child
    active_child = Session(
        id="child_active", agent_type="code", title="active", depth=3, parent_session_id="parent1"
    )
    await store.upsert(active_child)
    # Completed child — should be excluded
    completed_child = Session(
        id="child_done", agent_type="code", title="done", depth=3, parent_session_id="parent1"
    )
    completed_child = completed_child.model_copy(update={"status": SessionStatus.COMPLETED})
    await store.upsert(completed_child)
    children = await store.list_active_children("code", "parent1")
    assert len(children) == 1
    assert children[0]["id"] == "child_active"


@pytest.mark.asyncio
async def test_list_active_children_includes_stalled(tmp_path: Path):
    """stalled session 仍应占 max_children 位。"""
    store = IndexStore(tmp_path)
    parent = Session(id="parent2", agent_type="code", title="parent", depth=2)
    await store.upsert(parent)

    active_child = Session(
        id="child_active2",
        agent_type="code",
        title="active",
        depth=3,
        parent_session_id="parent2",
    )
    stalled_child = Session(
        id="child_stalled",
        agent_type="code",
        title="stalled",
        depth=3,
        parent_session_id="parent2",
        status=SessionStatus.STALLED,
    )
    await store.upsert(active_child)
    await store.upsert(stalled_child)

    children = await store.list_active_children("code", "parent2")
    assert len(children) == 2  # both active and stalled count


@pytest.mark.asyncio
async def test_list_active_children_concurrent_count_is_bounded(tmp_path: Path):
    """验证 list_active_children 在并发场景下正确计数，不能因为竞态而少算。"""
    import asyncio

    store = IndexStore(tmp_path)
    parent = Session(id="p_concurrent", agent_type="code", title="parent", depth=2)
    await store.upsert(parent)

    # 先放一个 stalled child
    stalled = Session(
        id="stalled_concurrent",
        agent_type="code",
        title="s",
        depth=3,
        parent_session_id="p_concurrent",
        status=SessionStatus.STALLED,
    )
    await store.upsert(stalled)

    # 并发查询 5 次，结果应该一致且都包含 stalled session
    results = await asyncio.gather(
        *[store.list_active_children("code", "p_concurrent") for _ in range(5)]
    )
    for r in results:
        assert len(r) == 1
        assert r[0]["status"] == "stalled"

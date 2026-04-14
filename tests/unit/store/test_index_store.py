from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.types import Session
from sebastian.store.index_store import IndexStore


@pytest.fixture
def tmp_sessions_dir(tmp_path: Path) -> Path:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    return sessions_dir


@pytest.mark.asyncio
async def test_upsert_and_list(tmp_sessions_dir: Path) -> None:
    store = IndexStore(tmp_sessions_dir)
    session = Session(agent_type="sebastian", title="Hello")

    await store.upsert(session)

    sessions = await store.list_all()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session.id
    assert sessions[0]["agent_type"] == "sebastian"


@pytest.mark.asyncio
async def test_upsert_updates_existing(tmp_sessions_dir: Path) -> None:
    store = IndexStore(tmp_sessions_dir)
    session = Session(
        agent_type="sebastian",
        title="Original",
    )

    await store.upsert(session)
    session.title = "Updated"
    await store.upsert(session)

    sessions = await store.list_all()
    assert len(sessions) == 1
    assert sessions[0]["title"] == "Updated"


@pytest.mark.asyncio
async def test_list_by_agent_type(tmp_sessions_dir: Path) -> None:
    store = IndexStore(tmp_sessions_dir)
    session_one = Session(agent_type="sebastian", title="Chat 1")
    session_two = Session(agent_type="stock", title="Stock 1")
    session_three = Session(agent_type="stock", title="Stock 2")

    await store.upsert(session_one)
    await store.upsert(session_two)
    await store.upsert(session_three)

    by_type = await store.list_by_agent_type("stock")

    assert len(by_type) == 2
    assert all(s["agent_type"] == "stock" for s in by_type)


@pytest.mark.asyncio
async def test_prune_orphans(tmp_sessions_dir: Path) -> None:
    """剔除磁盘目录不存在的索引条目；保留有目录的；返回被剔除条目。"""
    store = IndexStore(tmp_sessions_dir)
    alive = Session(agent_type="sebastian", title="alive")
    orphan = Session(agent_type="forge", title="orphan")
    await store.upsert(alive)
    await store.upsert(orphan)

    # 仅给 alive 建磁盘目录，orphan 没有
    (tmp_sessions_dir / alive.agent_type / alive.id).mkdir(parents=True)

    dropped = await store.prune_orphans(tmp_sessions_dir)

    assert [d["id"] for d in dropped] == [orphan.id]
    remaining = await store.list_all()
    assert [s["id"] for s in remaining] == [alive.id]


@pytest.mark.asyncio
async def test_prune_orphans_noop_when_all_alive(tmp_sessions_dir: Path) -> None:
    store = IndexStore(tmp_sessions_dir)
    s = Session(agent_type="sebastian", title="x")
    await store.upsert(s)
    (tmp_sessions_dir / s.agent_type / s.id).mkdir(parents=True)

    dropped = await store.prune_orphans(tmp_sessions_dir)

    assert dropped == []
    assert len(await store.list_all()) == 1

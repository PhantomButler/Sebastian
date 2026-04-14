from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.types import Session
from sebastian.store.session_store import SessionStore


@pytest.mark.asyncio
async def test_subagent_session_path(tmp_path: Path) -> None:
    """Sub-agent sessions stored at {agent_type}/{session_id}/ without agent_id."""
    store = SessionStore(tmp_path)
    session = Session(id="test123", agent_type="code", title="test", depth=2)
    await store.create_session(session)
    expected_dir = tmp_path / "code" / "test123"
    assert expected_dir.exists(), f"Expected {expected_dir} to exist"
    assert "subagents" not in str(expected_dir)


@pytest.mark.asyncio
async def test_depth3_session_path(tmp_path: Path) -> None:
    """depth=3 的 session 存储路径格式与 depth=2 相同：{agent_type}/{session_id}/。"""
    store = SessionStore(tmp_path)
    session = Session(
        id="deep456",
        agent_type="stock",
        title="test",
        depth=3,
        parent_session_id="parent-123",
    )
    await store.create_session(session)
    expected_dir = tmp_path / "stock" / "deep456"
    assert expected_dir.exists(), f"Expected {expected_dir} to exist"
    assert "subagents" not in str(expected_dir)


@pytest.mark.asyncio
async def test_depth3_parent_session_id_persisted(tmp_path: Path) -> None:
    """depth=3 session 的 parent_session_id 写入 meta.json 后可读回。"""
    store = SessionStore(tmp_path)
    session = Session(
        id="child789",
        agent_type="research",
        title="test",
        depth=3,
        parent_session_id="parent-abc",
    )
    await store.create_session(session)
    loaded = await store.get_session("child789", "research")
    assert loaded is not None
    assert loaded.parent_session_id == "parent-abc"
    assert loaded.depth == 3


@pytest.mark.asyncio
async def test_sebastian_session_path(tmp_path: Path) -> None:
    """Sebastian 主会话（depth=1）存储路径为 {sessions_dir}/sebastian/{session_id}/。"""
    store = SessionStore(tmp_path)
    session = Session(
        id="seb123",
        agent_type="sebastian",
        title="test",
        depth=1,
    )
    await store.create_session(session)
    expected_dir = tmp_path / "sebastian" / "seb123"
    assert expected_dir.exists(), f"Expected {expected_dir} to exist"

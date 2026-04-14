from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_session_store_update_activity_updates_last_activity(tmp_path: Path) -> None:
    """SessionStore.update_activity 更新 meta.json 中的 last_activity_at。"""
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    store = SessionStore(tmp_path)
    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    await store.create_session(session)

    old_meta = json.loads((tmp_path / "code" / session.id / "meta.json").read_text())
    old_ts = old_meta["last_activity_at"]

    await asyncio.sleep(0.01)  # ensure timestamp differs
    await store.update_activity(session.id, "code")

    new_meta = json.loads((tmp_path / "code" / session.id / "meta.json").read_text())
    assert new_meta["last_activity_at"] != old_ts


@pytest.mark.asyncio
async def test_session_store_update_activity_transitions_stalled_to_active(tmp_path: Path) -> None:
    """SessionStore.update_activity 将 stalled 状态转为 active。"""
    from sebastian.core.types import Session, SessionStatus
    from sebastian.store.session_store import SessionStore

    store = SessionStore(tmp_path)
    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    session.status = SessionStatus.STALLED
    await store.create_session(session)

    await store.update_activity(session.id, "code")

    meta = json.loads((tmp_path / "code" / session.id / "meta.json").read_text())
    assert meta["status"] == "active"


@pytest.mark.asyncio
async def test_session_store_update_activity_noop_when_meta_missing(tmp_path: Path) -> None:
    """SessionStore.update_activity 在 meta.json 不存在时静默跳过。"""
    from sebastian.store.session_store import SessionStore

    store = SessionStore(tmp_path)
    # Should not raise
    await store.update_activity("nonexistent-session", "code")


@pytest.mark.asyncio
async def test_index_store_update_activity_syncs_meta(tmp_path: Path) -> None:
    """IndexStore.update_activity 注入 session_store 后同步写 meta.json。"""
    from sebastian.core.types import Session, SessionStatus
    from sebastian.store.index_store import IndexStore
    from sebastian.store.session_store import SessionStore

    session_store = SessionStore(tmp_path)
    index_store = IndexStore(tmp_path, session_store=session_store)

    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    session.status = SessionStatus.STALLED
    await session_store.create_session(session)
    await index_store.upsert(session)

    await index_store.update_activity(session.id)

    meta = json.loads((tmp_path / "code" / session.id / "meta.json").read_text())
    assert meta["status"] == "active"
    assert meta["last_activity_at"] is not None


@pytest.mark.asyncio
async def test_index_store_update_activity_without_session_store(tmp_path: Path) -> None:
    """IndexStore.update_activity 不注入 session_store 时仅写 index.json，不报错。"""
    from sebastian.core.types import Session
    from sebastian.store.index_store import IndexStore

    index_store = IndexStore(tmp_path)  # no session_store

    session = Session(agent_type="code", title="test", goal="test goal", depth=2)
    await index_store.upsert(session)

    # Should not raise
    await index_store.update_activity(session.id)

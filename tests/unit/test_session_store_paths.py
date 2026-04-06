from __future__ import annotations

import pytest
from pathlib import Path

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

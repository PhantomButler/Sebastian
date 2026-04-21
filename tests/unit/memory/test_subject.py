from __future__ import annotations

import pytest

from sebastian.memory.subject import resolve_subject
from sebastian.memory.types import MemoryScope


@pytest.mark.asyncio
async def test_resolve_subject_user_scope_defaults_to_owner() -> None:
    assert await resolve_subject(MemoryScope.USER, session_id="s1", agent_type="default") == "owner"


@pytest.mark.asyncio
async def test_resolve_subject_agent_scope_uses_agent_type() -> None:
    assert (
        await resolve_subject(MemoryScope.AGENT, session_id="s1", agent_type="calendar")
        == "agent:calendar"
    )


@pytest.mark.asyncio
async def test_resolve_subject_session_scope_uses_session_id() -> None:
    assert (
        await resolve_subject(MemoryScope.SESSION, session_id="s1", agent_type="default")
        == "session:s1"
    )


@pytest.mark.asyncio
async def test_resolve_subject_project_scope_defaults_to_owner() -> None:
    assert (
        await resolve_subject(MemoryScope.PROJECT, session_id="s1", agent_type="default") == "owner"
    )

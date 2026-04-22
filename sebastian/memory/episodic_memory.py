from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sebastian.store.session_store import SessionStore


@dataclass
class TurnEntry:
    role: str
    content: str
    ts: str


class EpisodicMemory:
    """Conversation history backed by the file-based SessionStore.

    DEPRECATED: EpisodicMemory is no longer used at runtime.  Conversation
    history is now managed via SessionTimelineStore (SQLite) accessed through
    SessionStore.  This class is kept only because MemoryStore still references
    it; both will be removed in a future release.
    """

    def __init__(self, session_store: SessionStore) -> None:
        self._store = session_store

    async def _get_agent_context(self, session_id: str, agent: str) -> str:
        session = await self._store.get_session_for_agent_type(session_id, agent)
        if session is None:
            raise FileNotFoundError(f"Session {session_id!r} not found for agent_type {agent!r}")
        return session.agent_type

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: str = "sebastian",
        blocks: list[dict[str, Any]] | None = None,
    ) -> TurnEntry:
        agent_type = await self._get_agent_context(session_id, agent)
        await self._store.append_message(
            session_id,
            role,
            content,
            agent_type=agent_type,
            blocks=blocks,
        )
        return TurnEntry(
            role=role,
            content=content,
            ts=datetime.now(UTC).isoformat(),
        )

    async def get_turns(
        self,
        session_id: str,
        agent: str = "sebastian",
        limit: int = 50,
    ) -> list[TurnEntry]:
        agent_type = await self._get_agent_context(session_id, agent)
        messages = await self._store.get_messages(
            session_id,
            agent_type=agent_type,
            limit=limit,
        )
        return [
            TurnEntry(role=message["role"], content=message["content"], ts=message.get("ts", ""))
            for message in messages
        ]
